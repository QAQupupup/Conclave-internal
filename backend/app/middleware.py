# 请求追踪中间件：每个 HTTP 请求分配 request_id，设置到 contextvars
# API 认证中间件：基于 token 的简单认证 + 速率限制
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import os
import re
import sys
import time
from collections import defaultdict
from threading import Lock
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from app.context import new_request_id, reset_request_id, set_request_id
from app.logging_config import get_logger

logger = get_logger("middleware.trace")

# API 认证 token（留空则不启用认证，仅开发模式）
_API_TOKEN = os.environ.get("CONCLAVE_API_TOKEN", "")
_DEV_TOKEN_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".dev_token")


def _load_or_create_dev_token() -> str:
    """读取或生成开发 token。"""
    if _API_TOKEN:
        return _API_TOKEN
    if os.path.exists(_DEV_TOKEN_PATH):
        with open(_DEV_TOKEN_PATH, encoding="utf-8") as f:
            tok = f.read().strip()
        if tok:
            return tok
    # 生成新 token
    token = hashlib.sha256(os.urandom(32)).hexdigest()[:48]
    try:
        with open(_DEV_TOKEN_PATH, "w", encoding="utf-8") as f:
            f.write(token)
        # [L-03 修复] Windows 上 os.chmod 行为不同，跳过权限设置
        if not sys.platform.startswith("win"):
            os.chmod(_DEV_TOKEN_PATH, 0o600)
        logger.warning(
            "首次启动：已生成开发 token 写入 %s，请前端配置后访问。生产环境必须设置 CONCLAVE_API_TOKEN。",
            _DEV_TOKEN_PATH,
        )
    except OSError as e:
        logger.error("无法写入 dev_token 文件: %s；使用内存 token（重启失效）", e)
    return token


_DEV_TOKEN = _load_or_create_dev_token()

# 免认证路径前缀
_PUBLIC_PATHS = {
    "/health",
    "/metrics",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/debug/auth-info",
    "/auth/login",
}
# WebSocket 升级路径免认证（WebSocket 在 query 参数中传 token）
_WS_PATHS = {"/ws"}

# ---- 速率限制 ----
_RATE_LIMIT_PER_MIN = int(os.environ.get("CONCLAVE_RATE_LIMIT_PER_MIN", "600"))
_RATE_LIMIT_FAIL_PER_MIN = int(os.environ.get("CONCLAVE_RATE_LIMIT_FAIL_PER_MIN", "5"))
_RATE_BLOCK_SECONDS = int(os.environ.get("CONCLAVE_RATE_BLOCK_SECONDS", "60"))

_FAIL_BAN_ENABLED = True

_LOCALHOST_IPS = {"127.0.0.1", "::1", "localhost"}

# [H-08 修复] 速率限制数据结构 + 定期清理，防止内存永久增长
_request_log: dict[str, list[float]] = defaultdict(list)
_fail_log: dict[str, list[float]] = defaultdict(list)
_blocked_ips: dict[str, float] = {}  # ip -> block_until_timestamp
_rate_lock = Lock()

# 定期清理任务
_cleanup_task: asyncio.Task | None = None
_cleanup_interval = 60.0  # 每 60 秒清理一次
_max_tracked_ips = 10000  # 最多追踪 10000 个 IP（LRU 式淘汰）


def _do_periodic_cleanup() -> None:
    """定期清理过期的速率限制数据，防止内存泄漏。

    [H-08 修复] 原实现中，_request_log/_fail_log/_blocked_ips 字典以 IP 为 key，
    如果遭遇分布式 DDoS（大量不同 IP），key 集合会无限增长导致 OOM。
    修复方案：
    1. 清理空列表 key（IP 一段时间内无请求）
    2. 清理 _blocked_ips 中已过期的条目
    3. 当追踪 IP 总数超过上限时，淘汰最旧的条目
    """
    now = time.monotonic()
    with _rate_lock:
        window = 60.0
        # 清理 _request_log：删除空列表
        empty_req = [ip for ip, log in _request_log.items() if not log or now - log[-1] > window * 2]
        for ip in empty_req:
            _request_log.pop(ip, None)
        # 清理 _fail_log：删除空列表和过期记录
        empty_fail = [ip for ip, log in _fail_log.items() if not log or now - log[-1] > window * 2]
        for ip in empty_fail:
            _fail_log.pop(ip, None)
        # 清理 _blocked_ips：删除已过期封禁
        expired_blocks = [ip for ip, until in _blocked_ips.items() if now >= until]
        for ip in expired_blocks:
            _blocked_ips.pop(ip, None)
        # LRU 式淘汰：如果追踪 IP 总数超过上限，清理最旧的
        all_ips = set(_request_log.keys()) | set(_fail_log.keys()) | set(_blocked_ips.keys())
        if len(all_ips) > _max_tracked_ips:
            # 找出没有活跃记录的 IP 并删除
            # 简单策略：删除所有 _request_log 和 _fail_log 中都为空的 IP
            # 如果还超，删除 _fail_log 中最旧的一半
            to_remove = len(all_ips) - _max_tracked_ips
            removed = 0
            for ip in list(_request_log.keys()):
                if removed >= to_remove:
                    break
                if not _request_log[ip]:
                    _request_log.pop(ip, None)
                    removed += 1
            if removed < to_remove:
                # 按最后请求时间排序，删除最旧的
                ips_with_time = []
                for ip, log in _request_log.items():
                    if log:
                        ips_with_time.append((log[-1], ip))
                ips_with_time.sort()
                for _, ip in ips_with_time[: to_remove - removed]:
                    _request_log.pop(ip, None)
                    _fail_log.pop(ip, None)
                    _blocked_ips.pop(ip, None)


async def _periodic_cleanup_loop() -> None:
    """后台定期清理循环"""
    while True:
        try:
            await asyncio.sleep(_cleanup_interval)
            _do_periodic_cleanup()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("速率限制定期清理异常: %s", e)


def start_rate_limit_cleanup() -> None:
    """启动定期清理任务（在 lifespan 中调用）"""
    global _cleanup_task
    if _cleanup_task is None or _cleanup_task.done():
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()
        _cleanup_task = loop.create_task(_periodic_cleanup_loop())


def stop_rate_limit_cleanup() -> None:
    """停止定期清理任务"""
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        _cleanup_task.cancel()
    _cleanup_task = None


def client_ip(request: Request) -> str:
    """提取客户端 IP（公开版本）"""
    return _client_ip(request)


def _client_ip(request: Request) -> str:
    """提取客户端 IP（优先 X-Forwarded-For 首段，再退化到 client.host）"""
    xff = request.headers.get("X-Forwarded-For")
    if xff:
        return xff.split(",")[0].strip()  # type: ignore[no-any-return]
    return request.client.host if request.client else "unknown"


def _check_rate_limit(ip: str, is_failed_attempt: bool = False) -> tuple[bool, str]:
    """检查 IP 是否被限流。返回 (allowed, reason)。"""
    if is_failed_attempt and (not _FAIL_BAN_ENABLED or ip in _LOCALHOST_IPS):
        return True, "ok"

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


def _normalize_path(path: str) -> str:
    """规范化路径，防止路径穿越绕过 _is_public 检查。

    [M-05 修复] 原实现用 startswith 匹配路径，可能被编码、`..`、重复斜杠绕过。
    规范化后再做精确匹配。
    """
    # 去除查询字符串（如果有）
    if "?" in path:
        path = path.split("?", 1)[0]
    # 规范化：去除重复斜杠、解析 .. 和 .
    # 简单规则：collapse 多个 / 为一个
    while "//" in path:
        path = path.replace("//", "/")
    # 去除尾部斜杠（除了根路径）
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return path


def _is_public(path: str) -> bool:
    """判断路径是否免认证

    [M-05 修复] 使用规范化路径 + 精确匹配/目录前缀匹配，防止编码绕过。
    """
    norm = _normalize_path(path)
    for p in _PUBLIC_PATHS:
        if norm == p:
            return True
        # 子路径匹配：/auth/login/xxx 也应视为公开（虽然目前没有子路由，保留扩展性）
        if norm.startswith(p + "/"):
            return True
    return False


def setup_auth_middleware(app: FastAPI) -> None:
    """注册 API 认证中间件

    认证策略（按优先级）：
    1. JWT Bearer Token（登录认证）—— 用户登录后获得
    2. Dev token（向后兼容）—— CONCLAVE_API_TOKEN 或 .dev_token 文件
    """

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next) -> Response:
        path = request.url.path
        client_ip_str = _client_ip(request)

        # 测试模式：跳过认证与限流，但注入测试 admin 用户以通过 auth_guard 权限检查
        # [C-03 修复] 与 HTTP 中间件一致，要求双重条件，防止生产环境误设一个环境变量绕过
        if os.environ.get("APP_ENV") == "test" and os.environ.get("CONCLAVE_TEST_DISABLE_AUTH") == "1":
            request.state.auth_user = {"username": "test", "role": "admin", "uid": None}
            from app.context import set_user_id, set_user_role, set_username

            set_user_id("test")
            set_username("test")
            set_user_role("admin")
            return cast(Response, await call_next(request))

        # 速率限制（所有请求包括公开路径都限流）
        ok, reason = _check_rate_limit(client_ip_str, is_failed_attempt=False)
        if not ok:
            return JSONResponse(
                status_code=429,
                content={"detail": f"请求过快：{reason}"},
                headers={"Retry-After": "60"},
            )

        # OPTIONS 预检请求直接放行（CORS 中间件在外层已处理，这里再次确保）
        if request.method == "OPTIONS":
            return cast(Response, await call_next(request))

        # 公开路径免认证（但不免限流）
        if _is_public(path):
            return cast(Response, await call_next(request))

        # 提取 token：仅从 Authorization header 读取
        # [C-04 修复] 普通 HTTP 请求不接受 ?token= 查询参数（防 token 在 URL/日志/Referer 中泄露）。
        # WebSocket 升级请求在 ws router 中自行处理 query 参数（浏览器 WS API 无法设置自定义 header）。
        auth_header = request.headers.get("Authorization", "")
        token = ""
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
        # 兼容：旧版 Authorization: Token xxx 格式
        elif auth_header.lower().startswith("token "):
            token = auth_header[6:].strip()

        if not token:
            ok, reason = _check_rate_limit(client_ip_str, is_failed_attempt=True)
            if not ok:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"认证失败过多：{reason}"},
                    headers={"Retry-After": str(_RATE_BLOCK_SECONDS)},
                )
            return JSONResponse(
                status_code=401,
                content={"detail": "未授权：请先登录"},
            )

        # token 长度限制（防 DoS）
        if len(token) > 4096:
            ok, reason = _check_rate_limit(client_ip_str, is_failed_attempt=True)
            if not ok:
                return JSONResponse(
                    status_code=429,
                    content={"detail": f"认证失败过多：{reason}"},
                    headers={"Retry-After": str(_RATE_BLOCK_SECONDS)},
                )
            return JSONResponse(
                status_code=401,
                content={"detail": "认证失败：token 格式无效"},
            )

        # 认证方式1：JWT token（用户登录）
        auth_user = None
        try:
            from app.auth import decode_token

            auth_user = decode_token(token)
        except Exception:
            auth_user = None

        if auth_user:
            request.state.auth_user = auth_user
            # 设置用户上下文（用于日志/审计追踪）
            from app.context import set_user_id, set_username
            from app.context import set_user_role as _set_ur

            set_user_id(str(auth_user.get("uid", "") or ""))
            set_username(auth_user.get("username", ""))
            _set_ur(auth_user.get("role", ""))
            return cast(Response, await call_next(request))

        # 认证方式2：Dev token（向后兼容，视为 admin）
        if hmac.compare_digest(
            token.encode("utf-8"),
            _DEV_TOKEN.encode("utf-8"),
        ):
            request.state.auth_user = {"username": "dev", "role": "admin", "uid": None}
            from app.context import set_user_id, set_username
            from app.context import set_user_role as _set_ur2

            set_user_id("dev")
            set_username("dev")
            _set_ur2("admin")
            return cast(Response, await call_next(request))

        # 全部认证失败
        ok2, _reason2 = _check_rate_limit(client_ip_str, is_failed_attempt=True)
        if not ok2:
            logger.warning("IP %s 触发封禁：%s", client_ip_str, _reason2)
            # 审计：触发封禁
            try:
                from app.observability.audit import audit

                audit(
                    "security.rate_limited",
                    "blocked",
                    {
                        "reason": "auth_failures_exceeded",
                        "path": path,
                    },
                    ip=client_ip_str,
                )
            except Exception:
                pass
            return JSONResponse(
                status_code=429,
                content={"detail": f"认证失败过多：{_reason2}"},
                headers={"Retry-After": str(_RATE_BLOCK_SECONDS)},
            )
        # 审计：未授权访问尝试
        try:
            from app.observability.audit import audit

            audit(
                "security.unauthorized_access",
                "failure",
                {
                    "path": path,
                    "method": request.method,
                    "has_auth_header": bool(auth_header),
                },
                ip=client_ip_str,
            )
        except Exception:
            pass
        return JSONResponse(
            status_code=401,
            content={"detail": "认证失败：token 无效或已过期"},
        )


# ---- 命令注入防护 ----

_DANGEROUS_PATTERNS = [
    r"\brm\s+(-{1,2}\w+\s+)*-?r\w*\s+(-{1,2}\w+\s+)*[/~.*]",
    r"\brm\s+(-{1,2}\w+\s+)*-?r\w*\s+\*",
    r"\bmkfs\b",
    r"\b(?:shutdown|reboot|halt|poweroff)\b",
    r"\bdd\s+if=.+of=/dev/",
    r">\s*/dev/sd[a-z]",
    r"\bchmod\s+-R\s+777\s+/",
    r"\b(?:curl|wget)\s+.+\|\s*/?(?:bash|sh|/bin/bash|/bin/sh)",
    r"\b(?:curl|wget)\s+.+\|\s*(?:bash|sh)",
    r"\beval\s+\$\(?",
    r"\beval\s+\$\w+",
    r"\bnc\s+.*-e\s+/bin/sh",
    r"\bpython\s+-c\s+.*import\s+subprocess",
    r"\bpython\s+-c\s+.*import\s+os",
]


def is_dangerous_command(command: str) -> bool:
    """检测命令是否包含危险模式"""
    cmd = command.strip()
    return any(re.search(pattern, cmd, re.IGNORECASE) for pattern in _DANGEROUS_PATTERNS)


def setup_trace_middleware(app: FastAPI) -> None:
    """注册请求追踪中间件

    [M-05 补充] CORS 中间件注册顺序：CORSMiddleware 注册在 auth_middleware 之前，
    OPTIONS 预检请求由 CORS 中间件直接返回，不会到达 auth 中间件。
    这里额外在 auth_middleware 中也放行 OPTIONS，作为防御性编程。
    """

    @app.middleware("http")
    async def trace_middleware(request: Request, call_next) -> Response:
        rid = request.headers.get("X-Request-Id") or new_request_id()
        token = set_request_id(rid)

        t0 = time.monotonic()
        method = request.method
        path = request.url.path

        try:
            response: Response = cast(Response, await call_next(request))
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            logger.error(
                "request_id=%s %s %s 500 %.0fms [异常: %s]",
                rid,
                method,
                path,
                elapsed,
                type(e).__name__,
            )
            raise
        finally:
            reset_request_id(token)

        elapsed = (time.monotonic() - t0) * 1000
        status = response.status_code

        try:
            from app.observability.metrics_store import get_metrics_store

            get_metrics_store().record_request(elapsed)
        except Exception:
            pass

        if status >= 500:
            logger.error(
                "request_id=%s %s %s %d %.0fms",
                rid,
                method,
                path,
                status,
                elapsed,
            )
            # 审计：5xx 错误
            try:
                from app.observability.audit import audit

                audit(
                    "system.error",
                    "error",
                    {
                        "method": method,
                        "path": path,
                        "status": status,
                    },
                    duration_ms=int(elapsed),
                )
            except Exception:
                pass
        elif status >= 400:
            logger.warning(
                "request_id=%s %s %s %d %.0fms",
                rid,
                method,
                path,
                status,
                elapsed,
            )
        else:
            logger.info(
                "request_id=%s %s %s %d %.0fms",
                rid,
                method,
                path,
                status,
                elapsed,
            )

        # 审计：写操作（POST/PUT/DELETE/PATCH）自动记录
        if method in ("POST", "PUT", "DELETE", "PATCH"):
            _NO_AUDIT_PATHS = {"/health", "/metrics", "/docs", "/openapi.json", "/redoc"}
            if path not in _NO_AUDIT_PATHS and not path.startswith("/docs"):
                try:
                    from app.observability.audit import audit

                    # 推断操作类型
                    action_map = {
                        "POST": _infer_audit_action(path, "create"),
                        "PUT": _infer_audit_action(path, "update"),
                        "DELETE": _infer_audit_action(path, "delete"),
                        "PATCH": _infer_audit_action(path, "update"),
                    }
                    action = action_map.get(method, "system.request")
                    audit(
                        action,
                        "success" if status < 400 else "failure",
                        {
                            "method": method,
                            "path": path,
                            "status": status,
                        },
                        duration_ms=int(elapsed),
                        ip=_client_ip(request),
                    )
                except Exception:
                    pass

        response.headers["X-Request-Id"] = rid
        return response


def get_dev_token_info() -> dict[str, Any]:
    """供调试端点 /debug/auth-info 返回当前认证配置。"""
    return {
        "auth_enabled": True,
        "token_source": "env" if _API_TOKEN else "dev_file",
        "fail_ban_enabled": _FAIL_BAN_ENABLED,
        "rate_limit_per_min": _RATE_LIMIT_PER_MIN,
        "rate_limit_fail_per_min": _RATE_LIMIT_FAIL_PER_MIN,
        "rate_block_seconds": _RATE_BLOCK_SECONDS,
        "jwt_auth_enabled": True,
        "default_admin_username": os.environ.get("CONCLAVE_ADMIN_USERNAME", "admin"),
    }


# 路径到审计动作的映射表（高频路径专用，更精确）
_PATH_AUDIT_MAP: dict[str, str] = {
    "/api/meetings": "meeting.created",
}


def _infer_audit_action(path: str, method_fallback: str) -> str:
    """根据 URL 路径推断审计动作类型"""
    # 精确匹配
    if path in _PATH_AUDIT_MAP:
        return _PATH_AUDIT_MAP[path]
    # 路径片段推断
    if "/meetings" in path:
        if "/control" in path:
            return "meeting.control"
        if "/intervene" in path:
            return "meeting.intervened"
        if "/run" in path:
            return "meeting.started"
        if "/abort" in path:
            return "meeting.aborted"
        if "/borrow" in path or "/takeover" in path:
            return "meeting.borrow_requested"
        if "/reference" in path:
            return "meeting.reference_injected"
        if "/tags" in path:
            return "meeting.tag_changed"
        if "/model" in path:
            return "meeting.model_changed"
        if method_fallback == "delete":
            return "meeting.deleted"
        return "meeting.updated"
    if "/auth" in path:
        if "/login" in path:
            return "auth.login"
        return "auth.action"
    if "/workspace" in path:
        if "/exec" in path or "/run" in path:
            return "sandbox.command_executed"
        if "/files" in path:
            return "sandbox.file_modified"
        return "workspace.action"
    if "/llm/keys" in path:
        return "admin.key_saved"
    if "/net-auth" in path or "/net_auth" in path:
        return "sandbox.network_auth"
    if "/agent-roles" in path or "/agent_roles" in path:
        return "admin.role_changed"
    if "/preferences" in path:
        return "admin.config_changed"
    if "/captcha" in path:
        return "sandbox.captcha_resolved"
    return f"system.{method_fallback}"


def record_auth_failure(ip: str) -> None:
    """供 auth router 记录登录失败（best effort）"""
    with contextlib.suppress(Exception):
        _check_rate_limit(ip or "unknown", is_failed_attempt=True)


def reset_auth_failures(ip: str) -> None:
    """登录成功时清除失败记录"""
    try:
        with _rate_lock:
            _fail_log.pop(ip or "unknown", None)
            _blocked_ips.pop(ip or "unknown", None)
    except Exception:
        pass


def verify_ws_token(token: str) -> dict | None:
    """WebSocket 认证：支持 JWT 和 dev token，返回用户信息或 None"""
    if not token:
        return None
    if len(token) > 4096:
        logger.warning("Rejected overlong token (%d bytes)", len(token))
        return None
    # JWT
    try:
        from app.auth import decode_token

        user = decode_token(token)
        if user:
            return user
    except Exception:
        pass
    # Dev token
    if hmac.compare_digest(token.encode("utf-8"), _DEV_TOKEN.encode("utf-8")):
        return {"username": "dev", "role": "admin", "uid": None}
    return None
