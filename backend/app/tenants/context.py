"""租户上下文（ContextVar）。

用于在整个请求生命周期中传递当前 tenant_id，DAO 层自动附加过滤条件。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any

_tenant_id_ctx: ContextVar[int | None] = ContextVar("tenant_id", default=None)
_system_tenant_ctx: ContextVar[bool] = ContextVar("system_tenant", default=False)


def set_tenant_id(tenant_id: int | None) -> Token:
    """设置当前租户 ID。"""
    return _tenant_id_ctx.set(tenant_id)


def get_tenant_id() -> int | None:
    """获取当前租户 ID。None 表示未设置（系统级操作或未登录）。"""
    return _tenant_id_ctx.get()


def reset_tenant_ctx(token: Token) -> None:
    """重置租户上下文。"""
    _tenant_id_ctx.reset(token)


def set_system_tenant(b: bool = True) -> Token:
    """设置系统租户标记（绕过租户过滤，用于跨租户管理操作）。"""
    return _system_tenant_ctx.set(b)


def is_system_tenant() -> bool:
    return _system_tenant_ctx.get()


@contextmanager
def create_system_tenant_ctx() -> Iterator[None]:
    """临时设置系统租户上下文（用于后台任务、初始化等跨租户操作）。"""
    t1 = _tenant_id_ctx.set(None)
    t2 = _system_tenant_ctx.set(True)
    try:
        yield
    finally:
        _system_tenant_ctx.reset(t2)
        _tenant_id_ctx.reset(t1)


def tenant_filter() -> dict[str, Any]:
    """生成 DAO 层的租户过滤条件。

    返回 dict 可直接展开到 SQL WHERE 条件参数中。
    系统租户（is_system_tenant=True）返回空条件（不过滤）。
    """
    if is_system_tenant():
        return {}
    tid = get_tenant_id()
    if tid is None:
        # 未设置 tenant_id：严格模式，返回不可能匹配的条件（防止数据泄露）
        return {"tenant_id": -1}
    return {"tenant_id": tid}
