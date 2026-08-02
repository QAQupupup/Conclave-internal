"""RBAC 相关数据库 DDL 迁移（幂等）。

在 Casbin enforcer 初始化之前执行，确保 tenant_members、user_settings 表
和相关索引存在，并回填旧数据。
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.engine import async_session_factory

logger = logging.getLogger(__name__)


async def ensure_rbac_tables() -> None:
    """创建 RBAC 相关表、列、索引，并回填数据。幂等可重复调用。"""
    async with async_session_factory() as session:
        # ===== 0. tenants 表补充列（description, is_active） =====
        await session.execute(
            text(
                """
            DO $$
            BEGIN
                ALTER TABLE tenants ADD COLUMN IF NOT EXISTS description TEXT NOT NULL DEFAULT '';
                ALTER TABLE tenants ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
            END $$;
            """
            )
        )

        # ===== 1. users 表改造 =====
        # 1.1 将旧 role='admin' 迁移为 'system_admin'
        await session.execute(text("UPDATE users SET role = 'system_admin' WHERE role = 'admin'"))
        # 1.2 添加 email 和 updated_at 列（如不存在）
        await session.execute(
            text(
                """
            DO $$
            BEGIN
                ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255);
                ALTER TABLE users ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP NOT NULL DEFAULT NOW();
            END $$;
            """
            )
        )
        # 1.3 users 索引
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_users_is_active ON users(is_active)"))
        await session.execute(
            text(
                """
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = 'idx_users_email') THEN
                    CREATE UNIQUE INDEX idx_users_email ON users(email) WHERE email IS NOT NULL;
                END IF;
            END $$;
            """
            )
        )
        # 1.4 pg_trgm 扩展 + 模糊搜索索引
        await session.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await session.execute(
            text("CREATE INDEX IF NOT EXISTS idx_users_username_trgm ON users USING GIN (username gin_trgm_ops)")
        )
        await session.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_users_display_name_trgm ON users USING GIN (display_name gin_trgm_ops)"
            )
        )

        # ===== 2. tenant_members 表 =====
        await session.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS tenant_members (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role VARCHAR(20) NOT NULL DEFAULT 'member',
                is_banned BOOLEAN NOT NULL DEFAULT FALSE,
                invited_by INTEGER,
                joined_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE(tenant_id, user_id)
            )
            """
            )
        )
        # role CHECK 约束
        await session.execute(
            text(
                """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.check_constraints
                    WHERE constraint_name = 'ck_tm_role'
                ) THEN
                    ALTER TABLE tenant_members ADD CONSTRAINT ck_tm_role
                    CHECK (role IN ('owner','maintainer','member','reporter','banned'));
                END IF;
            END $$;
            """
            )
        )
        # 外键
        await session.execute(
            text(
                """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'fk_tm_tenant' AND table_name = 'tenant_members'
                ) THEN
                    ALTER TABLE tenant_members ADD CONSTRAINT fk_tm_tenant
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'fk_tm_user' AND table_name = 'tenant_members'
                ) THEN
                    ALTER TABLE tenant_members ADD CONSTRAINT fk_tm_user
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'fk_tm_invited_by' AND table_name = 'tenant_members'
                ) THEN
                    ALTER TABLE tenant_members ADD CONSTRAINT fk_tm_invited_by
                    FOREIGN KEY (invited_by) REFERENCES users(id) ON DELETE SET NULL;
                END IF;
            END $$;
            """
            )
        )
        # 索引
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_tm_tenant_id ON tenant_members(tenant_id)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_tm_user_id ON tenant_members(user_id)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_tm_role ON tenant_members(role)"))
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_tm_tenant_role ON tenant_members(tenant_id, role)"))
        await session.execute(
            text(
                """
            CREATE INDEX IF NOT EXISTS idx_tm_tenant_active_joined
            ON tenant_members(tenant_id, joined_at DESC) WHERE is_banned = FALSE
            """
            )
        )

        # ===== 3. api_keys 表：添加 user_id 列 =====
        await session.execute(
            text(
                """
            DO $$
            BEGIN
                ALTER TABLE api_keys ADD COLUMN IF NOT EXISTS user_id INTEGER;
            END $$;
            """
            )
        )
        # 外键
        await session.execute(
            text(
                """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'fk_api_keys_user' AND table_name = 'api_keys'
                ) THEN
                    ALTER TABLE api_keys ADD CONSTRAINT fk_api_keys_user
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                END IF;
            END $$;
            """
            )
        )
        # 索引
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_api_keys_user_id ON api_keys(user_id)"))
        await session.execute(
            text("CREATE INDEX IF NOT EXISTS idx_api_keys_tenant_user ON api_keys(tenant_id, user_id)")
        )
        # 替换唯一约束：先删除旧约束，再创建新约束
        await session.execute(
            text(
                """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'uq_api_key_tenant_provider_name' AND table_name = 'api_keys'
                ) THEN
                    ALTER TABLE api_keys DROP CONSTRAINT uq_api_key_tenant_provider_name;
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'uq_api_key_tenant_user_provider_name' AND table_name = 'api_keys'
                ) THEN
                    ALTER TABLE api_keys ADD CONSTRAINT uq_api_key_tenant_user_provider_name
                    UNIQUE (tenant_id, user_id, provider, name);
                END IF;
            END $$;
            """
            )
        )

        # ===== 4. user_settings 表 =====
        await session.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS user_settings (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL,
                key VARCHAR(100) NOT NULL,
                value TEXT NOT NULL,
                value_type VARCHAR(20) NOT NULL DEFAULT 'string',
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, key)
            )
            """
            )
        )
        await session.execute(
            text(
                """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.check_constraints
                    WHERE constraint_name = 'ck_user_settings_value_type'
                ) THEN
                    ALTER TABLE user_settings ADD CONSTRAINT ck_user_settings_value_type
                    CHECK (value_type IN ('string','int','float','bool','json'));
                END IF;
            END $$;
            """
            )
        )
        await session.execute(
            text(
                """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'fk_user_settings_user' AND table_name = 'user_settings'
                ) THEN
                    ALTER TABLE user_settings ADD CONSTRAINT fk_user_settings_user
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;
                END IF;
            END $$;
            """
            )
        )
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_user_settings_user_id ON user_settings(user_id)"))

        # ===== 4.5 system_settings 表（系统级 KV 配置） =====
        await session.execute(
            text(
                """
            CREATE TABLE IF NOT EXISTS system_settings (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT NOT NULL,
                value_type VARCHAR(20) NOT NULL DEFAULT 'string',
                updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
            )
        )
        await session.execute(
            text(
                """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.check_constraints
                    WHERE constraint_name = 'ck_system_settings_value_type'
                ) THEN
                    ALTER TABLE system_settings ADD CONSTRAINT ck_system_settings_value_type
                    CHECK (value_type IN ('string','int','float','bool','json'));
                END IF;
            END $$;
            """
            )
        )

        # ===== 5. updated_at 触发器 =====
        await session.execute(
            text(
                """
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
            )
        )
        for tbl in ("tenant_members", "user_settings", "system_settings"):
            await session.execute(
                text(
                    f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.triggers
                        WHERE trigger_name = 'trg_{tbl}_updated_at' AND event_object_table = '{tbl}'
                    ) THEN
                        CREATE TRIGGER trg_{tbl}_updated_at
                        BEFORE UPDATE ON {tbl}
                        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
                    END IF;
                END $$;
                """
                )
            )

        # ===== 6. 数据回填：从 users.tenant_id 迁移到 tenant_members =====
        # 先插入 owner 记录
        await session.execute(
            text(
                """
            INSERT INTO tenant_members (tenant_id, user_id, role, is_banned, joined_at, created_at, updated_at)
            SELECT t.id, t.owner_id, 'owner', FALSE, t.created_at, NOW(), NOW()
            FROM tenants t
            WHERE t.owner_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM tenant_members tm
                  WHERE tm.tenant_id = t.id AND tm.user_id = t.owner_id
              )
            """
            )
        )
        # 再插入其他成员（users.tenant_id 指向该租户但不是 owner 的）
        await session.execute(
            text(
                """
            INSERT INTO tenant_members (tenant_id, user_id, role, is_banned, joined_at, created_at, updated_at)
            SELECT u.tenant_id, u.id, 'member', FALSE, u.created_at, NOW(), NOW()
            FROM users u
            JOIN tenants t ON t.id = u.tenant_id
            WHERE u.tenant_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM tenant_members tm
                  WHERE tm.tenant_id = u.tenant_id AND tm.user_id = u.id
              )
            """
            )
        )
        # 修正 owner 角色（如果已有记录但角色不是 owner）
        await session.execute(
            text(
                """
            UPDATE tenant_members tm
            SET role = 'owner', updated_at = NOW()
            FROM tenants t
            WHERE tm.tenant_id = t.id
              AND tm.user_id = t.owner_id
              AND tm.role != 'owner'
            """
            )
        )

        # ===== 7. casbin_rule 索引（adapter 创建表后添加，此处用 IF NOT EXISTS 安全创建）=====
        # 注意：casbin_rule 表由 casbin_async_sqlalchemy_adapter 在 init_rbac 时创建，
        # 此处用 DO 块检查表存在性，避免首次启动时报错
        await session.execute(
            text(
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

        await session.commit()

    logger.info("RBAC 数据库表迁移完成")
