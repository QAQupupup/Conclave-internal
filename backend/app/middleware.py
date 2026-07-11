# 请求追踪中间件：每个 HTTP 请求分配 request_id，设置到 contextvars
# API 认证中间件：基于 token 的简单认证 + 速率限制
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from collections import defaultdict
from threading import Lock
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse

from app.context import new_request_id, set_request_id, reset_request_id
from app.logging_config import get_logger

logger = get_logger("middleware.trace")

# API 认证 token（留空则不启用认证，仅开发模式）
# [CON-03 修复] 旧版 token 留空 = 完全无认证。改为：
#   1) 默认生成一个稳定的开发 token（写入 .dev_token 供前端读取）
#   2) token 比较改用 hmac.compare_digest 防时序攻击
#   3) 增加每 IP 速率限制
_API_TOKEN = os.environ.get("CONCLAVE_API_TOKEN", "")
_DEV_TOKEN_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), ".dev_token"
)


def _load_or_create_dev_token() -> str:
    """读取或生成开发 token。

    策略：
    - 如果 .dev_token 文件存在：读取其值
    - 不存在：生成 32 字节随机 token，hex 后写入 .dev_token
    - 第一次启动时打印到日志（开发模式）
    """
    if _API_TOKEN:
        return _API_TOKEN
    if os.path.exists(_DEV_TOKEN_PATH):
        with open(_DEV_TOKEN_PATH, "r", encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            return tok
    # 生成新 token
    token = hashlib.sha256(os.urandom(32)).hexdigest()[:48]
    try:
        with open(_DEV_TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(token)
        os.chmod(_DEV_TOKEN_PATH, 0o600)  # 仅 owner 可读写
        logger.warning(
            "首次启动：已生成开发 token 写入 %s，请前端配置后访问。生产环境必须设置 CONCLAVE_API_TOKEN。",
            _DEV_TOKEN_PATH,
        )
    except OSError as e:
        logger.error("无法写入 dev_token 文件: %s；使用内存 token（重启失效）", e)
    return token


_DEV_TOKEN = _load_or_create_dev_token()

# 免认证路径前缀
# [CON-03 修复] /debug/auth-info 必须公开：前端首次启动时需要拿 dev token，
# 否则永远拿不到 token 形成鸡生蛋。
_PUBLIC_PATHS = {"/health", "/metrics", "/docs", "/openapi.json", "/redoc", "/debug/auth-info"}
# WebSocket 升级路径免认证（WebSocket 在 query 参数中传 token）
_WS_PATHS = {"/ws"}

# ---- 速率限制 ----
# [CON-03 修复] 防止暴力破解 + DoS
# 默认：每 IP 600 次/分钟（10 req/sec），认证失败 5 次/分钟封禁 60 秒
# 600/min 适配 Conclave 正常使用场景：侧边栏轮询(12/min) + 工作区文件操作 + 会议状态查询
_RATE_LIMIT_PER_MIN = int(os.environ.get("CONCLAVE_RATE_LIMIT_PER_MIN", "600"))
_RATE_LIMIT_FAIL_PER_MIN = int(os.environ.get("CONCLAVE_RATE_LIMIT_FAIL_PER_MIN", "5"))
_RATE_BLOCK_SECONDS = int(os.environ.get("CONCLAVE_RATE_BLOCK_SECONDS", "60"))

_request_log: dict[str, list[float]] = defaultdict(list)
_fail_log: dict[str, list[float]] = defaultdict(list)
_blocked_ips: dict[str, float] = {}  # ip -> block_until_timestamp
_rate_lock = Lock()


def _client_ip(request: Request) -> str:
    """提取客户端 IP（优先 X-Forwarded-For 首段，再退化到 client.host）"""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check_rate_limit(ip: str, is_failed_attempt: bool = False) -> tuple[bool, str]:
    """检查 IP 是否被限流。返回 (allowed, reason)。"""
    now = time.monotonic()
    with _rate_lock:
        # 1) 已被封禁？
        block_until = _blocked_ips.get(ip)
        if block_until and now < block_until:
            remaining = int(block_until - now)
            return False, f"IP 已被临时封禁，{remaining}s 后解除"
        elif block_until:
            _blocked_ips.pop(ip, None)

        # 2) 滑动窗口
        window = 60.0
        if is_failed_attempt:
            log = _fail_log[ip]
            limit = _RATE_LIMIT_FAIL_PER_MIN
            label = "失败"
        else:
            log = _request_log[ip]
            limit = _RATE_LIMIT_PER_MIN
            label = "请求"

        # 清理过期记录
        log[:] = [t for t in log if now - t < window]
        if len(log) >= limit:
            if is_failed_attempt:
                _blocked_ips[ip] = now + _RATE_BLOCK_SECONDS
                return False, f"连续失败 {limit} 次，封禁 {_RATE_BLOCK_SECONDS}s"
            return False, f"超过每分钟 {limit} 次{label}上限"
        log.append(now)
        return True, "ok"


def _is_public(path: str) -> bool:
    """判断路径是否免认证"""
    for p in _PUBLIC_PATHS:
        if path == p or path.startswith(p + "/") or path.startswith(p + "?"):
            return True
    return False


def setup_auth_middleware(app: FastAPI) -> None:
    """注册 API 认证中间件

    认证策略（[CON-03 修复]）：
    - CONCLAVE_API_TOKEN 未设置 → 加载/生成 .dev_token（开发模式但仍需认证）
    - 任何情况都启用认证（除公开路径外）
    - token 比较用 hmac.compare_digest 防时序攻击
    - 每 IP 速率限制
    - 失败 5 次/分钟自动封禁 60 秒
    """

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next) -> Response:
        path = request.url.path
        client_ip = _client_ip(request)

        # 公开路径免认证 + 免限流
        if _is_public(path):
            return await call_next(request)

        # 速率限制（即使是未认证请求也限流，防止扫描）
        ok, reason = _check_rate_limit(client_ip, is_failed_attempt=False)
        if not ok:
            return JSONResponse(
                status_code=429,
                content={"detail": f"请求过快：{reason}"},
                headers={"Retry-After": "60"},
            )

        # 提取 token
        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        if not token:
            token = request.query_params.get("token", "")

        # [CON-03 修复] 用 hmac.compare_digest 防时序攻击
        # 比较前必须确保两个字符串类型一致
        if not token or not hmac.compare_digest(
            token.encode("utf-8"),
            _DEV_TOKEN.encode("utf-8"),
        ):
            # 失败计数
            ok2, _reason2 = _check_rate_limit(client_ip, is_failed_attempt=True)
            if not ok2:
                logger.warning("IP %s 触发封禁：%s", client_ip, _reason2)
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"认证失败过多：{_reason2}"},
                    headers={"Retry-After": str(_RATE_BLOCK_SECONDS)},
                )
            return JSONResponse(
                status_code=401,
                content={"detail": "未授权：请提供有效的 API token"},
            )

        return await call_next(request)


# ---- 命令注入防护 ----

# 危险命令模式（正则匹配，比精确匹配更难绕过）
_DANGEROUS_PATTERNS = [
    r"\brm\s+(-{1,2}\w+\s+)*-?r\w*\s+(-{1,2}\w+\s+)*[/~.*]",  # rm -rf / 或 rm -rf ~ 或 rm -rf . 或 rm -rf *
    r"\brm\s+(-{1,2}\w+\s+)*-?r\w*\s+\*",  # rm -rf *（删所有文件）
    r"\bmkfs\b",              # 格式化文件系统
    r"\b(?:shutdown|reboot|halt|poweroff)\b",  # 系统关机/重启
    r"\bdd\s+if=.+of=/dev/",  # dd 写设备
    r">\s*/dev/sd[a-z]",      # 重定向到块设备
    r"\bchmod\s+-R\s+777\s+/",  # 全盘改权限
    r"\b(?:curl|wget)\s+.+\|\s*/?(?:bash|sh|/bin/bash|/bin/sh)",  # curl|bash 含路径前缀
    r"\b(?:curl|wget)\s+.+\|\s*(?:bash|sh)",  # curl | shell 远程执行
    r"\beval\s+\$\(?",       # eval 命令注入
    r"\beval\s+\$\w+",       # eval $CMD 变量展开
    r"\bnc\s+.*-e\s+/bin/sh",  # netcat 反弹 shell
    r"\bpython\s+-c\s+.*import\s+subprocess",  # python subprocess 注入
    r"\bpython\s+-c\s+.*import\s+os",  # python os 模块注入
]


def is_dangerous_command(command: str) -> bool:
    """检测命令是否包含危险模式"""
    cmd = command.strip()
    for pattern in _DANGEROUS_PATTERNS:
        if re.search(pattern, cmd, re.IGNORECASE):
            return True
    return False


def setup_trace_middleware(app: FastAPI) -> None:
    """注册请求追踪中间件

    每个 HTTP 请求进入时：
    1. 分配唯一 request_id（或从 X-Request-Id header 继承）
    2. 设置到 contextvars（异步安全）
    3. 响应时在 header 中返回 X-Request-Id
    4. 记录请求日志（方法、路径、状态码、耗时）
    """

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next) -> Response:
        # 从 header 继承或生成新的 request_id
        rid = request.headers.get("X-Request-Id") or new_request_id()
        token = set_request_id(rid)

        t0 = time.monotonic()
        method = request.method
        path = request.url.path

        try:
            response = await call_next(request)
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            logger.error(
                "request_id=%s %s %s 500 %.0fms [异常: %s]",
                rid, method, path, elapsed, type(e).__name__,
            )
            raise
        finally:
            reset_request_id(token)

        elapsed = (time.monotonic() - t0) * 1000
        status = response.status_code

        # 记录到运维面板指标
        try:
            from app.observability.metrics_store import get_metrics_store
            get_metrics_store().record_request(elapsed)
        except Exception:
            pass

        # 按状态码级别记录日志
        if status >= 500:
            logger.error(
                "request_id=%s %s %s %d %.0fms",
                rid, method, path, status, elapsed,
            )
        elif status >= 400:
            logger.warning(
                "request_id=%s %s %s %d %.0fms",
                rid, method, path, status, elapsed,
            )
        else:
            logger.info(
                "request_id=%s %s %s %d %.0fms",
                rid, method, path, status, elapsed,
            )

        # 响应头返回 request_id（便于客户端关联）
        response.headers["X-Request-Id"] = rid
        return response


# ---- 公开 helper：暴露给前端获取 dev token ----
def get_dev_token_info() -> dict[str, Any]:
    """供调试端点 /debug/auth-info 返回当前认证配置。"""
    return {
        "auth_enabled": True,
        "token_source": "env" if _API_TOKEN else "dev_file",
        "rate_limit_per_min": _RATE_LIMIT_PER_MIN,
        "rate_limit_fail_per_min": _RATE_LIMIT_FAIL_PER_MIN,
        "rate_block_seconds": _RATE_BLOCK_SECONDS,
    }
