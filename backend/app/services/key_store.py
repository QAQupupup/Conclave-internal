"""API Key 加密存储服务

使用 Fernet 对称加密将 BYOK API Key 加密后存入数据库。
密钥从 CONCLAVE_SECRET_KEY 环境变量派生；若未设置则首次启动时自动生成
并存入数据目录（.secret_key 文件），确保重启后密钥一致。
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.config import settings
from app.db.engine import async_session_factory
from app.db.models import ApiKeyModel
from app.llm_providers import PROVIDERS
from app.observability.log_bus import log_bus
from app.tenants import create_system_tenant_ctx, current_tenant_id
from app.tenants.context import is_system_tenant

logger = log_bus

# Fernet 实例（延迟初始化）
_fernet = None


def _get_fernet():
    """获取或初始化 Fernet 加密实例"""
    global _fernet
    if _fernet is not None:
        return _fernet

    from cryptography.fernet import Fernet

    # 1. 优先从环境变量获取密钥
    secret = os.environ.get("CONCLAVE_SECRET_KEY", "").strip()

    if not secret:
        # 2. 尝试从数据目录读取持久化密钥
        key_file = Path(settings.db_path).parent / ".secret_key"
        if key_file.exists():
            secret = key_file.read_text(encoding="utf-8").strip()
        else:
            # 3. 首次启动：生成新密钥并持久化
            secret = base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
            try:
                key_file.parent.mkdir(parents=True, exist_ok=True)
                key_file.write_text(secret, encoding="utf-8")
                # 限制文件权限
                os.chmod(key_file, 0o600)
                logger.info("已生成新的加密密钥并保存到 %s", key_file)
            except Exception as e:
                logger.warning("无法持久化加密密钥（重启后已存Key将无法解密）: %s", str(e)[:100])

    # 从任意长度字符串派生 32-byte Fernet 密钥
    key_bytes = hashlib.sha256(secret.encode("utf-8")).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    _fernet = Fernet(fernet_key)
    return _fernet


def encrypt_key(plaintext: str) -> str:
    """加密 API Key，返回 base64 编码字符串"""
    if not plaintext:
        return ""
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("ascii")  # type: ignore[no-any-return]


def decrypt_key(encrypted: str) -> str:
    """解密 API Key，返回明文字符串"""
    if not encrypted:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(encrypted.encode("ascii")).decode("utf-8")  # type: ignore[no-any-return]
    except Exception as e:
        logger.error("API Key 解密失败: %s", str(e)[:100])
        return ""


# ---- CRUD 操作 ----


async def save_api_key(
    provider: str,
    api_key: str,
    name: str = "default",
    base_url: str = "",
    is_default: bool = False,
    user_id: int | None = None,
) -> dict[str, Any]:
    """保存或更新 API Key（加密后存入数据库）。自动关联当前租户。

    支持三层存储：
    - user_id is not None: 个人 Key（优先级最高）
    - tenant_id is not None, user_id is None: Team Key（回退层）
    - 两者都为 None: 系统 Key（最低优先级，仅系统管理员可设置）

    [Wave 5] fail-closed：无租户上下文且非系统租户时拒绝操作，防止跨租户覆盖。
    """
    encrypted = encrypt_key(api_key)
    tid = current_tenant_id()

    # [Wave 5] fail-closed：无租户上下文且非系统租户时拒绝
    if tid is None and not is_system_tenant():
        raise RuntimeError("save_api_key 需要租户上下文或系统租户模式")

    async with async_session_factory() as session:
        # 查找是否已存在：按 (tenant_id, user_id, provider, name) 精确匹配
        q = select(ApiKeyModel).where(
            ApiKeyModel.provider == provider,
            ApiKeyModel.name == name,
        )
        if user_id is not None:
            # 个人 Key：精确匹配 user_id
            q = q.where(ApiKeyModel.tenant_id == tid, ApiKeyModel.user_id == user_id)
        elif tid is not None:
            # Team Key：tenant_id 匹配且 user_id IS NULL
            q = q.where(ApiKeyModel.tenant_id == tid, ApiKeyModel.user_id.is_(None))
        else:
            # 系统 Key：tenant_id IS NULL 且 user_id IS NULL
            q = q.where(ApiKeyModel.tenant_id.is_(None), ApiKeyModel.user_id.is_(None))

        result = await session.execute(q)
        existing = result.scalar_one_or_none()

        if existing:
            # 更新：api_key 为空时保留原密钥（支持仅切换默认/改 base_url）
            if api_key:
                existing.encrypted_key = encrypted
            existing.base_url = base_url if base_url else existing.base_url
            existing.is_default = is_default
            existing.updated_at = datetime.now(timezone.utc)
        else:
            if not api_key:
                raise ValueError("新建 Key 必须提供 api_key")
            record = ApiKeyModel(
                tenant_id=tid,
                user_id=user_id,
                provider=provider,
                name=name,
                encrypted_key=encrypted,
                base_url=base_url,
                is_default=is_default,
            )
            session.add(record)

        # 如果设为默认，取消同 scope 下其他 key 的默认状态
        if is_default:
            q_default = select(ApiKeyModel).where(
                ApiKeyModel.provider == provider,
                ApiKeyModel.name != name,
                ApiKeyModel.is_default.is_(True),
            )
            if user_id is not None:
                q_default = q_default.where(ApiKeyModel.tenant_id == tid, ApiKeyModel.user_id == user_id)
            elif tid is not None:
                q_default = q_default.where(ApiKeyModel.tenant_id == tid, ApiKeyModel.user_id.is_(None))
            else:
                q_default = q_default.where(ApiKeyModel.tenant_id.is_(None), ApiKeyModel.user_id.is_(None))
            others = await session.execute(q_default)
            for other in others.scalars().all():
                other.is_default = False

        await session.commit()

    # 同步更新内存中的 PROVIDERS 配置（仅系统级 key 更新全局配置）
    if tid is None and user_id is None:
        try:
            if provider in PROVIDERS:
                if api_key:
                    PROVIDERS[provider].api_key = api_key
                if base_url:
                    PROVIDERS[provider].base_url = base_url
        except Exception:
            pass

    return {
        "provider": provider,
        "name": name,
        "base_url": base_url,
        "is_default": is_default,
        "user_id": user_id,
        "saved": True,
    }


async def list_api_keys(
    scope: str = "team",
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    """列出 API Key。

    Args:
        scope: "personal"（个人 Key）/ "team"（Team Key）/ "system"（系统 Key，仅管理员）/ "all"（所有可见层）
        user_id: 用户 ID（scope=personal 时必填）

    返回的 key 字段为脱敏形式（前4位+后4位）。
    """
    tid = current_tenant_id()

    if tid is None and not is_system_tenant():
        logger.warning("list_api_keys 拒绝无租户上下文的查询")
        return []

    async with async_session_factory() as session:
        conditions = []
        if scope == "personal" and user_id is not None and tid is not None:
            conditions.append((ApiKeyModel.tenant_id == tid) & (ApiKeyModel.user_id == user_id))
        elif scope == "team" and tid is not None:
            conditions.append((ApiKeyModel.tenant_id == tid) & (ApiKeyModel.user_id.is_(None)))
        elif scope == "system":
            conditions.append((ApiKeyModel.tenant_id.is_(None)) & (ApiKeyModel.user_id.is_(None)))
        elif scope == "all":
            # 所有可见层：个人 + Team + 系统
            if user_id is not None and tid is not None:
                conditions.append((ApiKeyModel.tenant_id == tid) & (ApiKeyModel.user_id == user_id))
            if tid is not None:
                conditions.append((ApiKeyModel.tenant_id == tid) & (ApiKeyModel.user_id.is_(None)))
            conditions.append((ApiKeyModel.tenant_id.is_(None)) & (ApiKeyModel.user_id.is_(None)))
        else:
            # 默认：Team 层
            if tid is not None:
                conditions.append((ApiKeyModel.tenant_id == tid) & (ApiKeyModel.user_id.is_(None)))

        if not conditions:
            return []

        from sqlalchemy import or_ as _or

        query = (
            select(ApiKeyModel)
            .where(_or(*conditions))
            .order_by(
                ApiKeyModel.user_id.is_(None).asc(),  # personal first (user_id not null)
                ApiKeyModel.provider,
                ApiKeyModel.name,
            )
        )
        result = await session.execute(query)
        records = result.scalars().all()

    keys = []
    for r in records:
        plain = decrypt_key(r.encrypted_key)
        masked = _mask_key(plain)
        key_scope = "personal" if r.user_id else ("team" if r.tenant_id else "system")
        keys.append(
            {
                "id": r.id,
                "provider": r.provider,
                "name": r.name,
                "key_masked": masked,
                "base_url": r.base_url,
                "is_default": r.is_default,
                "scope": key_scope,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
        )
    return keys


async def get_api_key(
    provider: str,
    name: str = "default",
    user_id: int | None = None,
    base_url_only: bool = False,
) -> str | tuple[str, str]:
    """获取指定 provider 的明文 API Key（供 LLM 调用使用）。

    解析顺序（3 层回退）：
    1. 个人 Key（user_id 不为空时）
    2. Team Key（tenant_id 不为空时）
    3. 系统 Key（全局默认）

    [Wave 5] fail-closed：无租户上下文且非系统租户时返回空字符串。

    Args:
        provider: Provider 名
        name: Key 名称
        user_id: 用户 ID（传则先查个人 Key）
        base_url_only: True 时返回 (api_key, base_url) 元组
    """
    tid = current_tenant_id()

    # [Wave 5] fail-closed：无租户上下文且非系统租户时返回空
    if tid is None and not is_system_tenant():
        logger.warning("get_api_key 拒绝无租户上下文的查询: provider=%s", provider)
        return "" if not base_url_only else ("", "")

    async with async_session_factory() as session:
        # 构建查找条件：按优先级顺序查找
        conditions = []
        if user_id is not None and tid is not None:
            conditions.append((ApiKeyModel.tenant_id == tid) & (ApiKeyModel.user_id == user_id))
        if tid is not None:
            conditions.append((ApiKeyModel.tenant_id == tid) & (ApiKeyModel.user_id.is_(None)))
        conditions.append((ApiKeyModel.tenant_id.is_(None)) & (ApiKeyModel.user_id.is_(None)))

        for cond in conditions:
            result = await session.execute(
                select(ApiKeyModel).where(
                    ApiKeyModel.provider == provider,
                    ApiKeyModel.name == name,
                    cond,
                )
            )
            record = result.scalar_one_or_none()
            if record:
                key = decrypt_key(record.encrypted_key)
                if key:
                    if base_url_only:
                        return (key, record.base_url or "")
                    return key

    if base_url_only:
        return ("", "")
    return ""


async def get_resolved_key_and_base_url(
    provider: str,
    name: str = "default",
    user_id: int | None = None,
) -> tuple[str, str]:
    """同时获取 key 和 base_url（便捷方法）。"""
    result = await get_api_key(provider, name, user_id=user_id, base_url_only=True)
    if isinstance(result, tuple):
        return result
    return (result, "")


async def delete_api_key(
    provider: str,
    name: str = "default",
    user_id: int | None = None,
) -> bool:
    """删除指定的 API Key。

    按 scope 删除：
    - user_id 不为空：删除个人 Key
    - user_id 为空但有 tenant_id：删除 Team Key
    - 系统租户且两者都空：删除系统 Key
    """
    tid = current_tenant_id()

    if tid is None and not is_system_tenant():
        logger.warning("delete_api_key 拒绝无租户上下文的操作: provider=%s", provider)
        return False

    async with async_session_factory() as session:
        q = delete(ApiKeyModel).where(
            ApiKeyModel.provider == provider,
            ApiKeyModel.name == name,
        )
        if user_id is not None:
            q = q.where(ApiKeyModel.tenant_id == tid, ApiKeyModel.user_id == user_id)
        elif tid is not None:
            q = q.where(ApiKeyModel.tenant_id == tid, ApiKeyModel.user_id.is_(None))
        else:
            q = q.where(ApiKeyModel.tenant_id.is_(None), ApiKeyModel.user_id.is_(None))
        result = await session.execute(q)
        await session.commit()
        return result.rowcount > 0  # type: ignore[attr-defined, no-any-return]


async def load_keys_to_providers() -> int:
    """启动时调用：从数据库加载系统级默认 Key 到内存 PROVIDERS 配置

    仅加载 tenant_id IS NULL 的系统级 key。租户专属 key 在请求时按需加载。

    Returns:
        加载的 Key 数量
    """
    try:
        with create_system_tenant_ctx():
            async with async_session_factory() as session:
                result = await session.execute(
                    select(ApiKeyModel).where(
                        ApiKeyModel.is_default.is_(True),
                        ApiKeyModel.tenant_id.is_(None),
                    )
                )
                defaults = result.scalars().all()

        count = 0
        for record in defaults:
            plain = decrypt_key(record.encrypted_key)
            if plain and record.provider in PROVIDERS:
                PROVIDERS[record.provider].api_key = plain
                if record.base_url:
                    PROVIDERS[record.provider].base_url = record.base_url
                count += 1

        if count > 0:
            logger.info(f"从数据库加载了 {count} 个 API Key 到 Provider 配置", logger="services.key_store")
        return count
    except Exception as e:
        logger.warning("加载持久化 API Key 失败: %s", str(e)[:200])
        return 0


def _mask_key(key: str) -> str:
    """脱敏显示 Key：前4位 + *** + 后4位"""
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return f"{key[:4]}***{key[-4:]}"
