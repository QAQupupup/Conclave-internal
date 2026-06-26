# WebSocket 端点：连接回放快照 + 推送事件 + 接收 control.signal
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.events import DomainEvent, bus
from app.orchestrator.runner import get_state
from app.orchestrator.state import apply_signal

router = APIRouter()


async def _send_event(ws: WebSocket, event: DomainEvent) -> None:
    """向 WS 推送一条领域事件"""
    await ws.send_text(event.model_dump_json())


@router.websocket("/ws/meetings/{meeting_id}")
async def meeting_ws(ws: WebSocket, meeting_id: str) -> None:
    """会议 WebSocket

    - 连接时回放当前 MeetingState 快照 + 历史事件
    - 之后每有事件就推送
    - 接收 control.signal 转发给 Orchestrator
    """
    await ws.accept()

    # 1. 回放快照
    state = get_state(meeting_id)
    snapshot: dict[str, Any] = state.snapshot() if state else {}
    await ws.send_text(json.dumps({"type": "snapshot", "meeting_id": meeting_id, "payload": snapshot},
                                  ensure_ascii=False, default=str))

    # 2. 回放历史事件
    for ev in bus.history(meeting_id):
        await _send_event(ws, ev)
    # 回放结束标记，便于客户端判断初始化完成
    await ws.send_text(json.dumps(
        {"type": "replay.done", "meeting_id": meeting_id,
         "events": len(bus.history(meeting_id))},
        ensure_ascii=False,
    ))

    # 3. 订阅后续事件，推送到 WS
    queue: asyncio.Queue[DomainEvent | None] = asyncio.Queue()

    async def _on_event(event: DomainEvent) -> None:
        await queue.put(event)

    unsubscribe = bus.subscribe(meeting_id, _on_event)

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
