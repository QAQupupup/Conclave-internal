"""租户服务：建表、CRUD、迁移。"""
from __future__ import annotations

import logging
import re

from sqlalchemy import text

from app.db.engine import async_session_factory
from app.tenants.models import TenantCreate, TenantInfo

logger = logging.getLogger(__name__)

TENANTS_TABLE = "tenants"
DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "默认组织"


def _slugify(name: str) -> str:
    """生成 URL 安全的 slug。"""
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fa5\-_]", "-", name.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "org"


async def ensure_tenants_table() -> None:
    """创建 tenants 表并确保 users 表有 tenant_id 列和外键约束。

    可在 users 表已存在或不存在时安全调用。
    """
    async with async_session_factory() as session:
        # 1. 创建 tenants 表
        await session.execute(text(
            f"""
            CREATE TABLE IF NOT EXISTS {TENANTS_TABLE} (
                id SERIAL PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                slug VARCHAR(64) UNIQUE NOT NULL,
                plan VARCHAR(32) NOT NULL DEFAULT 'free',
                owner_id INTEGER,
                settings JSONB NOT NULL DEFAULT '{{}}',
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
        ))
        await session.execute(
            text(f"CREATE INDEX IF NOT EXISTS idx_tenants_slug ON {TENANTS_TABLE}(slug)")
        )

        # 2. users 表添加 tenant_id 列（如不存在）
        await session.execute(text(
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = 'users' AND column_name = 'tenant_id'
                ) THEN
                    ALTER TABLE users ADD COLUMN tenant_id INTEGER;
                END IF;
            END $$;
            """
        ))
        await session.execute(
            text("CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id)")
        )

        # 3. 添加外键约束（如不存在）
        await session.execute(text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'fk_users_tenant' AND table_name = 'users'
                ) THEN
                    ALTER TABLE users ADD CONSTRAINT fk_users_tenant
                    FOREIGN KEY (tenant_id) REFERENCES {TENANTS_TABLE}(id) ON DELETE SET NULL;
                END IF;
            END $$;
            """
        ))

        # 4. tenants.owner_id 外键（users 表可能是后建的，所以延迟添加）
        await session.execute(text(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.table_constraints
                    WHERE constraint_name = 'fk_tenants_owner' AND table_name = '{TENANTS_TABLE}'
                ) THEN
                    ALTER TABLE {TENANTS_TABLE} ADD CONSTRAINT fk_tenants_owner
                    FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL;
                END IF;
            END $$;
            """
        ))

        await session.commit()


async def create_tenant(data: TenantCreate) -> TenantInfo:
    """创建一个新租户。"""
    async with async_session_factory() as session:
        try:
            result = await session.execute(
                text(
                    f"INSERT INTO {TENANTS_TABLE}(name, slug, plan, owner_id, settings) "
                    "VALUES(:name, :slug, :plan, :owner_id, :settings::jsonb) RETURNING id, name, slug, plan, owner_id, settings, created_at"
                ),
                {
                    "name": data.name,
                    "slug": data.slug,
                    "plan": data.plan,
                    "owner_id": data.owner_id,
                    "settings": data.settings,
                },
            )
            row = result.mappings().first()
            await session.commit()
        except Exception as e:
            await session.rollback()
            raise e

    if not row:
        raise RuntimeError("创建租户失败")
    return TenantInfo(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        plan=row["plan"],
        owner_id=row["owner_id"],
        settings=row["settings"] or {},
        created_at=row["created_at"].isoformat() if row.get("created_at") else None,
    )


async def get_tenant(tenant_id: int) -> TenantInfo | None:
    """根据 ID 获取租户。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(f"SELECT id, name, slug, plan, owner_id, settings, created_at FROM {TENANTS_TABLE} WHERE id = :id"),
            {"id": tenant_id},
        )
        row = result.mappings().first()
    if not row:
        return None
    return TenantInfo(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        plan=row["plan"],
        owner_id=row["owner_id"],
        settings=row["settings"] or {},
        created_at=row["created_at"].isoformat() if row.get("created_at") else None,
    )


async def get_tenant_by_slug(slug: str) -> TenantInfo | None:
    """根据 slug 获取租户。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(f"SELECT id, name, slug, plan, owner_id, settings, created_at FROM {TENANTS_TABLE} WHERE slug = :slug"),
            {"slug": slug},
        )
        row = result.mappings().first()
    if not row:
        return None
    return TenantInfo(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        plan=row["plan"],
        owner_id=row["owner_id"],
        settings=row["settings"] or {},
        created_at=row["created_at"].isoformat() if row.get("created_at") else None,
    )


async def get_default_tenant() -> TenantInfo | None:
    """获取默认租户。"""
    return await get_tenant_by_slug(DEFAULT_TENANT_SLUG)


async def _get_or_create_default_tenant() -> TenantInfo:
    """获取或创建默认租户。"""
    existing = await get_default_tenant()
    if existing:
        return existing
    return await create_tenant(TenantCreate(
        name=DEFAULT_TENANT_NAME,
        slug=DEFAULT_TENANT_SLUG,
        plan="free",
    ))


async def create_default_tenant_for_existing_users() -> TenantInfo | None:
    """首次启动迁移：创建默认租户并将所有无 tenant_id 的用户关联到默认租户。

    返回默认租户（如果执行了迁移），如果所有用户都已有 tenant_id 则返回 None。
    """
    default_tenant = await _get_or_create_default_tenant()

    async with async_session_factory() as session:
        # 统计有多少用户没有 tenant_id
        result = await session.execute(
            text("SELECT COUNT(*) as cnt FROM users WHERE tenant_id IS NULL")
        )
        cnt = int(result.scalar() or 0)
        if cnt == 0:
            return None

        # 将所有无 tenant_id 的用户关联到默认租户
        await session.execute(
            text("UPDATE users SET tenant_id = :tid WHERE tenant_id IS NULL"),
            {"tid": default_tenant.id},
        )
        await session.commit()
        logger.info("已将 %d 个现有用户关联到默认租户(id=%d)", cnt, default_tenant.id)

    return default_tenant
