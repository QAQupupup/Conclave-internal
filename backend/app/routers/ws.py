# WebSocket 端点：连接回放快照 + 推送事件 + 接收 control.signal
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.events import DomainEvent, bus, make_event
from app.middleware import verify_ws_token, _check_rate_limit
from app.orchestrator.runner import get_state, set_state
from conclave_core.state import apply_signal
from app.db_legacy import save_meeting

logger = logging.getLogger("ws")

router = APIRouter()

# WS 推送配额：每连接每分钟最多 N 条事件，防止恶意/异常客户端撑爆带宽
WS_MAX_EVENTS_PER_MIN = int(os.environ.get("CONCLAVE_WS_RATE_LIMIT", "600"))
# [M-04 修复] WS 入站消息配额：每连接每分钟最多 N 条客户端消息，防 DoS
WS_MAX_INBOUND_PER_MIN = int(os.environ.get("CONCLAVE_WS_INBOUND_RATE", "120"))
# WS 队列最大长度：防止慢客户端导致内存无限堆积
WS_QUEUE_MAXSIZE = int(os.environ.get("CONCLAVE_WS_QUEUE_MAX", "500"))
_ws_event_log: dict[str, list[float]] = {}
_ws_event_lock = asyncio.Lock()
# 批量发送配置：同一帧内到达的事件最多等待 BATCH_MAX_WAIT 秒后合并发送
WS_BATCH_MAX_WAIT = float(os.environ.get("CONCLAVE_WS_BATCH_WAIT", "0.05"))  # 50ms


def _ws_client_ip(ws: WebSocket) -> str:
    """提取 WebSocket 客户端 IP"""
    xff = ws.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    if ws.client:
        return ws.client.host
    return "unknown"


def _check_ws_token(ws: WebSocket) -> dict | None:
    """WebSocket 连接的 token 认证

    HTTP 中间件无法拦截 WebSocket，需在 accept 前手动检查。
    支持 query 参数 ?token=<token>（浏览器 WebSocket API 无法设 header）。
    返回用户信息 dict 或 None。

    [C-03 修复] 测试模式要求双重条件（APP_ENV=test + CONCLAVE_TEST_DISABLE_AUTH=1），
    与 HTTP 中间件保持一致，防止生产环境误设一个环境变量就绕过 WS 认证。
    """
    if os.environ.get("APP_ENV") == "test" and os.environ.get("CONCLAVE_TEST_DISABLE_AUTH") == "1":
        return {"username": "test", "role": "admin", "uid": None}

    token = ws.query_params.get("token", "")
    # [C-04 修复] 同时支持 Authorization header（虽然浏览器WS API无法设置，但非浏览器客户端可以）
    if not token:
        auth_header = ws.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
    return verify_ws_token(token)


def _check_meeting_access(user: dict, meeting_id: str) -> tuple[bool, str]:
    """检查用户是否有权访问指定会议。

    [H-02 修复] 原实现没有任何权限校验，任何已认证用户都能连接任意会议的 WS，
    导致越权读取其他用户的会议内容、发送控制信号。
    权限规则：
    - admin 角色可访问所有会议
    - 会议不存在时，允许任何已认证用户访问（会议创建场景）
    - 会议存在时，普通用户必须是 owner 或参与者

    Returns:
        (allowed, reason)
    """
    if not user:
        return False, "未认证"
    role = user.get("role", "")
    if role == "admin":
        return True, "admin"
    username = user.get("username", "")
    state = get_state(meeting_id)
    if state is None:
        # 会议不存在，允许创建者连接
        return True, "create"
    # 检查 owner
    owner = getattr(state, "owner", None) or (state.snapshot().get("owner") if hasattr(state, "snapshot") else None)
    if owner and owner == username:
        return True, "owner"
    # 检查参与者列表
    participants = []
    if hasattr(state, "participants"):
        participants = list(state.participants)
    elif hasattr(state, "snapshot"):
        snap = state.snapshot() or {}
        participants = snap.get("participants", []) or []
    if username in participants:
        return True, "participant"
    return False, "无权访问该会议"


async def _check_ws_event_rate(client_key: str) -> tuple[bool, str]:
    """WS 出站事件推送速率限制（按连接key）。"""
    async with _ws_event_lock:
        now = time.monotonic()
        log = _ws_event_log.setdefault(client_key, [])
        log[:] = [t for t in log if now - t < 60.0]
        if not log:
            _ws_event_log.pop(client_key, None)
            log = _ws_event_log.setdefault(client_key, [])
        if len(log) >= WS_MAX_EVENTS_PER_MIN:
            return False, f"WS 推送超过每分钟 {WS_MAX_EVENTS_PER_MIN} 条"
        log.append(now)
        return True, "ok"


class WsInboundRateLimiter:
    """[M-04 修复] WS 入站消息速率限制器（每连接独立窗口）"""

    def __init__(self, max_per_min: int = WS_MAX_INBOUND_PER_MIN):
        self.max = max_per_min
        self._timestamps: list[float] = []

    def check(self) -> bool:
        now = time.monotonic()
        self._timestamps[:] = [t for t in self._timestamps if now - t < 60.0]
        if len(self._timestamps) >= self.max:
            return False
        self._timestamps.append(now)
        return True


async def _send_event(ws: WebSocket, event: DomainEvent) -> None:
    """向 WS 推送一条领域事件"""
    await ws.send_text(event.model_dump_json())


async def _send_json(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))


async def _ws_close_error(ws: WebSocket, code: int, reason: str, payload: dict) -> None:
    """辅助函数：accept -> 发送错误 -> 关闭"""
    await ws.accept()
    await _send_json(ws, payload)
    await ws.close(code=code, reason=reason)


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_ws(ws: WebSocket, meeting_id: str, from_seq: int = 0) -> None:
    """会议 WebSocket

    - 连接时回放当前 MeetingState 快照 + 历史事件
    - 之后每有事件就推送
    - 接收 control.signal 转发给 Orchestrator
    - from_seq > 0 时跳过 snapshot，只推 seq > from_seq 的增量事件（断线重连）
    - token 通过 ?token=<token> query 参数或 Authorization: Bearer header 传递
    - [H-02 修复] 加会议访问权限校验
    - [M-04 修复] 加入站消息速率限制
    """
    # 认证：HTTP 中间件不拦截 WS，需在 accept 前手动检查
    user = _check_ws_token(ws)
    if not user:
        await _ws_close_error(ws, 4401, "Unauthorized", {
            "type": "error", "meeting_id": meeting_id, "message": "未授权：请先登录",
        })
        return

    # [H-02 修复] 权限校验
    allowed, reason = _check_meeting_access(user, meeting_id)
    # 接入层速率限制
    client_ip = _ws_client_ip(ws)

    if not allowed:
        await _ws_close_error(ws, 4403, "Forbidden", {
            "type": "error", "meeting_id": meeting_id, "message": reason,
        })
        logger.warning("WS 权限拒绝: user=%s meeting=%s reason=%s", user.get("username"), meeting_id, reason)
        # 审计：WS 权限拒绝
        try:
            from app.observability.audit import audit
            audit("security.unauthorized_access", "denied", {
                "channel": "ws", "meeting_id": meeting_id, "reason": reason,
            }, ip=client_ip, username=user.get("username"), meeting_id=meeting_id)
        except Exception:
            pass
        return

    ok, rate_reason = _check_rate_limit(client_ip, is_failed_attempt=False)
    if not ok:
        await _ws_close_error(ws, 4429, "Too Many Requests", {
            "type": "error", "meeting_id": meeting_id, "message": f"速率限制：{rate_reason}",
        })
        return

    await ws.accept()

    # 审计：WS 连接建立
    try:
        from app.observability.audit import audit
        from app.context import set_user_id, set_username, set_user_role, set_meeting_id
        set_user_id(str(user.get("uid") or ""))
        set_username(user.get("username", ""))
        set_user_role(user.get("role", ""))
        set_meeting_id(meeting_id)
        audit("system.ws_connected", "success", {
            "from_seq": from_seq,
            "access_reason": reason,
        }, ip=client_ip, username=user.get("username"), meeting_id=meeting_id)
    except Exception:
        pass

    # 连接 key（IP + meeting_id 用于出站限流）
    conn_key = f"{client_ip}:{meeting_id}"
    # [M-04 修复] 入站速率限制器
    inbound_limiter = WsInboundRateLimiter()

    # ---- 心跳任务：每 30s 发 ping，断连则关闭 ----
    HEARTBEAT_INTERVAL = 30.0

    async def _heartbeat_loop() -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                await _send_json(ws, {"type": "ping", "meeting_id": meeting_id, "ts": time.time()})
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception:
            pass

    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    # 先订阅事件队列，再回放历史（避免竞态丢事件）
    queue: asyncio.Queue[DomainEvent | None] = asyncio.Queue(maxsize=WS_QUEUE_MAXSIZE)
    _dropped_count = 0

    async def _on_event(event: DomainEvent) -> None:
        nonlocal _dropped_count
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()
                queue.put_nowait(event)
                _dropped_count += 1
            except Exception:
                pass

    unsubscribe = bus.subscribe(meeting_id, _on_event)

    subscribe_seq = await bus.last_seq(meeting_id)
    snapshot_seq = subscribe_seq

    if from_seq > 0:
        new_events = await bus.replay(meeting_id, from_seq)
        for ev in new_events:
            await _send_event(ws, ev)
        snapshot_seq = await bus.last_seq(meeting_id)
        await _send_json(ws, {
            "type": "replay.done", "meeting_id": meeting_id,
            "events": len(new_events), "from_seq": from_seq,
            "last_seq": snapshot_seq,
        })
    else:
        state = get_state(meeting_id)
        snapshot_seq = await bus.last_seq(meeting_id)
        snapshot: dict[str, Any] = state.snapshot() if state else {}
        await _send_json(ws, {"type": "snapshot", "meeting_id": meeting_id, "payload": snapshot})
        await _send_json(ws, {
            "type": "replay.done", "meeting_id": meeting_id,
            "events": 0, "from_seq": 0, "last_seq": snapshot_seq,
        })

    drain_cutoff_seq = snapshot_seq if from_seq == 0 else subscribe_seq
    while not queue.empty():
        ev = await queue.get()
        if ev is not None and ev.seq > drain_cutoff_seq:
            await _send_event(ws, ev)

    try:
        while True:
            if not queue.empty():
                ev = await queue.get()
                if ev is None:
                    break
                ev_ok, _ = await _check_ws_event_rate(conn_key)
                if ev_ok:
                    await _send_event(ws, ev)
                continue
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.2)
                if raw.strip() == "pong":
                    continue
                # [M-04 修复] 入站消息速率限制
                if not inbound_limiter.check():
                    await _send_json(ws, {
                        "type": "error", "meeting_id": meeting_id,
                        "message": f"发送消息过快，限制为每分钟 {WS_MAX_INBOUND_PER_MIN} 条",
                    })
                    continue
                msg = json.loads(raw)
                if msg.get("type") == "pong":
                    continue
                # [H-02 补充] 只有 admin 或会议 owner 才能发送控制信号
                if msg.get("type") == "control.signal" or "signal" in msg:
                    signal = msg.get("signal", "")
                    payload = msg.get("payload", {})
                    # 二次校验：非 admin 用户发送控制信号时必须是 owner
                    current_state = get_state(meeting_id)
                    if current_state is not None and user.get("role") != "admin":
                        owner = getattr(current_state, "owner", None) or (
                            current_state.snapshot().get("owner") if hasattr(current_state, "snapshot") else None
                        )
                        if owner and owner != user.get("username"):
                            await _send_json(ws, {
                                "type": "error", "meeting_id": meeting_id,
                                "message": "仅会议创建者或管理员可发送控制信号",
                            })
                            continue
                    state = get_state(meeting_id)
                    if state is not None:
                        state = apply_signal(state, signal, payload)
                        set_state(state)
                        # 审计：控制信号
                        try:
                            from app.observability.audit import audit
                            sig_action = {
                                "approve_borrow": "meeting.borrow_approved",
                                "reject_borrow": "meeting.borrow_rejected",
                                "pause": "meeting.paused",
                                "resume": "meeting.resumed",
                                "abort": "meeting.aborted",
                                "intervene": "meeting.intervened",
                            }.get(signal, "meeting.control")
                            audit(sig_action, "success", {
                                "signal": signal,
                                "payload_keys": list(payload.keys()) if isinstance(payload, dict) else [],
                            }, username=user.get("username"), meeting_id=meeting_id, ip=client_ip)
                        except Exception:
                            pass
                        try:
                            await save_meeting(
                                meeting_id=meeting_id,
                                topic=state.topic,
                                status=state.status.value,
                                stage=state.stage.value,
                                created_at=state.created_at,
                                payload=state.snapshot(),
                            )
                        except Exception:
                            pass
                        try:
                            await bus.publish(make_event(
                                "control.signal", meeting_id,
                                {"signal": signal, "status": state.status.value, "payload": payload},
                            ))
                        except Exception:
                            pass
                        try:
                            if signal == "approve_borrow":
                                await bus.publish(make_event("borrow.approved_by_user", meeting_id, {
                                    "meeting_id": meeting_id,
                                    "request_id": payload.get("request_id", ""),
                                    "pending_borrow_request": None,
                                    "borrow_frozen": state.borrow_frozen,
                                }))
                            elif signal == "reject_borrow":
                                await bus.publish(make_event("borrow.rejected_by_user", meeting_id, {
                                    "meeting_id": meeting_id,
                                    "request_id": payload.get("request_id", ""),
                                    "pending_borrow_request": None,
                                    "reason": payload.get("reason", ""),
                                    "borrow_frozen": state.borrow_frozen,
                                }))
                            elif signal == "freeze_borrow":
                                await bus.publish(make_event("borrow.frozen", meeting_id, {
                                    "meeting_id": meeting_id,
                                    "pending_borrow_request": None,
                                    "borrow_frozen": True,
                                }))
                        except Exception:
                            pass
                        await _send_json(ws, {
                            "type": "control.ack", "meeting_id": meeting_id,
                            "signal": signal, "status": state.status.value,
                        })
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                if not inbound_limiter.check():
                    continue
                await _send_json(ws, {"type": "error", "meeting_id": meeting_id, "message": "无效的 JSON"})
    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await _send_json(ws, {"type": "error", "meeting_id": meeting_id, "message": str(e)})
        except Exception:
            pass
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        unsubscribe()
        # 清理出站限流记录
        async with _ws_event_lock:
            _ws_event_log.pop(conn_key, None)
        # 审计：WS 断开
        try:
            from app.observability.audit import audit
            audit("system.ws_disconnected", "success", {
                "dropped_events": _dropped_count,
            }, ip=client_ip, username=user.get("username"), meeting_id=meeting_id)
        except Exception:
            pass


@router.websocket("/ws/system")
async def system_ws(ws: WebSocket) -> None:
    """系统级 WebSocket：广播 system.* 事件

    [H-02 修复] 系统 WS 仅允许 admin 角色连接。普通用户连接 /ws/system 可以监听
    全局事件（会议列表变更、服务部署状态、网络认证状态等），属于越权信息泄露。
    """
    user = _check_ws_token(ws)
    if not user:
        await _ws_close_error(ws, 4401, "Unauthorized", {"type": "error", "message": "未授权"})
        return

    # [H-02 修复] /ws/system 仅管理员可连接（涉及系统级事件广播）
    if user.get("role") != "admin":
        await _ws_close_error(ws, 4403, "Forbidden", {
            "type": "error", "message": "仅管理员可连接系统 WS",
        })
        logger.warning("WS /ws/system 权限拒绝: user=%s role=%s", user.get("username"), user.get("role"))
        return

    client_ip = _ws_client_ip(ws)
    ok, reason = _check_rate_limit(client_ip, is_failed_attempt=False)
    if not ok:
        await _ws_close_error(ws, 4429, "Too Many Requests", {
            "type": "error", "message": f"速率限制：{reason}",
        })
        return

    await ws.accept()

    conn_key = f"{client_ip}:system"
    inbound_limiter = WsInboundRateLimiter(max_per_min=60)  # 系统 WS 入站更严格

    queue: asyncio.Queue[DomainEvent | None] = asyncio.Queue(maxsize=WS_QUEUE_MAXSIZE)
    _sys_dropped = 0

    async def _on_event(event: DomainEvent) -> None:
        nonlocal _sys_dropped
        if event.type.startswith("system.") or event.type.startswith("captcha.") \
                or event.type.startswith("net_auth.") or event.type.startswith("service."):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                    queue.put_nowait(event)
                    _sys_dropped += 1
                except Exception:
                    pass

    unsubscribe = bus.subscribe("*", _on_event)

    async def _heartbeat_loop() -> None:
        try:
            while True:
                await asyncio.sleep(30.0)
                await _send_json(ws, {"type": "ping", "ts": time.time()})
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception:
            pass

    heartbeat_task = asyncio.create_task(_heartbeat_loop())
    await _send_json(ws, {"type": "system.ready", "ts": time.time()})

    try:
        while True:
            if not queue.empty():
                ev = await queue.get()
                if ev is None:
                    break
                ev_ok, _ = await _check_ws_event_rate(conn_key)
                if ev_ok:
                    await _send_event(ws, ev)
                continue
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.2)
                if raw.strip() == "pong":
                    continue
                if not inbound_limiter.check():
                    await _send_json(ws, {
                        "type": "error",
                        "message": f"发送消息过快，限制为每分钟 60 条",
                    })
                    continue
                msg = json.loads(raw) if raw else {}
                if msg.get("type") == "pong":
                    continue
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                continue
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        unsubscribe()
        async with _ws_event_lock:
            _ws_event_log.pop(conn_key, None)
