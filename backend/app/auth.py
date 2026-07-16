"""
认证模块：JWT 登录认证 + 默认系统管理员
- 使用 HMAC-SHA256 签名 JWT（不引入额外依赖，基于标准库 + cryptography）
- 密码使用 PBKDF2-HMAC-SHA256 + salt 哈希（基于 hashlib/pbkdf2，标准库）
- 支持多用户角色：admin（最高权限，管理多租户）、user（普通用户）
- 向后兼容旧版 dev token（CONCLAVE_API_TOKEN 环境变量）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from typing import Any, Optional

from sqlalchemy import text

from app.db.engine import async_session_factory

logger = logging.getLogger(__name__)

# ---- 配置 ----
JWT_SECRET = os.environ.get("CONCLAVE_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = int(os.environ.get("CONCLAVE_JWT_EXPIRE", "86400"))  # 默认24小时
PBKDF2_ITERATIONS = 260_000  # OWASP 推荐 2023+ 最低 600,000（SHA-256）；取平衡值
PBKDF2_SALT_BYTES = 16

# 默认管理员账号（首次启动自动创建）
DEFAULT_ADMIN_USERNAME = os.environ.get("CONCLAVE_ADMIN_USERNAME", "admin")
DEFAULT_ADMIN_PASSWORD = os.environ.get("CONCLAVE_ADMIN_PASSWORD", "admin123")


def _ensure_jwt_secret() -> str:
    """确保 JWT_SECRET 存在：若未通过环境变量设置，则生成并持久化到 .jwt_secret 文件"""
    global JWT_SECRET
    if JWT_SECRET:
        return JWT_SECRET
    secret_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".jwt_secret")
    try:
        if os.path.exists(secret_path):
            with open(secret_path, "r", encoding="utf-8") as f:
                JWT_SECRET = f.read().strip()
                if JWT_SECRET:
                    return JWT_SECRET
    except OSError:
        pass
    # 生成新 secret
    JWT_SECRET = secrets.token_urlsafe(48)
    try:
        with open(secret_path, "w", encoding="utf-8") as f:
            f.write(JWT_SECRET)
        os.chmod(secret_path, 0o600)
        logger.info("Generated new JWT secret at %s", secret_path)
    except OSError as e:
        logger.warning("Could not persist JWT secret: %s (will use ephemeral secret)", e)
    return JWT_SECRET


# ---- 密码哈希 ----

def hash_password(password: str, salt: Optional[bytes] = None) -> str:
    """PBKDF2-HMAC-SHA256 密码哈希，返回格式：pbkdf2_sha256$iterations$salt_b64$hash_b64"""
    if salt is None:
        salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(dk).decode("ascii")
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt_b64}${hash_b64}"


def verify_password(password: str, stored_hash: str) -> bool:
    """验证密码是否匹配存储的哈希"""
    try:
        parts = stored_hash.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False
        iterations = int(parts[1])
        salt = base64.b64decode(parts[2])
        expected = parts[3]
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        actual = base64.b64encode(dk).decode("ascii")
        return hmac.compare_digest(expected, actual)
    except Exception:
        return False


# ---- JWT ----

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = 4 - (len(data) % 4)
    if pad != 4:
        data += "=" * pad
    return base64.urlsafe_b64decode(data)


def create_jwt(payload: dict[str, Any], expires_in: Optional[int] = None) -> str:
    """创建 JWT token"""
    secret = _ensure_jwt_secret()
    now = int(time.time())
    exp = now + (expires_in if expires_in is not None else JWT_EXPIRE_SECONDS)
    claims = {**payload, "iat": now, "exp": exp}
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    h_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b64 = _b64url_encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = hmac.new(secret.encode("ascii"), signing_input, hashlib.sha256).digest()
    s_b64 = _b64url_encode(sig)
    return f"{h_b64}.{p_b64}.{s_b64}"


def verify_jwt(token: str) -> Optional[dict[str, Any]]:
    """验证 JWT，返回 payload 或 None"""
    try:
        secret = _ensure_jwt_secret()
        parts = token.split(".")
        if len(parts) != 3:
            return None
        h_b64, p_b64, s_b64 = parts
        signing_input = f"{h_b64}.{p_b64}".encode("ascii")
        expected_sig = hmac.new(secret.encode("ascii"), signing_input, hashlib.sha256).digest()
        actual_sig = _b64url_decode(s_b64)
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        claims = json.loads(_b64url_decode(p_b64))
        if claims.get("exp", 0) < int(time.time()):
            return None
        return claims
    except Exception:
        return None


# ---- 用户存储（内存 + PostgreSQL 持久化）----

_users_lock = threading.RLock()
_users_cache: dict[str, dict[str, Any]] = {}  # username -> user dict


async def _init_users_table() -> None:
    """创建 users 表（如不存在）"""
    async with async_session_factory() as session:
        await session.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(64) UNIQUE NOT NULL,
                    password_hash VARCHAR(256) NOT NULL,
                    role VARCHAR(32) NOT NULL DEFAULT 'user',
                    display_name VARCHAR(128),
                    is_active BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    last_login_at TIMESTAMP
                )
                """
            )
        )
        await session.execute(
            text("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        )
        await session.commit()


async def _load_users_from_db() -> None:
    """从数据库加载所有用户到内存缓存"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT id, username, password_hash, role, display_name, is_active, created_at, last_login_at FROM users"
            )
        )
        rows = result.mappings().all()
    with _users_lock:
        _users_cache.clear()
        for row in rows:
            username = row["username"]
            _users_cache[username] = {
                "id": row["id"],
                "username": username,
                "password_hash": row["password_hash"],
                "role": row["role"],
                "display_name": row.get("display_name") or username,
                "is_active": bool(row["is_active"]),
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                "last_login_at": row["last_login_at"].isoformat() if row.get("last_login_at") else None,
            }


async def _create_user_in_db(username: str, password_hash: str, role: str, display_name: str) -> Optional[dict]:
    """在数据库中创建用户"""
    async with async_session_factory() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO users(username, password_hash, role, display_name) "
                    "VALUES(:username, :password_hash, :role, :display_name)"
                ),
                {
                    "username": username,
                    "password_hash": password_hash,
                    "role": role,
                    "display_name": display_name,
                },
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.warning("Failed to create user %s: %s", username, e)
            return None
        result = await session.execute(
            text(
                "SELECT id, username, password_hash, role, display_name, is_active, created_at, last_login_at "
                "FROM users WHERE username = :username"
            ),
            {"username": username},
        )
        row = result.mappings().first()
    if not row:
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "password_hash": row["password_hash"],
        "role": row["role"],
        "display_name": row.get("display_name") or username,
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "last_login_at": row["last_login_at"].isoformat() if row.get("last_login_at") else None,
    }


async def _update_last_login(username: str) -> None:
    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE users SET last_login_at = NOW() WHERE username = :username"),
            {"username": username},
        )
        await session.commit()


async def init_auth() -> None:
    """初始化认证系统：建表、加载用户、创建默认管理员"""
    await _init_users_table()
    await _load_users_from_db()
    _ensure_jwt_secret()

    # 创建默认管理员
    with _users_lock:
        if DEFAULT_ADMIN_USERNAME not in _users_cache:
            logger.info(
                "Creating default admin user: username=%s (set CONCLAVE_ADMIN_PASSWORD to change)",
                DEFAULT_ADMIN_USERNAME,
            )
            pw_hash = hash_password(DEFAULT_ADMIN_PASSWORD)
            user = await _create_user_in_db(
                username=DEFAULT_ADMIN_USERNAME,
                password_hash=pw_hash,
                role="admin",
                display_name="系统管理员",
            )
            if user:
                _users_cache[DEFAULT_ADMIN_USERNAME] = user


async def authenticate_user(username: str, password: str) -> Optional[dict]:
    """验证用户名密码，返回用户信息（不含密码哈希）或 None"""
    with _users_lock:
        user = _users_cache.get(username)
    if not user:
        return None
    if not user.get("is_active"):
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    # 更新最后登录时间
    try:
        await _update_last_login(username)
    except Exception:
        pass
    # 返回不含密码哈希的副本
    return {k: v for k, v in user.items() if k != "password_hash"}


def get_user_by_username(username: str) -> Optional[dict]:
    with _users_lock:
        user = _users_cache.get(username)
    if not user:
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


def create_access_token(user: dict) -> str:
    """为用户创建 JWT access token"""
    return create_jwt({
        "sub": user["username"],
        "role": user.get("role", "user"),
        "uid": user.get("id"),
    })


def decode_token(token: str) -> Optional[dict]:
    """验证并解码 token，返回 {username, role, uid, ...} 或 None"""
    claims = verify_jwt(token)
    if not claims:
        return None
    return {
        "username": claims.get("sub"),
        "role": claims.get("role", "user"),
        "uid": claims.get("uid"),
    }
