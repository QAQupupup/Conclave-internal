# WebSocket 端点：连接回放快照 + 推送事件 + 接收 control.signal
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.events import DomainEvent, bus
from app.orchestrator.runner import get_state
from app.orchestrator.state import apply_signal

router = APIRouter()

# API 认证 token（与 middleware.py 共用同一环境变量）
_API_TOKEN = os.environ.get("CONCLAVE_API_TOKEN", "")


async def _send_event(ws: WebSocket, event: DomainEvent) -> None:
    """向 WS 推送一条领域事件"""
    await ws.send_text(event.model_dump_json())


def _check_ws_token(ws: WebSocket) -> bool:
    """WebSocket 连接的 token 认证

    HTTP 中间件无法拦截 WebSocket，需在 accept 前手动检查。
    支持 query 参数 ?token=<token>（浏览器 WebSocket API 无法设 header）。
    token 未配置时返回 True（开发模式不认证）。
    """
    if not _API_TOKEN:
        return True
    token = ws.query_params.get("token", "")
    return token == _API_TOKEN


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_ws(ws: WebSocket, meeting_id: str, from_seq: int = 0) -> None:
    """会议 WebSocket

    - 连接时回放当前 MeetingState 快照 + 历史事件
    - 之后每有事件就推送
    - 接收 control.signal 转发给 Orchestrator
    - from_seq > 0 时跳过 snapshot，只推 seq > from_seq 的增量事件（断线重连）
    - token 通过 ?token=<token> query 参数传递（CONCLAVE_API_TOKEN 未设置时不认证）
    """
    # 认证：HTTP 中间件不拦截 WS，需在 accept 前手动检查
    if not _check_ws_token(ws):
        await ws.accept()
        await ws.send_text(json.dumps(
            {"type": "error", "meeting_id": meeting_id,
             "message": "未授权：请提供有效的 API token"},
            ensure_ascii=False,
        ))
        await ws.close(code=4401, reason="Unauthorized")
        return

    await ws.accept()

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

    if from_seq > 0:
        # 增量回放：客户端已有状态，只推 seq > from_seq 的事件
        new_events = bus.replay(meeting_id, from_seq)
        for ev in new_events:
            await _send_event(ws, ev)
        await ws.send_text(json.dumps(
            {"type": "replay.done", "meeting_id": meeting_id,
             "events": len(new_events), "from_seq": from_seq,
             "last_seq": subscribe_seq},
            ensure_ascii=False,
        ))
    else:
        # 完整回放：snapshot + 全部历史事件
        # 1. 回放快照
        state = get_state(meeting_id)
        snapshot: dict[str, Any] = state.snapshot() if state else {}
        await ws.send_text(json.dumps({"type": "snapshot", "meeting_id": meeting_id, "payload": snapshot},
                                      ensure_ascii=False, default=str))
        # 2. 回放历史事件（seq <= subscribe_seq 的）
        for ev in bus.history(meeting_id):
            await _send_event(ws, ev)
        # 回放结束标记，便于客户端判断初始化完成
        await ws.send_text(json.dumps(
            {"type": "replay.done", "meeting_id": meeting_id,
             "events": len(bus.history(meeting_id)), "from_seq": 0,
             "last_seq": subscribe_seq},
            ensure_ascii=False,
        ))

    # 补发订阅后到回放完成之间产生的事件（seq > subscribe_seq）
    # 这些事件在 replay 时还没产生，但已进入队列
    while not queue.empty():
        ev = await queue.get()
        if ev is not None and ev.seq > subscribe_seq:
            await _send_event(ws, ev)

    try:
        # 同时监听队列推送与客户端消息
        while True:
            # 先非阻塞处理队列
            if not queue.empty():
                ev = await queue.get()
                if ev is None:
                    break
                await _send_event(ws, ev)
                continue
            # 用 wait_for 超时轮询客户端消息，避免永久阻塞队列
            try:
                raw = await asyncio.wait_for(ws.receive_text(), timeout=0.2)
                msg = json.loads(raw)
                if msg.get("type") == "control.signal" or "signal" in msg:
                    signal = msg.get("signal", "")
                    payload = msg.get("payload", {})
                    # 转发给 Orchestrator
                    state = get_state(meeting_id)
                    if state is not None:
                        apply_signal(state, signal, payload)
                        # 回执
                        await ws.send_text(json.dumps(
                            {"type": "control.ack", "meeting_id": meeting_id,
                             "signal": signal, "status": state.status.value},
                            ensure_ascii=False,
                        ))
            except asyncio.TimeoutError:
                continue
            except WebSocketDisconnect:
                break
            except json.JSONDecodeError:
                await ws.send_text(json.dumps({"type": "error", "meeting_id": meeting_id,
                                                "message": "无效的 JSON"}))
    except WebSocketDisconnect:
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await ws.send_text(json.dumps({"type": "error", "meeting_id": meeting_id,
                                           "message": str(e)}))
        except Exception:  # noqa: BLE001
            pass
    finally:
        unsubscribe()
