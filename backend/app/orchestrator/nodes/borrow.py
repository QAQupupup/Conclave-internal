# Borrowed agent speaking logic: re-export from orchestrator/borrow_helpers.py
# 函数实现已迁移到 orchestrator/borrow_helpers.py，消除 stage_runners 对 nodes/ 的反向依赖。
# 本文件保留 re-export 以向后兼容 nodes/__init__.py 和其他潜在引用。
from __future__ import annotations

from app.orchestrator.borrow_helpers import (
    _let_borrowed_agents_speak,
    _moderator_assess_borrow,
    AUTO_BORROW_THRESHOLD,
    _ROLE_NAMES,
    _BORROWABLE_ROLES,
)

__all__ = [
    "_let_borrowed_agents_speak",
    "_moderator_assess_borrow",
    "AUTO_BORROW_THRESHOLD",
    "_ROLE_NAMES",
    "_BORROWABLE_ROLES",
]
