"""安全的后台任务创建：自动记录未捕获异常，防止 asyncio.Task 静默失败。

[M-10 修复] 多处使用 asyncio.create_task() 创建后台任务但未添加 done callback
处理异常，异常被 asyncio 吞掉仅打印 "Task exception was never retrieved"，
导致后台任务静默失败（如 key 加载失败、定价抓取失败等不易发现）。
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine

logger = logging.getLogger(__name__)


def create_supervised_task(
    coro: Coroutine[Any, Any, Any],
    *,
    name: str = "",
    logger: logging.Logger | None = None,
) -> asyncio.Task:
    """创建受监督的后台任务，未捕获异常会被记录到日志。

    Args:
        coro: 要执行的协程
        name: 任务名称（用于日志标识）
        logger: 自定义日志记录器，默认使用 utils.tasks
    """
    log = logger or logging.getLogger("utils.tasks")
    task_name = name or getattr(coro, "__qualname__", coro.__class__.__name__)
    task = asyncio.create_task(coro, name=task_name)

    def _on_done(t: asyncio.Task) -> None:
        try:
            exc = t.exception()
        except asyncio.CancelledError:
            return
        except Exception:  # noqa: BLE001
            return
        if exc is not None:
            log.error(
                "后台任务 %s 未捕获异常: %s: %s",
                task_name, type(exc).__name__, exc,
                exc_info=exc,
            )

    task.add_done_callback(_on_done)
    return task
