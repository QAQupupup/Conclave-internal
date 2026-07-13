# 网络授权管理器：检测网络失败、创建申请、等待批复、自动通过/超时降级
from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any

from app.events import bus, make_event
from app.net_auth import (
    create_auth_request,
    get_auth_request,
)
from app.observability.log_bus import log_bus

# ---- 配置 ----

AUTO_APPROVE = os.environ.get("CONCLAVE_NET_AUTH_AUTO", "") == "1"
AUTH_TIMEOUT_SECONDS = int(os.environ.get("CONCLAVE_NET_AUTH_TIMEOUT", "120"))


# ---- 网络错误检测 ----

# 网络相关错误关键词
_NET_ERROR_PATTERNS = [
    "connection refused",
    "connection reset",
    "connection aborted",
    "temporary failure in name resolution",
    "getaddrinfo failed",
    "network is unreachable",
    "network access",
    "urlopen error",
    "NewConnectionError",
    "MaxRetryError",
    "socket.gaierror",
    "ssl: certificate_verify_failed",
    "pip install",
    "ModuleNotFoundError",
    "ImportError",
    "No module named",
]


def detect_network_failure(stderr: str, exit_code: int, code: str) -> str | None:
    """检测沙箱执行失败是否因网络限制导致

    返回失败原因字符串（如触发网络申请），或 None（非网络问题）。
    """
    stderr_lower = stderr.lower()

    # 1. 明确的网络连接错误
    for pattern in _NET_ERROR_PATTERNS[:11]:  # 前 11 个是网络错误
        if pattern.lower() in stderr_lower:
            return f"网络连接失败: {pattern}"

    # 2. pip install 失败（L1 无网络时 pip 会报错）
    if "pip install" in code.lower() and (
        "connection" in stderr_lower or "network" in stderr_lower or "could not find" in stderr_lower
    ):
        return "pip install 需要网络访问"

    # 3. ModuleNotFoundError（L1 无网络时无法 pip install 安装缺失模块）
    if exit_code == 1 and "modulenotfounderror" in stderr_lower:
        missing_module = _extract_missing_module(stderr)
        if missing_module and missing_module not in ("pandas", "numpy", "matplotlib", "sklearn", "scipy", "seaborn"):
            # 非数据科学镜像预装的模块，可能需要 pip install
            return f"缺少模块 {missing_module}，需要 pip install（需要网络）"

    return None


def _extract_missing_module(stderr: str) -> str | None:
    """从 ModuleNotFoundError 错误中提取模块名"""
    for line in stderr.split("\n"):
        if "ModuleNotFoundError" in line and "No module named" in line:
            # No module named 'requests'
            idx = line.find("'")
            if idx >= 0:
                end = line.find("'", idx + 1)
                if end > idx:
                    return line[idx + 1 : end]
    return None


def determine_needed_level(code: str, failure_reason: str) -> str:
    """根据代码内容和失败原因判断需要的网络级别"""
    code_lower = code.lower()

    # HTTP 请求 → L3
    if any(p in code_lower for p in ["import requests", "from requests", "import urllib", "from urllib",
                                      "import httpx", "from httpx", "import aiohttp", "from aiohttp",
                                      "http://", "https://", "urlopen"]):
        return "L3"

    # pip install → L2
    if "pip install" in code_lower:
        return "L2"

    # ModuleNotFoundError 但代码没有网络请求 → L2（需要安装依赖）
    if "modulenotfounderror" in failure_reason.lower() or "pip install" in failure_reason.lower():
        return "L2"

    return "L2"  # 默认升级到 L2


async def request_network_access(
    meeting_id: str,
    stage: str,
    code: str,
    detected_level: str,
    failure_reason: str,
    stderr: str,
) -> dict[str, Any]:
    """发起网络授权申请

    流程：
    1. 创建申请单写入 DB
    2. 发布 net_auth.requested 事件（前端可展示给用户）
    3. 如果 AUTO_APPROVE=True，自动通过
    4. 否则等待用户批复，超时后降级

    返回：
        {"approved": True/False, "level": "L2"/"L3", "request_id": "..."}
    """
    needed_level = determine_needed_level(code, failure_reason)
    request_id = f"auth-{uuid.uuid4().hex[:12]}"
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=AUTH_TIMEOUT_SECONDS)

    # 写入 DB
    create_auth_request(
        request_id=request_id,
        meeting_id=meeting_id,
        stage=stage,
        code_snippet=code,
        requested_level=needed_level,
        detected_level=detected_level,
        failure_reason=failure_reason,
        stderr_output=stderr,
        expires_at=expires_at,
    )

    log_bus.info(
        f"网络授权申请已创建: {request_id} level={needed_level} meeting={meeting_id}",
        logger="net_auth",
    )

    # 发布事件通知前端
    await bus.publish(make_event(
        "net_auth.requested",
        meeting_id,
        {
            "request_id": request_id,
            "requested_level": needed_level,
            "detected_level": detected_level,
            "failure_reason": failure_reason,
            "expires_at": expires_at.isoformat(),
            "auto_approve": AUTO_APPROVE,
        },
    ))

    # 自动通过
    if AUTO_APPROVE:
        from app.net_auth import review_auth_request
        review_auth_request(request_id, "approved", "自动通过（AUTO_APPROVE=1）")
        log_bus.info(f"网络授权自动通过: {request_id}", logger="net_auth")
        await bus.publish(make_event(
            "net_auth.reviewed",
            meeting_id,
            {"request_id": request_id, "action": "approved", "comment": "自动通过"},
        ))
        return {"approved": True, "level": needed_level, "request_id": request_id}

    # 等待用户批复（带超时）
    result = await _wait_for_review(request_id, meeting_id, AUTH_TIMEOUT_SECONDS)

    if result is None:
        # 超时，降级处理
        log_bus.warning(
            f"网络授权申请超时未批复，降级处理: {request_id}",
            logger="net_auth",
        )
        await bus.publish(make_event(
            "net_auth.timeout",
            meeting_id,
            {"request_id": request_id, "action": "expired"},
        ))
        return {"approved": False, "level": None, "request_id": request_id, "timeout": True}

    if result["status"] == "approved":
        return {"approved": True, "level": needed_level, "request_id": request_id}

    # denied
    return {"approved": False, "level": None, "request_id": request_id, "denied": True}


async def _wait_for_review(request_id: str, meeting_id: str, timeout: int) -> dict[str, Any] | None:
    """等待用户批复，超时返回 None"""
    # 订阅事件
    future: asyncio.Future = asyncio.get_event_loop().create_future()

    async def handler(event):
        if event.type == "net_auth.reviewed" and event.payload.get("request_id") == request_id:
            if not future.done():
                future.set_result(event.payload)

    unsub = bus.subscribe(meeting_id, handler)

    try:
        # 同时轮询 DB（防止事件丢失）
        result = await asyncio.wait_for(
            _poll_for_review(request_id, timeout),
            timeout=timeout,
        )
        return result
    except asyncio.TimeoutError:
        return None
    finally:
        unsub()


async def _poll_for_review(request_id: str, timeout: int) -> dict[str, Any]:
    """轮询 DB 等待批复结果"""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        req = get_auth_request(request_id)
        if req and req["status"] != "pending":
            return req
        await asyncio.sleep(2)
    raise asyncio.TimeoutError("轮询超时")
