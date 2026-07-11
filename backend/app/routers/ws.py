# WebSocket 端点：连接回放快照 + 推送事件 + 接收 control.signal
from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.events import DomainEvent, bus, make_event
from app.orchestrator.runner import get_state, set_state
from app.orchestrator.state import apply_signal
from app.db_legacy import save_meeting

router = APIRouter()

# API 认证 token（与 middleware.py 共用同一环境变量）
# [CON-03/CON-08 修复] 改为共享 dev token（不再单独读取 env）
from app.middleware import _DEV_TOKEN, _check_rate_limit, _client_ip

# WS 推送配额：每连接每分钟最多 N 条事件，防止恶意/异常客户端撑爆带宽
WS_MAX_EVENTS_PER_MIN = int(os.environ.get("CONCLAVE_WS_RATE_LIMIT", "600"))
_ws_event_log: dict[str, list[float]] = {}  # client_ip -> [timestamp]
_ws_event_lock = asyncio.Lock()


def _check_ws_token(ws: WebSocket) -> bool:
    """WebSocket 连接的 token 认证

    HTTP 中间件无法拦截 WebSocket，需在 accept 前手动检查。
    支持 query 参数 ?token=<token>（浏览器 WebSocket API 无法设 header）。
    [CON-03 修复] 用 hmac.compare_digest 防时序攻击。
    """
    import hmac

    token = ws.query_params.get("token", "")
    if not token:
        return False
    return hmac.compare_digest(token.encode("utf-8"), _DEV_TOKEN.encode("utf-8"))


async def _check_ws_event_rate(client_ip: str) -> tuple[bool, str]:
    """WS 事件推送速率限制。

    Returns:
        (allowed, reason)
    """
    async with _ws_event_lock:
        now = time.monotonic()
        log = _ws_event_log.setdefault(client_ip, [])
        log[:] = [t for t in log if now - t < 60.0]
        # 清理空列表，防止字典只增不减
        if not log:
            _ws_event_log.pop(client_ip, None)
            log = _ws_event_log.setdefault(client_ip, [])
        if len(log) >= WS_MAX_EVENTS_PER_MIN:
            return False, f"WS 推送超过每分钟 {WS_MAX_EVENTS_PER_MIN} 条"
        log.append(now)
        return True, "ok"


async def _send_event(ws: WebSocket, event: DomainEvent) -> None:
    """向 WS 推送一条领域事件"""
    await ws.send_text(event.model_dump_json())


async def _send_json(ws: WebSocket, payload: dict) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_ws(ws: WebSocket, meeting_id: str, from_seq: int = 0) -> None:
    """会议 WebSocket

    - 连接时回放当前 MeetingState 快照 + 历史事件
    - 之后每有事件就推送
    - 接收 control.signal 转发给 Orchestrator
    - from_seq > 0 时跳过 snapshot，只推 seq > from_seq 的增量事件（断线重连）
    - token 通过 ?token=<token> query 参数传递
    - [CON-08 修复] 加心跳（ping/pong 每 30s）+ 推送速率限制 + 接入统一速率限制
    """
    # 认证：HTTP 中间件不拦截 WS，需在 accept 前手动检查
    if not _check_ws_token(ws):
        await ws.accept()
        await _send_json(ws, {
            "type": "error", "meeting_id": meeting_id,
            "message": "未授权：请提供有效的 API token",
        })
        await ws.close(code=4401, reason="Unauthorized")
        return

    # 速率限制（接入层与 HTTP 共享）
    # 提取客户端 IP：WebSocket 头取 X-Forwarded-For 或 fallback 到 ws.client
    fake_request_ip = ws.headers.get("x-forwarded-for")
    if fake_request_ip:
        client_ip = fake_request_ip.split(",")[0].strip()
    elif ws.client:
        client_ip = ws.client.host
    else:
        client_ip = "unknown"

    ok, reason = _check_rate_limit(client_ip, is_failed_attempt=False)
    if not ok:
        await ws.accept()
        await _send_json(ws, {
            "type": "error", "meeting_id": meeting_id,
            "message": f"速率限制：{reason}",
        })
        await ws.close(code=4429, reason="Too Many Requests")
        return

    await ws.accept()

    # ---- 心跳任务：每 30s 发 ping，断连则关闭 ----
    # [CON-08 修复] 之前没有心跳，僵尸连接会无限保留服务端资源
    HEARTBEAT_INTERVAL = 30.0

    async def _heartbeat_loop() -> None:
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                # 发送 application-level ping（与协议层 ping 不同，更兼容浏览器 WS API）
                await _send_json(ws, {
                    "type": "ping",
                    "meeting_id": meeting_id,
                    "ts": time.time(),
                })
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except Exception:
            pass

    heartbeat_task = asyncio.create_task(_heartbeat_loop())

    # 先订阅事件队列，再回放历史——避免回放与订阅之间的竞态丢事件
    # 竞态根因：如果先 replay 再 subscribe，replay 之后 publish 的事件
    # 不在 replay 列表中也不触发订阅者，永久丢失。
    # 修复：先 subscribe 到队列，replay 期间产生的新事件进入队列，
    # replay 完成后从队列补发，保证无遗漏。
    queue: asyncio.Queue[DomainEvent | None] = asyncio.Queue()

    async def _on_event(event: DomainEvent) -> None:
        await queue.put(event)

    unsubscribe = bus.subscribe(meeting_id, _on_event)

    # 记录订阅时刻的 last_seq，用于区分"回放事件"和"实时事件"
    subscribe_seq = bus.last_seq(meeting_id)
    snapshot_seq = subscribe_seq  # 全量回放时会覆盖为状态捕获点的 seq

    if from_seq > 0:
        # 增量回放：客户端已有状态，只推 seq > from_seq 的事件
        new_events = bus.replay(meeting_id, from_seq)
        for ev in new_events:
            await _send_event(ws, ev)
        # 记录回放完成时的 last_seq，用于队列补发截止点
        snapshot_seq = bus.last_seq(meeting_id)
        await _send_json(ws, {
            "type": "replay.done", "meeting_id": meeting_id,
            "events": len(new_events), "from_seq": from_seq,
            "last_seq": snapshot_seq,
        })
    else:
        # 完整回放：仅发送 snapshot（快照已包含完整状态：messages/conflicts/evidence/artifact 等），
        # 不再额外重放历史事件——历史事件中的 agent.spoke 等内容已反映在 snapshot 中，
        # 重复发送会导致前端出现重复消息。
        #
        # 正确顺序（避免竞态）：
        #   1) 已在上方 subscribe 到事件队列
        #   2) 取当前状态 → 3) 立即记录 snapshot_seq（状态对应的最后事件序号）
        #   4) 发送 snapshot → 5) 发送 replay.done
        #   6) 排空队列：仅补发 seq > snapshot_seq 的事件（快照之后产生的新事件）
        state = get_state(meeting_id)
        snapshot_seq = bus.last_seq(meeting_id)  # 状态捕获时刻的 last_seq
        snapshot: dict[str, Any] = state.snapshot() if state else {}
        await _send_json(ws, {"type": "snapshot", "meeting_id": meeting_id, "payload": snapshot})
        await _send_json(ws, {
            "type": "replay.done", "meeting_id": meeting_id,
            "events": 0, "from_seq": 0,
            "last_seq": snapshot_seq,
        })

    # 确定补发截止序号：全量回放用 snapshot_seq（状态捕获点），增量回放用 subscribe_seq
    drain_cutoff_seq = snapshot_seq if from_seq == 0 else subscribe_seq

    # 补发队列中已积累的、截止序号之后的新事件
    while not queue.empty():
        ev = await queue.get()
        if ev is not None and ev.seq > drain_cutoff_seq:
            await _send_event(ws, ev)

    try:
        # 同时监听队列推送与客户端消息
        while True:
            # 先非阻塞处理队列
            if not queue.empty():
                ev = await queue.get()
                if ev is None:
                    break
                # 推送速率限制
                ev_ok, _ = await _check_ws_event_rate(client_ip)
                if ev_ok:
                    await _send_event(ws, ev)
                continue
            # 用 wait_for 超时轮询客户端消息，避免永久阻塞队列
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.2)
                # 客户端 pong：仅记日志，不做处理
                if raw.strip() == "pong":
                    continue
                msg = json.loads(raw)
                # pong 字段
                if msg.get("type") == "pong":
                    continue
                if msg.get("type") == "control.signal" or "signal" in msg:
                    signal = msg.get("signal", "")
                    payload = msg.get("payload", {})
                    # 转发给 Orchestrator
                    state = get_state(meeting_id)
                    if state is not None:
                        state = apply_signal(state, signal, payload)
                        set_state(state)
                        # 持久化（与 HTTP control 端点保持一致）
                        try:
                            save_meeting(
                                meeting_id=meeting_id,
                                topic=state.topic,
                                status=state.status.value,
                                stage=state.stage.value,
                                created_at=state.created_at,
                                payload=state.snapshot(),
                            )
                        except Exception:
                            pass  # 持久化失败不影响信号处理
                        # 广播 control.signal 事件，让其他订阅者感知
                        try:
                            await bus.publish(
                                make_event(
                                    "control.signal",
                                    meeting_id,
                                    {"signal": signal, "status": state.status.value, "payload": payload},
                                )
                            )
                        except Exception:
                            pass
                        # 借调相关信号发布专门事件，让前端实时更新
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
                        # 回执
                        await _send_json(ws, {
                            "type": "control.ack", "meeting_id": meeting_id,
                            "signal": signal, "status": state.status.value,
                        })
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await _send_json(ws, {"type": "error", "meeting_id": meeting_id,
                                       "message": "无效的 JSON"})
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await _send_json(ws, {"type": "error", "meeting_id": meeting_id, "message": str(e)})
        except Exception:  # noqa: BLE001
            pass
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        unsubscribe()


@router.websocket("/ws/system")
async def system_ws(ws: WebSocket) -> None:
    """系统级 WebSocket：广播 system.* 事件（如会议列表变更、标签变更等）

    [CON-20 修复] 旧版 TaskBoard/DashboardView/MeetingSidebar/TokenPanel 用 5-10s
    setInterval 轮询 REST 端点，造成：
    1) 服务端反复查询 DB，浪费 IO
    2) 客户端反馈延迟（用户新建会议 5-10s 后才在侧栏出现）
    3) 轮询心跳被 Connection-Limit 计入，认证失败的 IP 误封禁

    改为：后端在 meetings 创建/删除/标签更新后 publish system.meetings.changed，
    前端 useSystemWebSocket 订阅后立即刷新。
    """
    # 认证
    if not _check_ws_token(ws):
        await ws.accept()
        await _send_json(ws, {"type": "error", "message": "未授权"})
        await ws.close(code=4401, reason="Unauthorized")
        return

    await ws.accept()

    queue: asyncio.Queue[DomainEvent | None] = asyncio.Queue()

    async def _on_event(event: DomainEvent) -> None:
        # 接受 system.* 和 captcha.* 事件（captcha 事件用于前端值守弹窗）
        if event.type.startswith("system.") or event.type.startswith("captcha."):
            await queue.put(event)

    # 订阅通配（bus 已实现 * 通配订阅）
    unsubscribe = bus.subscribe("*", _on_event)

    # 心跳
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
                await _send_event(ws, ev)
                continue
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.2)
                if raw.strip() == "pong":
                    continue
                msg = json.loads(raw) if raw else {}
                if msg.get("type") == "pong":
                    continue
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        unsubscribe()
