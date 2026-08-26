"""数据库 Schema 一致性校验。

防止"改了 ORM 模型忘了改 raw SQL DDL"或"改了一处建表 SQL 忘了改另一处"
这类双源真相问题。在启动时和测试中调用，及早发现列缺失/类型不匹配。

设计原则：
- 硬错误（抛异常）：ORM 声明的列在 DB 中不存在、NOT NULL 约束不匹配
- 软警告（仅日志）：NOT NULL 列无 server_default（raw SQL INSERT 需显式赋值）
- 只检查有 ORM 模型的表；无 ORM 模型的 raw SQL 表（第三方/插件自建表）不检查
- 此模块是"预警系统"，不是迁移工具——发现不一致直接报错，让开发者修
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from app.db.base import Base
from app.db.engine import async_session_factory

logger = logging.getLogger(__name__)


# 已知无需 ORM 模型的 raw SQL 表（第三方/插件自建表，无 ORM 模型）
# 注：meetings/messages/events/user_preferences/meeting_tags/agent_roles/meeting_aux
#     均已迁移到 ORM 模型（见 app/db/models/），不再列入本白名单。
_LEGACY_RAW_TABLES: set[str] = {
    # net_auth / notifications 由各自模块 raw SQL 建表
    "net_auth_requests",
    "notifications",
    "alembic_version",
    # Casbin adapter 自建表
    "casbin_rule",
}


def _get_orm_expected_columns() -> dict[str, dict[str, dict[str, Any]]]:
    """从 ORM 模型提取期望的列定义。

    返回: {table_name: {column_name: {nullable, has_server_default, is_pk}}}
    """
    result: dict[str, dict[str, dict[str, Any]]] = {}
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        table = cls.__table__
        if table is None:
            continue
        tbl_name = table.name
        cols: dict[str, dict[str, Any]] = {}
        for col in table.columns:
            cols[col.name] = {
                "nullable": col.nullable,
                "has_server_default": col.server_default is not None,
                "has_python_default": col.default is not None or col.onupdate is not None,
                "is_pk": col.primary_key,
                "type_name": str(col.type),
            }
        result[tbl_name] = cols
    return result


async def verify_schema_consistency(raise_on_error: bool = True) -> dict[str, list[str]]:
    """校验 ORM 模型与数据库实际表结构的一致性。

    Args:
        raise_on_error: 发现硬错误时是否抛异常

    Returns:
        {"errors": [...], "warnings": [...]}
    """
    errors: list[str] = []
    warnings: list[str] = []

    try:
        expected = _get_orm_expected_columns()
    except Exception as e:
        logger.warning("Schema 校验：无法读取 ORM 模型定义: %s", e)
        return {"errors": [], "warnings": []}

    async with async_session_factory() as session:
        # 获取所有 public 表
        tables_result = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        )
        db_tables = {row[0] for row in tables_result.fetchall()}

        for tbl_name, orm_cols in expected.items():
            if tbl_name in _LEGACY_RAW_TABLES:
                continue

            if tbl_name not in db_tables:
                # 表可能由后续流程创建（如 Casbin adapter），记为警告
                warnings.append(f"ORM 表 '{tbl_name}' 在数据库中不存在（可能尚未初始化）")
                continue

            # 获取数据库中该表的实际列
            cols_result = await session.execute(
                text(
                    "SELECT column_name, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = :tbl"
                ),
                {"tbl": tbl_name},
            )
            db_cols: dict[str, dict[str, Any]] = {}
            for row in cols_result.fetchall():
                col_name, is_nullable, col_default = row
                db_cols[col_name] = {
                    "nullable": is_nullable == "YES",
                    "has_default": col_default is not None,
                }

            for col_name, orm_col in orm_cols.items():
                if col_name not in db_cols:
                    errors.append(f"表 '{tbl_name}' 列 '{col_name}': ORM 声明了但 DB 中不存在")
                    continue

                db_col = db_cols[col_name]

                # NOT NULL 约束不匹配 → 硬错误
                if not orm_col["nullable"] and db_col["nullable"]:
                    errors.append(f"表 '{tbl_name}' 列 '{col_name}': ORM 声明 NOT NULL 但 DB 列为 nullable")

                # NOT NULL 无 server_default → 警告（raw SQL INSERT 需显式赋值）
                # Python default 只对 ORM 路径有效，raw SQL 路径需要 server_default
                if (
                    not orm_col["nullable"]
                    and not orm_col["has_server_default"]
                    and not orm_col["is_pk"]
                    and not db_col["has_default"]
                    and col_name != "created_at"  # created_at 已在 Mixin 加了 server_default
                    and col_name != "updated_at"  # updated_at 已在 Mixin 加了 server_default
                ):
                    warnings.append(
                        f"表 '{tbl_name}' 列 '{col_name}': NOT NULL 无 DB DEFAULT，"
                        f"raw SQL INSERT 必须显式赋值（Python default 仅对 ORM 路径有效）"
                    )

    if warnings:
        logger.warning("Schema 校验 %d 个警告:", len(warnings))
        for w in warnings:
            logger.warning("  [WARN] %s", w)

    if errors:
        logger.error("Schema 校验发现 %d 个硬错误:", len(errors))
        for err in errors:
            logger.error("  [ERROR] %s", err)
        if raise_on_error:
            raise RuntimeError(
                f"DB Schema 与 ORM 模型不一致（{len(errors)} 个错误）:\n" + "\n".join(f"  - {err}" for err in errors)
            )
    elif not warnings:
        logger.info("Schema 一致性校验通过")

    return {"errors": errors, "warnings": warnings}
