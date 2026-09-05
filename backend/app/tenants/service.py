"""租户服务：建表、CRUD、迁移、成员管理。"""

from __future__ import annotations

import logging
import re
from typing import cast

from sqlalchemy import CursorResult, text

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
        await session.execute(
            text(
                f"""
            CREATE TABLE IF NOT EXISTS {TENANTS_TABLE} (
                id SERIAL PRIMARY KEY,
                name VARCHAR(128) NOT NULL,
                slug VARCHAR(64) UNIQUE NOT NULL,
                plan VARCHAR(32) NOT NULL DEFAULT 'free',
                owner_id INTEGER,
                description TEXT NOT NULL DEFAULT '',
                settings JSONB NOT NULL DEFAULT '{{}}',
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP NOT NULL DEFAULT NOW()
            )
            """
            )
        )
        await session.execute(text(f"CREATE INDEX IF NOT EXISTS idx_tenants_slug ON {TENANTS_TABLE}(slug)"))

        # 1.5 tenants 表补充列（description, is_active）——幂等
        await session.execute(
            text(
                f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = '{TENANTS_TABLE}' AND column_name = 'description'
                ) THEN
                    ALTER TABLE {TENANTS_TABLE} ADD COLUMN description TEXT NOT NULL DEFAULT '';
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = '{TENANTS_TABLE}' AND column_name = 'is_active'
                ) THEN
                    ALTER TABLE {TENANTS_TABLE} ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT TRUE;
                END IF;
            END $$;
            """
            )
        )

        # 2. users 表添加 tenant_id 列（如不存在）
        await session.execute(
            text(
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
            )
        )
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_users_tenant_id ON users(tenant_id)"))

        # 3. 添加外键约束（如不存在）
        await session.execute(
            text(
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
            )
        )

        # 4. tenants.owner_id 外键（users 表可能是后建的，所以延迟添加）
        await session.execute(
            text(
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
            )
        )

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
            text(
                f"SELECT id, name, slug, plan, owner_id, settings, created_at FROM {TENANTS_TABLE} WHERE slug = :slug"
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
    return await create_tenant(
        TenantCreate(
            name=DEFAULT_TENANT_NAME,
            slug=DEFAULT_TENANT_SLUG,
            plan="free",
        )
    )


async def create_default_tenant_for_existing_users() -> TenantInfo | None:
    """首次启动迁移：创建默认租户并将所有无 tenant_id 的用户关联到默认租户。

    返回默认租户（如果执行了迁移），如果所有用户都已有 tenant_id 则返回 None。
    """
    default_tenant = await _get_or_create_default_tenant()

    async with async_session_factory() as session:
        # 统计有多少用户没有 tenant_id
        result = await session.execute(text("SELECT COUNT(*) as cnt FROM users WHERE tenant_id IS NULL"))
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
    "docker_host_secrets",
    "agent_roles",  # [Wave 4] 多租户隔离：自定义角色按租户隔离，内置角色 tenant_id=NULL
    # [Wave 5] 记忆子系统多租户隔离
    "raw_memories",
    "feature_memories",
    "profile_memories",
    # [ADR-017] 产物链核心实体表（ORM 建表已含 tenant_id，此处纳入自动迁移兜底，
    # 满足 docs/pitfalls.md P8 多租户隔离 Checklist 第 1 项）
    "artifacts",
    "projects",
    "issues",
]


async def ensure_business_tables_tenant_id() -> None:
    """为所有核心业务表添加 tenant_id 列（如不存在）。

    幂等：可重复调用。添加列后回填默认租户 ID（对于 tenant_id IS NULL 的历史数据）。
    [Wave 5] 增加 table 存在性检查，防止 ORM 表尚未 create_all 时 ALTER TABLE 报错。
    """
    default_tenant = await get_default_tenant()
    default_tid = default_tenant.id if default_tenant else None

    async with async_session_factory() as session:
        for table in _BUSINESS_TABLES:
            await session.execute(
                text(
                    f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables WHERE table_name = '{table}'
                    ) AND NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = '{table}' AND column_name = 'tenant_id'
                    ) THEN
                        ALTER TABLE {table} ADD COLUMN tenant_id INTEGER;
                    END IF;
                END $$;
                """
                )
            )

        await session.commit()

        # 回填默认租户 ID（仅对已存在的表）
        # 注意：不能在 UPDATE 语句的 WHERE 中用 EXISTS 检查表是否存在，
        # 因为 PostgreSQL 在解析阶段就需要表存在，WHERE EXISTS 无法阻止解析错误。
        # 必须先查询哪些表存在，再只对存在的表执行 UPDATE。
        if default_tid is not None:
            result = await session.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
                ),
                {"tables": list(_BUSINESS_TABLES)},
            )
            existing_tables = [row[0] for row in result.fetchall()]
            for table in existing_tables:
                await session.execute(
                    text(f"UPDATE {table} SET tenant_id = :tid WHERE tenant_id IS NULL"),
                    {"tid": default_tid},
                )
            await session.commit()
            logger.info("已为核心业务表回填默认租户 id=%d", default_tid)

        # 添加索引和外键（仅对已存在的表）
        for table in _BUSINESS_TABLES:
            await session.execute(
                text(
                    f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables WHERE table_name = '{table}'
                    ) THEN
                        CREATE INDEX IF NOT EXISTS idx_{table}_tenant_id ON {table}(tenant_id);
                    END IF;
                END $$;
                """
                )
            )
            await session.execute(
                text(
                    f"""
                DO $$
                BEGIN
                    IF EXISTS (
                        SELECT 1 FROM information_schema.tables WHERE table_name = '{table}'
                    ) THEN
                        -- 挂 FK 前先清理孤儿 tenant_id（引用不存在租户的存量数据置 NULL，
                        -- 与 ON DELETE SET NULL 语义一致；否则 ALTER TABLE 会因脏数据失败）
                        UPDATE {table} SET tenant_id = NULL
                        WHERE tenant_id IS NOT NULL
                          AND NOT EXISTS (
                              SELECT 1 FROM {TENANTS_TABLE} t WHERE t.id = {table}.tenant_id
                          );
                        IF NOT EXISTS (
                            SELECT 1 FROM information_schema.table_constraints
                            WHERE constraint_name = 'fk_{table}_tenant' AND table_name = '{table}'
                        ) THEN
                            ALTER TABLE {table} ADD CONSTRAINT fk_{table}_tenant
                            FOREIGN KEY (tenant_id) REFERENCES {TENANTS_TABLE}(id) ON DELETE SET NULL;
                        END IF;
                    END IF;
                END $$;
                """
                )
            )
        await session.commit()

    logger.info("核心业务表 tenant_id 列迁移完成")


# ============ 成员管理 ============


async def list_user_tenants(user_id: int) -> list[TenantInfo]:
    """列出用户所属的所有租户（通过 tenant_members 多对多关联 + owner 权限）。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                f"""SELECT DISTINCT t.id, t.name, t.slug, t.plan, t.owner_id, t.settings, t.created_at
                FROM {TENANTS_TABLE} t
                LEFT JOIN tenant_members tm ON tm.tenant_id = t.id AND tm.user_id = :user_id AND tm.is_banned = FALSE
                WHERE (tm.user_id = :user_id OR t.owner_id = :user_id)
                  AND (tm.is_banned = FALSE OR tm.is_banned IS NULL)
                ORDER BY t.created_at ASC"""
            ),
            {"user_id": user_id},
        )
        rows = result.mappings().all()

        # 兼容：如果以上查询无结果（旧数据/无 tenant_members 记录），回退到旧逻辑
        if not rows:
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
    """列出租户内所有成员（通过 tenant_members 关联，支持多角色）。"""
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

        # 查询 tenant_members JOIN users
        result = await session.execute(
            text(
                """SELECT u.id, u.username, u.display_name, u.email, tm.role, tm.is_banned, tm.joined_at
                FROM tenant_members tm
                INNER JOIN users u ON u.id = tm.user_id
                WHERE tm.tenant_id = :tid
                ORDER BY tm.joined_at ASC"""
            ),
            {"tid": tenant_id},
        )
        rows = result.mappings().all()

        # 兼容：如果 tenant_members 没有数据，回退到旧逻辑
        if not rows:
            result = await session.execute(
                text(
                    "SELECT id, username, display_name, tenant_id, created_at "
                    "FROM users WHERE tenant_id = :tid ORDER BY created_at ASC"
                ),
                {"tid": tenant_id},
            )
            old_rows = list(result.mappings().all())
            existing_ids = {r["id"] for r in old_rows}
            if owner_id is not None and owner_id not in existing_ids:
                owner_result = await session.execute(
                    text("SELECT id, username, display_name, tenant_id, created_at FROM users WHERE id = :oid"),
                    {"oid": owner_id},
                )
                owner_row = owner_result.mappings().first()
                if owner_row:
                    old_rows.append(owner_row)
            return [
                TenantMember(
                    user_id=r["id"],
                    username=r["username"],
                    display_name=r["display_name"] or r["username"],
                    email=None,
                    role=ROLE_OWNER if r["id"] == owner_id else ROLE_MEMBER,
                    joined_at=r["created_at"].isoformat() if r.get("created_at") else None,
                )
                for r in old_rows
            ]

    members = []
    for r in rows:
        role = r["role"] or (ROLE_OWNER if r["id"] == owner_id else ROLE_MEMBER)
        if r.get("is_banned"):
            continue  # 旧接口不返回被封禁的成员
        members.append(
            TenantMember(
                user_id=r["id"],
                username=r["username"],
                display_name=r["display_name"] or r["username"],
                email=r.get("email"),
                role=role,
                joined_at=r["joined_at"].isoformat() if r.get("joined_at") else None,
            )
        )
    return members


async def user_has_tenant_access(user_id: int, tenant_id: int) -> bool:
    """检查用户是否有权访问指定租户（通过 tenant_members 表，未被封禁）。"""
    async with async_session_factory() as session:
        # 先查 tenant_members
        result = await session.execute(
            text("SELECT 1 FROM tenant_members WHERE user_id = :uid AND tenant_id = :tid AND is_banned = FALSE"),
            {"uid": user_id, "tid": tenant_id},
        )
        if result.scalar() is not None:
            return True
        # 兼容：检查 owner 和旧逻辑（users.tenant_id）
        result = await session.execute(
            text(
                f"SELECT 1 FROM {TENANTS_TABLE} t "
                "WHERE t.id = :tid AND (t.owner_id = :uid OR EXISTS ("
                "  SELECT 1 FROM users u WHERE u.id = :uid AND u.tenant_id = :tid"
                "))"
            ),
            {"tid": tenant_id, "uid": user_id},
        )
        return result.scalar() is not None


async def add_user_to_tenant(user_id: int, tenant_id: int, role: str = ROLE_MEMBER) -> bool:
    """将用户加入租户。更新 users.tenant_id（活跃租户指针）并确保 tenant_members 有记录。

    返回是否有变更。
    """
    async with async_session_factory() as session:
        # 1. 更新活跃 tenant_id
        result = await session.execute(
            text("UPDATE users SET tenant_id = :tid WHERE id = :uid"),
            {"tid": tenant_id, "uid": user_id},
        )
        changed = (cast(CursorResult, result).rowcount or 0) > 0

        # 2. 确保 tenant_members 有记录（upsert）
        # 先检查租户是否存在
        t_result = await session.execute(
            text(f"SELECT owner_id FROM {TENANTS_TABLE} WHERE id = :tid"),
            {"tid": tenant_id},
        )
        t_row = t_result.mappings().first()
        if t_row:
            owner_id = t_row["owner_id"]
            # 如果用户是 owner，角色为 owner
            actual_role = ROLE_OWNER if owner_id == user_id else role
            await session.execute(
                text(
                    """
                    INSERT INTO tenant_members (tenant_id, user_id, role, is_banned, joined_at, created_at, updated_at)
                    VALUES (:tid, :uid, :role, FALSE, NOW(), NOW(), NOW())
                    ON CONFLICT(tenant_id, user_id) DO NOTHING
                    """
                ),
                {"tid": tenant_id, "uid": user_id, "role": actual_role},
            )
            changed = True

        await session.commit()
        return changed


async def is_tenant_owner(user_id: int, tenant_id: int) -> bool:
    """检查用户是否是租户 owner。"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(f"SELECT 1 FROM {TENANTS_TABLE} WHERE id = :tid AND owner_id = :uid"),
            {"tid": tenant_id, "uid": user_id},
        )
        return result.scalar() is not None


def generate_unique_slug(name: str) -> str:
    """从名称生成唯一 slug（带随机后缀）。实际唯一性由数据库 UNIQUE 约束保证。"""
    import secrets

    base = _slugify(name)
    suffix = secrets.token_hex(3)
    return f"{base}-{suffix}"
