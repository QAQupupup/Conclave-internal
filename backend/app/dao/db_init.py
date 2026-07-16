"""数据库初始化与连接池管理。

包含建表 DDL 执行与连接池关闭逻辑。
原迁移自 app/db_legacy.py，逻辑未做任何修改。
"""
from __future__ import annotations

from sqlalchemy import text

from app.db.engine import async_session_factory, get_engine


async def close_db_pool() -> None:
    """关闭连接池，主要用于测试清理。"""
    engine = await get_engine()
    await engine.dispose()


async def init_db() -> None:
    """初始化所有 legacy 表。"""
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS meetings (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            meeting_id TEXT NOT NULL,
            agent_role TEXT NOT NULL,
            stage TEXT NOT NULL,
            content TEXT NOT NULL,
            claim_refs TEXT NOT NULL,
            evidence_refs TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (meeting_id) REFERENCES meetings(id)
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_messages_meeting ON messages(meeting_id)",
        """
        CREATE TABLE IF NOT EXISTS events (
            seq SERIAL PRIMARY KEY,
            meeting_id TEXT NOT NULL,
            type TEXT NOT NULL,
            payload TEXT NOT NULL,
            ts TEXT NOT NULL,
            trace_id TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_events_meeting ON events(meeting_id)",
        "CREATE INDEX IF NOT EXISTS idx_events_meeting_seq ON events(meeting_id, seq)",
        """
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id TEXT NOT NULL DEFAULT 'default',
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (user_id, key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS meeting_tags (
            id SERIAL PRIMARY KEY,
            meeting_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(meeting_id, tag),
            FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_meeting_tags_meeting ON meeting_tags(meeting_id)",
        "CREATE INDEX IF NOT EXISTS idx_meeting_tags_tag ON meeting_tags(tag)",
        """
        CREATE TABLE IF NOT EXISTS agent_roles (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            perspective TEXT NOT NULL DEFAULT '',
            expertise_domains TEXT NOT NULL DEFAULT '[]',
            risk_appetite TEXT NOT NULL DEFAULT 'balanced',
            default_stance TEXT NOT NULL DEFAULT '',
            evidence_preference TEXT NOT NULL DEFAULT 'balanced',
            model_override TEXT NOT NULL DEFAULT '',
            background_brief TEXT NOT NULL DEFAULT '',
            prompt_template TEXT NOT NULL DEFAULT '',
            is_builtin INTEGER NOT NULL DEFAULT 0,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_agent_roles_active ON agent_roles(is_active)",
        """
        CREATE TABLE IF NOT EXISTS meeting_aux (
            meeting_id TEXT NOT NULL,
            key TEXT NOT NULL,
            value_json TEXT NOT NULL DEFAULT '{}',
            updated_at TEXT NOT NULL,
            PRIMARY KEY (meeting_id, key),
            FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_meeting_aux_meeting ON meeting_aux(meeting_id)",
    ]
    async with async_session_factory() as session:
        for stmt in ddl_statements:
            await session.execute(text(stmt))
        await session.commit()
