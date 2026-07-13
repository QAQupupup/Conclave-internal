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
    return f.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_key(encrypted: str) -> str:
    """解密 API Key，返回明文字符串"""
    if not encrypted:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(encrypted.encode("ascii")).decode("utf-8")
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
    """保存或更新 API Key（加密后存入数据库）"""
    from sqlalchemy import select

    encrypted = encrypt_key(api_key)

    async with async_session_factory() as session:
        # 查找是否已存在
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
                provider=provider,
                name=name,
                encrypted_key=encrypted,
                base_url=base_url,
                is_default=is_default,
            )
            session.add(record)

        # 如果设为默认，取消同 provider 其他 key 的默认状态
        if is_default:
            others = await session.execute(
                select(ApiKeyModel).where(
                    ApiKeyModel.provider == provider,
                    ApiKeyModel.name != name,
                    ApiKeyModel.is_default.is_(True),
                )
            )
            for other in others.scalars().all():
                other.is_default = False

        await session.commit()

    # 同步更新内存中的 PROVIDERS 配置
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
    """列出所有已保存的 API Key（返回的 key 字段为脱敏形式，仅显示前4位+后4位）"""
    from sqlalchemy import select

    async with async_session_factory() as session:
        result = await session.execute(
            select(ApiKeyModel).order_by(ApiKeyModel.provider, ApiKeyModel.name)
        )
        records = result.scalars().all()

    keys = []
    for r in records:
        plain = decrypt_key(r.encrypted_key)
        masked = _mask_key(plain)
        keys.append({
            "id": r.id,
            "provider": r.provider,
            "name": r.name,
            "key_masked": masked,
            "base_url": r.base_url,
            "is_default": r.is_default,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        })
    return keys


async def get_api_key(provider: str, name: str = "default") -> str:
    """获取指定 provider 的明文 API Key（供 LLM 调用使用）"""
    from sqlalchemy import select

    async with async_session_factory() as session:
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
    """删除指定的 API Key"""
    from sqlalchemy import delete

    async with async_session_factory() as session:
        result = await session.execute(
            delete(ApiKeyModel).where(
                ApiKeyModel.provider == provider,
                ApiKeyModel.name == name,
            )
        )
        await session.commit()
        return result.rowcount > 0


async def load_keys_to_providers() -> int:
    """启动时调用：从数据库加载所有 Key 到内存 PROVIDERS 配置

    Returns:
        加载的 Key 数量
    """
    from sqlalchemy import select
    from app.llm_providers import PROVIDERS

    try:
        async with async_session_factory() as session:
            result = await session.execute(
                select(ApiKeyModel).where(ApiKeyModel.is_default.is_(True))
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
            logger.info("从数据库加载了 %d 个 API Key 到 Provider 配置", count)
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
