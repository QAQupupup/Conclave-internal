"""
认证模块：JWT 登录认证 + 默认系统管理员
- 使用 HMAC-SHA256 签名 JWT（不引入额外依赖，基于标准库 + cryptography）
- 密码使用 PBKDF2-HMAC-SHA256 + salt 哈希（基于 hashlib/pbkdf2，标准库）
- [H-04 修复] PBKDF2 迭代次数提升至 600,000（符合 OWASP 2023+ 推荐）
- [H-05 修复] JWT 添加 iss(签发者)/aud(受众)/jti(唯一ID) 声明，防跨环境 token 重用
- 支持多用户角色：admin（最高权限，管理多租户）、user（普通用户）
- 向后兼容旧版 dev token（CONCLAVE_API_TOKEN 环境变量）
- 向后兼容旧密码哈希（260_000 次迭代仍可验证，新密码自动升级为 600_000 次）
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import threading
import time
import uuid
from typing import Any, Optional

from sqlalchemy import text

from app.db.engine import async_session_factory

logger = logging.getLogger(__name__)

# ---- 配置 ----
JWT_SECRET = os.environ.get("CONCLAVE_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = int(os.environ.get("CONCLAVE_JWT_EXPIRE", "86400"))  # 默认24小时

# [H-04 修复] PBKDF2 迭代次数：OWASP 2023+ 推荐 SHA-256 最低 600,000 次
PBKDF2_ITERATIONS = 600_000
# 旧迭代次数（兼容已存在的密码哈希）
PBKDF2_ITERATIONS_LEGACY = 260_000
PBKDF2_SALT_BYTES = 16

# [H-05 修复] JWT iss/aud 声明配置
# iss(issuer)：标识谁签发的 token，防止不同系统间 token 互用
# aud(audience)：标识 token 的接收方，防止同一系统不同 API 间 token 混用
JWT_ISSUER = os.environ.get("CONCLAVE_JWT_ISSUER", "conclave-backend")
JWT_AUDIENCE = os.environ.get("CONCLAVE_JWT_AUDIENCE", "conclave-api")

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
        # [L-03 修复] Windows 上 os.chmod 行为不同，跳过权限设置
        if not sys.platform.startswith("win"):
            os.chmod(secret_path, 0o600)
        logger.info("Generated new JWT secret at %s", secret_path)
    except OSError as e:
        logger.warning("Could not persist JWT secret: %s (will use ephemeral secret)", e)
    return JWT_SECRET


# ---- 密码哈希 ----

def hash_password(password: str, salt: Optional[bytes] = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    """PBKDF2-HMAC-SHA256 密码哈希，返回格式：pbkdf2_sha256$iterations$salt_b64$hash_b64

    [H-04 修复] 默认使用 600,000 次迭代；验证时从存储的哈希中读取实际迭代次数，
    旧密码（260,000 次）仍可验证。登录成功后可选择透明升级。
    """
    if salt is None:
        salt = secrets.token_bytes(PBKDF2_SALT_BYTES)
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(dk).decode("ascii")
    return f"pbkdf2_sha256${iterations}${salt_b64}${hash_b64}"


def verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """验证密码是否匹配存储的哈希。

    Returns:
        (valid, needs_rehash): valid=True 表示密码正确；needs_rehash=True 表示
            密码使用旧参数（如迭代次数较低），调用方应在登录成功后用新参数重新哈希。
    """
    try:
        parts = stored_hash.split("$")
        if len(parts) != 4 or parts[0] != "pbkdf2_sha256":
            return False, False
        iterations = int(parts[1])
        salt = base64.b64decode(parts[2])
        expected = parts[3]
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        actual = base64.b64encode(dk).decode("ascii")
        valid = hmac.compare_digest(expected, actual)
        # 迭代次数低于当前标准时需要重新哈希
        needs_rehash = valid and iterations < PBKDF2_ITERATIONS
        return valid, needs_rehash
    except Exception:
        return False, False


# ---- JWT ----

def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = 4 - (len(data) % 4)
    if pad != 4:
        data += "=" * pad
    return base64.urlsafe_b64decode(data)


def create_jwt(payload: dict[str, Any], expires_in: Optional[int] = None) -> str:
    """创建 JWT token

    [H-05 修复] 自动添加 iss/aud/jti/iat/exp 标准声明：
    - iss: 签发者标识（防跨系统 token 互用）
    - aud: 接收方标识（防同系统不同 API 间 token 混用）
    - jti: JWT 唯一 ID（支持未来 token 黑名单/撤销）
    """
    secret = _ensure_jwt_secret()
    now = int(time.time())
    exp = now + (expires_in if expires_in is not None else JWT_EXPIRE_SECONDS)
    claims = {
        **payload,
        "iss": JWT_ISSUER,
        "aud": JWT_AUDIENCE,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": exp,
    }
    header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
    h_b64 = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p_b64 = _b64url_encode(json.dumps(claims, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{h_b64}.{p_b64}".encode("ascii")
    sig = hmac.new(secret.encode("ascii"), signing_input, hashlib.sha256).digest()
    s_b64 = _b64url_encode(sig)
    return f"{h_b64}.{p_b64}.{s_b64}"


def verify_jwt(token: str) -> Optional[dict[str, Any]]:
    """验证 JWT，返回 payload 或 None

    [H-05 修复] 严格验证 iss 和 aud 声明，防止跨环境 token 重用。
    """
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
        # [H-05 修复] 验证 iss/aud 声明
        if claims.get("iss") != JWT_ISSUER:
            logger.warning("JWT iss 声明不匹配: expected=%s, got=%s", JWT_ISSUER, claims.get("iss"))
            return None
        aud = claims.get("aud")
        if aud != JWT_AUDIENCE:
            # aud 支持列表（RFC 7519 4.1.3），任一匹配即可
            if isinstance(aud, list):
                if JWT_AUDIENCE not in aud:
                    logger.warning("JWT aud 声明不匹配: expected=%s, got=%s", JWT_AUDIENCE, aud)
                    return None
            else:
                logger.warning("JWT aud 声明不匹配: expected=%s, got=%s", JWT_AUDIENCE, aud)
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


async def _update_password_hash(username: str, new_hash: str) -> None:
    """更新用户密码哈希（用于透明升级迭代次数）"""
    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE users SET password_hash = :hash WHERE username = :username"),
            {"hash": new_hash, "username": username},
        )
        await session.commit()
    with _users_lock:
        if username in _users_cache:
            _users_cache[username]["password_hash"] = new_hash


async def _update_last_login(username: str) -> None:
    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE users SET last_login_at = NOW() WHERE username = :username"),
            {"username": username},
        )
        await session.commit()


async def init_auth() -> None:
    """初始化认证系统：建表、加载用户、创建默认管理员

    [H-04 修复] 记录默认管理员密码配置状态，如果使用默认密码则输出警告。
    """
    await _init_users_table()
    await _load_users_from_db()
    _ensure_jwt_secret()

    # 创建默认管理员
    with _users_lock:
        if DEFAULT_ADMIN_USERNAME not in _users_cache:
            # 安全警告：如果使用默认密码，在日志中醒目标记
            using_default_pw = DEFAULT_ADMIN_PASSWORD == "admin123"
            log_level = logging.WARNING if using_default_pw else logging.INFO
            logger.log(
                log_level,
                "Creating default admin user: username=%s %s",
                DEFAULT_ADMIN_USERNAME,
                "(USING DEFAULT PASSWORD 'admin123' - SET CONCLAVE_ADMIN_PASSWORD IN PRODUCTION!)"
                if using_default_pw else "(custom password from env)",
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
    """验证用户名密码，返回用户信息（不含密码哈希）或 None

    [H-04 修复] 登录成功后自动将旧迭代次数的密码哈希升级到新标准。
    """
    with _users_lock:
        user = _users_cache.get(username)
    if not user:
        return None
    if not user.get("is_active"):
        return None
    valid, needs_rehash = verify_password(password, user["password_hash"])
    if not valid:
        return None
    # 更新最后登录时间
    try:
        await _update_last_login(username)
    except Exception:
        pass
    # 透明升级密码哈希（旧迭代次数 → 新迭代次数）
    if needs_rehash:
        try:
            new_hash = hash_password(password)
            await _update_password_hash(username, new_hash)
            logger.info("用户 %s 密码哈希已自动升级到 %d 次迭代", username, PBKDF2_ITERATIONS)
        except Exception as e:
            logger.warning("密码哈希升级失败（不影响登录）: %s", e)
    # 返回不含密码哈希的副本
    return {k: v for k, v in user.items() if k != "password_hash"}


def get_user_by_username(username: str) -> Optional[dict]:
    with _users_lock:
        user = _users_cache.get(username)
    if not user:
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


def require_role(required_role: str):
    """FastAPI 依赖：要求用户具有指定角色（admin 自动拥有所有权限）"""
    def _dep(user: dict = _get_current_user_dep) -> dict:
        if user.get("role") != "admin" and user.get("role") != required_role:
            from fastapi import HTTPException
            raise HTTPException(status_code=403, detail=f"权限不足：需要 {required_role} 角色")
        return user
    return _dep


def create_access_token(user: dict) -> str:
    """为用户创建 JWT access token"""
    return create_jwt({
        "sub": user["username"],
        "role": user.get("role", "user"),
        "uid": user.get("id"),
    })


def decode_token(token: str) -> Optional[dict]:
    """验证并解码 token，返回 {username, role, uid, jti, ...} 或 None"""
    claims = verify_jwt(token)
    if not claims:
        return None
    return {
        "username": claims.get("sub"),
        "role": claims.get("role", "user"),
        "uid": claims.get("uid"),
        "jti": claims.get("jti"),
    }


# 内部依赖标记（在 middleware 中注入 request.state.auth_user）
def _get_current_user_dep():
    """占位依赖，实际由 middleware 注入 request.state.auth_user。
    这里不做实际工作，仅用于路由签名。"""
    from fastapi import Request, HTTPException
    def _inner(request: Request) -> dict:
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="未授权")
        return user
    return _inner


# 便捷导出：require_admin 依赖
require_admin = None  # 在 routers 中通过 FastAPI Depends 注入
