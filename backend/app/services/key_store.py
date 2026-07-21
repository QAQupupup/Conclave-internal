"""API Key 加密存储服务

使用 Fernet 对称加密将 BYOK API Key 加密后存入数据库。
密钥从 CONCLAVE_SECRET_KEY 环境变量派生；若未设置则首次启动时自动生成
并存入数据目录（.secret_key 文件），确保重启后密钥一致。
"""

from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path
from typing import Any

from app.config import settings
from app.db.engine import async_session_factory
from app.db.models import ApiKeyModel
from app.observability.log_bus import log_bus
from app.tenants import current_tenant_id, tenant_filter_clause, is_system_tenant

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
) -> dict[str, Any]:
    """保存或更新 API Key（加密后存入数据库）。自动关联当前租户。"""
    from sqlalchemy import select

    encrypted = encrypt_key(api_key)
    tid = current_tenant_id()

    async with async_session_factory() as session:
        # 查找是否已存在：优先找租户专属 key，其次系统 key
        if tid is not None:
            result = await session.execute(
                select(ApiKeyModel).where(
                    ApiKeyModel.provider == provider,
                    ApiKeyModel.name == name,
                    ApiKeyModel.tenant_id == tid,
                )
            )
            existing = result.scalar_one_or_none()
            if existing is None:
                # 回退到系统 key（将被复制为租户专属）
                result2 = await session.execute(
                    select(ApiKeyModel).where(
                        ApiKeyModel.provider == provider,
                        ApiKeyModel.name == name,
                        ApiKeyModel.tenant_id.is_(None),
                    )
                )
                existing = result2.scalar_one_or_none()
                if existing is not None:
                    # 系统 key 不直接修改，创建租户专属副本
                    existing = None
        else:
            result = await session.execute(
                select(ApiKeyModel).where(
                    ApiKeyModel.provider == provider,
                    ApiKeyModel.name == name,
                )
            )
            existing = result.scalar_one_or_none()

        if existing:
            existing.encrypted_key = encrypted
            existing.base_url = base_url
            existing.is_default = is_default
            from datetime import datetime, timezone

            existing.updated_at = datetime.now(timezone.utc)
        else:
            record = ApiKeyModel(
                tenant_id=tid,
                provider=provider,
                name=name,
                encrypted_key=encrypted,
                base_url=base_url,
                is_default=is_default,
            )
            session.add(record)

        # 如果设为默认，取消同租户同 provider 其他 key 的默认状态
        if is_default:
            q = select(ApiKeyModel).where(
                ApiKeyModel.provider == provider,
                ApiKeyModel.name != name,
                ApiKeyModel.is_default.is_(True),
            )
            if tid is not None:
                q = q.where(ApiKeyModel.tenant_id == tid)
            others = await session.execute(q)
            for other in others.scalars().all():
                other.is_default = False

        await session.commit()

    # 同步更新内存中的 PROVIDERS 配置（仅系统级 key 更新全局配置）
    if tid is None:
        try:
            from app.llm_providers import PROVIDERS

            if provider in PROVIDERS:
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
        "saved": True,
    }


async def list_api_keys() -> list[dict[str, Any]]:
    """列出当前租户的 API Key（返回的 key 字段为脱敏形式，仅显示前4位+后4位）。
    同时返回系统级 key（tenant_id IS NULL）作为基础。
    """
    from sqlalchemy import and_, or_, select

    tid = current_tenant_id()
    async with async_session_factory() as session:
        if tid is not None:
            result = await session.execute(
                select(ApiKeyModel)
                .where(or_(ApiKeyModel.tenant_id == tid, ApiKeyModel.tenant_id.is_(None)))
                .order_by(ApiKeyModel.tenant_id.desc(), ApiKeyModel.provider, ApiKeyModel.name)
            )
        else:
            result = await session.execute(
                select(ApiKeyModel).order_by(ApiKeyModel.provider, ApiKeyModel.name)
            )
        records = result.scalars().all()

    keys = []
    for r in records:
        plain = decrypt_key(r.encrypted_key)
        masked = _mask_key(plain)
        keys.append(
            {
                "id": r.id,
                "provider": r.provider,
                "name": r.name,
                "key_masked": masked,
                "base_url": r.base_url,
                "is_default": r.is_default,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
        )
    return keys


async def get_api_key(provider: str, name: str = "default") -> str:
    """获取指定 provider 的明文 API Key（供 LLM 调用使用）。
    优先查租户专属 key，回退系统 key。
    """
    from sqlalchemy import or_, select

    tid = current_tenant_id()
    async with async_session_factory() as session:
        if tid is not None:
            result = await session.execute(
                select(ApiKeyModel).where(
                    ApiKeyModel.provider == provider,
                    ApiKeyModel.name == name,
                    or_(ApiKeyModel.tenant_id == tid, ApiKeyModel.tenant_id.is_(None)),
                ).order_by(ApiKeyModel.tenant_id.desc())
            )
        else:
            result = await session.execute(
                select(ApiKeyModel).where(
                    ApiKeyModel.provider == provider,
                    ApiKeyModel.name == name,
                )
            )
        record = result.scalar_one_or_none()

    if record:
        return decrypt_key(record.encrypted_key)
    return ""


async def delete_api_key(provider: str, name: str = "default") -> bool:
    """删除指定的 API Key（仅删除当前租户的 key，不删除系统 key）"""
    from sqlalchemy import delete

    tid = current_tenant_id()
    async with async_session_factory() as session:
        q = delete(ApiKeyModel).where(
            ApiKeyModel.provider == provider,
            ApiKeyModel.name == name,
        )
        if tid is not None:
            q = q.where(ApiKeyModel.tenant_id == tid)
        else:
            q = q.where(ApiKeyModel.tenant_id.is_(None))
        result = await session.execute(q)
        await session.commit()
        return result.rowcount > 0  # type: ignore[no-any-return]


async def load_keys_to_providers() -> int:
    """启动时调用：从数据库加载系统级默认 Key 到内存 PROVIDERS 配置

    仅加载 tenant_id IS NULL 的系统级 key。租户专属 key 在请求时按需加载。

    Returns:
        加载的 Key 数量
    """
    from sqlalchemy import select

    from app.llm_providers import PROVIDERS
    from app.tenants import create_system_tenant_ctx

    try:
        async with create_system_tenant_ctx():
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
