"""租户服务：建表、CRUD、迁移、成员管理。"""
from __future__ import annotations

import logging
import re
from typing import Any

from sqlalchemy import text

from app.db.engine import async_session_factory
from app.tenants.models import TenantCreate, TenantInfo, TenantMember

logger = logging.getLogger(__name__)

TENANTS_TABLE = "tenants"
DEFAULT_TENANT_SLUG = "default"
DEFAULT_TENANT_NAME = "默认组织"

# 租户成员角色
ROLE_OWNER = "owner"
ROLE_ADMIN = "admin"
ROLE_MEMBER = "member"


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
    import json as _json
    from sqlalchemy.exc import IntegrityError as _IntegrityError
    async with async_session_factory() as session:
        try:
            result = await session.execute(
                text(
                    f"INSERT INTO {TENANTS_TABLE}(name, slug, plan, owner_id, settings) "
                    "VALUES(:name, :slug, :plan, :owner_id, CAST(:settings AS JSONB)) "
                    "RETURNING id, name, slug, plan, owner_id, settings, created_at"
                ),
                {
                    "name": data.name,
                    "slug": data.slug,
                    "plan": data.plan,
                    "owner_id": data.owner_id,
                    "settings": _json.dumps(data.settings, ensure_ascii=False),
                },
            )
            row = result.mappings().first()
            await session.commit()
        except _IntegrityError as e:
            await session.rollback()
            # slug 唯一约束冲突
            if "unique" in str(e).lower() or "duplicate" in str(e).lower():
                raise ValueError(f"slug '{data.slug}' 已存在") from e
            raise
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
            text(
                f"SELECT id, name, slug, plan, owner_id, settings, created_at "
                f"FROM {TENANTS_TABLE} WHERE id = :id"
            ),
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
            text(
                f"SELECT id, name, slug, plan, owner_id, settings, created_at "
                f"FROM {TENANTS_TABLE} WHERE slug = :slug"
            ),
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
        # 如果默认租户还没有 owner，将第一个用户设为 owner
        if default_tenant.owner_id is None:
            first_user = await session.execute(
                text("SELECT id FROM users WHERE tenant_id = :tid ORDER BY id ASC LIMIT 1"),
                {"tid": default_tenant.id},
            )
            first_row = first_user.mappings().first()
            if first_row:
                await session.execute(
                    text(f"UPDATE {TENANTS_TABLE} SET owner_id = :oid WHERE id = :tid"),
                    {"oid": first_row["id"], "tid": default_tenant.id},
                )
        await session.commit()
        logger.info("已将 %d 个现有用户关联到默认租户(id=%d)", cnt, default_tenant.id)

    # 重新查询以获取更新后的 owner_id
    return await get_tenant(default_tenant.id)


# 需要加 tenant_id 列的核心业务表（除 users 外，users 在 ensure_tenants_table 中已处理）
_BUSINESS_TABLES = [
    "meetings",
    "messages",
    "events",
    "meeting_tags",
    "meeting_aux",
    "user_preferences",
    "api_keys",
    "documents",
    "net_auth_requests",
    "cost_records",
    "docker_hosts",
]


async def ensure_business_tables_tenant_id() -> None:
    """为所有核心业务表添加 tenant_id 列（如不存在）。

    幂等：可重复调用。添加列后回填默认租户 ID（对于 tenant_id IS NULL 的历史数据）。
    """
    default_tenant = await get_default_tenant()
    default_tid = default_tenant.id if default_tenant else None

    async with async_session_factory() as session:
        for table in _BUSINESS_TABLES:
            await session.execute(text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = '{table}' AND column_name = 'tenant_id'
                    ) THEN
                        ALTER TABLE {table} ADD COLUMN tenant_id INTEGER;
                    END IF;
                END $$;
                """
            ))

        await session.commit()

        # 回填默认租户 ID
        if default_tid is not None:
            for table in _BUSINESS_TABLES:
                await session.execute(text(
                    f"UPDATE {table} SET tenant_id = :tid WHERE tenant_id IS NULL"
                ), {"tid": default_tid})
            await session.commit()
            logger.info("已为核心业务表回填默认租户 id=%d", default_tid)

        # 添加索引和外键
        for table in _BUSINESS_TABLES:
            await session.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_{table}_tenant_id ON {table}(tenant_id)"
            ))
            await session.execute(text(
                f"""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.table_constraints
                        WHERE constraint_name = 'fk_{table}_tenant' AND table_name = '{table}'
                    ) THEN
                        ALTER TABLE {table} ADD CONSTRAINT fk_{table}_tenant
                        FOREIGN KEY (tenant_id) REFERENCES {TENANTS_TABLE}(id) ON DELETE SET NULL;
                    END IF;
                END $$;
                """
            ))
        await session.commit()

    logger.info("核心业务表 tenant_id 列迁移完成")


# ============ 成员管理 ============


async def list_user_tenants(user_id: int) -> list[TenantInfo]:
    """列出用户所属的所有租户（通过 users.tenant_id 关联，后续可扩展为多对多）。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                f"""SELECT t.id, t.name, t.slug, t.plan, t.owner_id, t.settings, t.created_at
                FROM {TENANTS_TABLE} t
                WHERE t.id IN (
                    SELECT tenant_id FROM users WHERE id = :user_id AND tenant_id IS NOT NULL
                )
                OR t.owner_id = :user_id
                ORDER BY t.created_at ASC"""
            ),
            {"user_id": user_id},
        )
        rows = result.mappings().all()
    return [
        TenantInfo(
            id=r["id"],
            name=r["name"],
            slug=r["slug"],
            plan=r["plan"],
            owner_id=r["owner_id"],
            settings=r["settings"] or {},
            created_at=r["created_at"].isoformat() if r.get("created_at") else None,
        )
        for r in rows
    ]


async def list_tenant_members(tenant_id: int) -> list[TenantMember]:
    """列出租户内所有成员（包含 owner，即使 owner 当前活跃在其他租户）。"""
    async with async_session_factory() as session:
        # 先获取租户 owner_id
        t_result = await session.execute(
            text(f"SELECT id, owner_id FROM {TENANTS_TABLE} WHERE id = :tid"),
            {"tid": tenant_id},
        )
        t_row = t_result.mappings().first()
        if not t_row:
            return []
        owner_id = t_row["owner_id"]

        # 查询 tenant_id 指向该租户的用户（当前活跃成员）
        result = await session.execute(
            text(
                f"SELECT id, username, display_name, tenant_id, created_at "
                f"FROM users WHERE tenant_id = :tid ORDER BY created_at ASC"
            ),
            {"tid": tenant_id},
        )
        rows = list(result.mappings().all())
        existing_ids = {r["id"] for r in rows}

        # 如果 owner 不在列表中（例如 owner 已切换到其他租户），补充查询 owner 信息
        if owner_id is not None and owner_id not in existing_ids:
            owner_result = await session.execute(
                text(
                    "SELECT id, username, display_name, tenant_id, created_at "
                    "FROM users WHERE id = :oid"
                ),
                {"oid": owner_id},
            )
            owner_row = owner_result.mappings().first()
            if owner_row:
                rows.append(owner_row)

    members = []
    for r in rows:
        members.append(TenantMember(
            user_id=r["id"],
            username=r["username"],
            display_name=r["display_name"] or r["username"],
            email=None,
            role=ROLE_OWNER if r["id"] == owner_id else ROLE_MEMBER,
            joined_at=r["created_at"].isoformat() if r.get("created_at") else None,
        ))
    return members


async def user_has_tenant_access(user_id: int, tenant_id: int) -> bool:
    """检查用户是否有权访问指定租户（是成员或 owner）。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                f"SELECT 1 FROM {TENANTS_TABLE} t "
                "WHERE t.id = :tenant_id AND (t.owner_id = :user_id OR EXISTS ("
                "  SELECT 1 FROM users u WHERE u.id = :user_id AND u.tenant_id = :tenant_id"
                "))"
            ),
            {"tenant_id": tenant_id, "user_id": user_id},
        )
        return result.scalar() is not None


async def add_user_to_tenant(user_id: int, tenant_id: int, role: str = ROLE_MEMBER) -> bool:
    """将用户加入租户。目前是单租户模式（一个用户只能属于一个租户），
    直接更新 users.tenant_id。返回是否有变更。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text("UPDATE users SET tenant_id = :tid WHERE id = :uid"),
            {"tid": tenant_id, "uid": user_id},
        )
        await session.commit()
        return (result.rowcount or 0) > 0


async def is_tenant_owner(user_id: int, tenant_id: int) -> bool:
    """检查用户是否是租户 owner。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                f"SELECT 1 FROM {TENANTS_TABLE} WHERE id = :tid AND owner_id = :uid"
            ),
            {"tid": tenant_id, "uid": user_id},
        )
        return result.scalar() is not None


def generate_unique_slug(name: str) -> str:
    """从名称生成唯一 slug（带随机后缀）。实际唯一性由数据库 UNIQUE 约束保证。"""
    import secrets
    base = _slugify(name)
    suffix = secrets.token_hex(3)
    return f"{base}-{suffix}"
