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
            owner_username TEXT NOT NULL DEFAULT 'system',
            status TEXT NOT NULL,
            stage TEXT NOT NULL,
            created_at TEXT NOT NULL,
            payload TEXT NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            tenant_id INTEGER
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
            tenant_id INTEGER,
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
            trace_id TEXT,
            tenant_id INTEGER
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
            tenant_id INTEGER,
            PRIMARY KEY (user_id, key)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS meeting_tags (
            id SERIAL PRIMARY KEY,
            meeting_id TEXT NOT NULL,
            tag TEXT NOT NULL,
            created_at TEXT NOT NULL,
            tenant_id INTEGER,
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
            tenant_id INTEGER,
            PRIMARY KEY (meeting_id, key),
            FOREIGN KEY (meeting_id) REFERENCES meetings(id) ON DELETE CASCADE
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_meeting_aux_meeting ON meeting_aux(meeting_id)",
        # 兼容旧数据库：为已有表添加缺失列
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS owner_username TEXT NOT NULL DEFAULT 'system'",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS schema_version INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE meetings ADD COLUMN IF NOT EXISTS tenant_id INTEGER",
        "ALTER TABLE messages ADD COLUMN IF NOT EXISTS tenant_id INTEGER",
        "ALTER TABLE events ADD COLUMN IF NOT EXISTS tenant_id INTEGER",
        "ALTER TABLE user_preferences ADD COLUMN IF NOT EXISTS tenant_id INTEGER",
        "ALTER TABLE meeting_tags ADD COLUMN IF NOT EXISTS tenant_id INTEGER",
        "ALTER TABLE meeting_aux ADD COLUMN IF NOT EXISTS tenant_id INTEGER",
        # 索引（必须在列存在之后创建）
        "CREATE INDEX IF NOT EXISTS idx_meetings_owner ON meetings(owner_username)",
        "CREATE INDEX IF NOT EXISTS idx_meetings_status ON meetings(status)",
        "CREATE INDEX IF NOT EXISTS idx_meetings_created ON meetings(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_meetings_tenant_id ON meetings(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_messages_tenant_id ON messages(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_events_tenant_id ON events(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_user_preferences_tenant_id ON user_preferences(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_meeting_tags_tenant_id ON meeting_tags(tenant_id)",
        "CREATE INDEX IF NOT EXISTS idx_meeting_aux_tenant_id ON meeting_aux(tenant_id)",
        # 联合索引：覆盖多租户会议列表查询（WHERE tenant_id=? AND status!=deleted ORDER BY created_at DESC）
        "CREATE INDEX IF NOT EXISTS idx_meetings_tenant_status_created ON meetings(tenant_id, status, created_at DESC)",
    ]
    async with async_session_factory() as session:
        for stmt in ddl_statements:
            await session.execute(text(stmt))
        await session.commit()
