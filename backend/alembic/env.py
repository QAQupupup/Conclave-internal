"""Alembic 迁移环境配置。

支持异步 PostgreSQL + SQLAlchemy 2.0。
"""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings
from app.db.base import Base
# 导入所有 ORM 模型以确保 Base.metadata 包含全部表
from app.db.models import (  # noqa: F401
    MeetingModel, MessageModel, EventModel, MeetingTagModel,
    AgentRoleModel, UserPreferenceModel, NetAuthRequestModel,
    MeetingAuxModel, ApiKeyModel, DocumentModel, CostRecordModel,
    RawMemoryModel, FeatureMemoryModel, ProfileMemoryModel,
)

# Alembic Config 对象
config = context.config

# 日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 目标元数据
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """离线模式：生成 SQL 而非直接执行。"""
    url = settings.database_url
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """在连接上下文中执行迁移。"""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """在线模式：异步引擎执行迁移。"""
    connectable = create_async_engine(
        settings.database_url,
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())