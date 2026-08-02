"""Casbin RBAC enforcer 初始化与单例管理。

使用 casbin-async-sqlalchemy-adapter 将策略存储在 PostgreSQL 中，
支持 RBAC with Domains（系统域 + 每个 Team 一个域）。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import casbin
from casbin_async_sqlalchemy_adapter import Adapter as CasbinAdapter

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

# 全局 enforcer 单例（在 lifespan 中初始化）
_enforcer: casbin.AsyncEnforcer | None = None

# Domain 命名
SYSTEM_DOMAIN = "system"


def get_enforcer() -> casbin.AsyncEnforcer:
    """获取全局 Casbin enforcer 单例。必须在 init_rbac() 之后调用。"""
    if _enforcer is None:
        raise RuntimeError("Casbin RBAC 尚未初始化，请在应用启动时调用 init_rbac()")
    return _enforcer


def team_domain(tenant_id: int) -> str:
    """生成 Team 域名字符串。"""
    return f"t{tenant_id}"


async def init_rbac(engine: AsyncEngine | None = None, model_path: str | Path | None = None) -> casbin.AsyncEnforcer:
    """初始化 Casbin AsyncEnforcer。

    Args:
        engine: SQLAlchemy async engine（项目已有的）。若为 None，从 app.db.engine 获取。
        model_path: rbac_model.conf 路径，默认使用同目录下的 model.conf

    Returns:
        初始化后的 AsyncEnforcer（同时存入全局 _enforcer）
    """
    global _enforcer

    if engine is None:
        from app.db.engine import get_engine as _get_engine

        engine = await _get_engine()

    if model_path is None:
        model_path = Path(__file__).parent / "model.conf"

    # 创建 adapter（使用项目已有的 async engine）
    adapter = CasbinAdapter(engine)

    # 确保 casbin_rule 表存在
    await adapter.create_table()

    # 创建 casbin_rule 索引（幂等）
    from sqlalchemy import text as _text

    from app.db.engine import async_session_factory as _asf

    try:
        async with _asf() as _s:
            await _s.execute(
                _text(
                    """
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'casbin_rule') THEN
                        CREATE INDEX IF NOT EXISTS idx_casbin_ptype ON casbin_rule(ptype);
                        CREATE INDEX IF NOT EXISTS idx_casbin_policy_lookup ON casbin_rule(ptype, v0, v1, v2);
                        CREATE INDEX IF NOT EXISTS idx_casbin_group_lookup ON casbin_rule(ptype, v0, v1);
                    END IF;
                END $$;
                """
                )
            )
            await _s.commit()
    except Exception as _e:
        logger.warning("casbin_rule 索引创建失败（非致命）: %s", _e)

    # 创建 AsyncEnforcer
    e = casbin.AsyncEnforcer(str(model_path), adapter)
    await e.load_policy()

    _enforcer = e
    logger.info("Casbin RBAC enforcer 初始化完成")
    return e


async def reload_policies() -> None:
    """重新加载策略（在策略变更后调用以刷新内存缓存）。"""
    e = get_enforcer()
    await e.load_policy()
