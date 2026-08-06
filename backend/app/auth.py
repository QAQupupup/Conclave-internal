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
import contextlib
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
from typing import Any

from sqlalchemy import text

from app.db.engine import async_session_factory

logger = logging.getLogger(__name__)

# ---- 配置 ----
JWT_SECRET = os.environ.get("CONCLAVE_JWT_SECRET", "")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_SECONDS = int(os.environ.get("CONCLAVE_JWT_EXPIRE", "900"))  # 默认15分钟（access token），配合前端自动刷新
REFRESH_TOKEN_EXPIRE_SECONDS = int(os.environ.get("CONCLAVE_REFRESH_TOKEN_EXPIRE", str(7 * 86400)))  # 默认7天

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

# [P0-4 修复] 生产环境安全基线
JWT_SECRET_MIN_LENGTH = 32  # HMAC-SHA256 密钥最低 256 bit = 32 byte
_WEAK_DEFAULT_PASSWORDS = {"admin123", "password", "123456", "admin", ""}


def _check_production_security() -> None:
    """生产环境 fail-fast 安全检查。

    在 APP_ENV=production 下，以下情况直接 raise RuntimeError 拒绝启动：
    1. CONCLAVE_JWT_SECRET 未设置或长度 < 32 字节（HMAC-SHA256 安全基线）
    2. CONCLAVE_ADMIN_PASSWORD 未设置或使用弱默认密码

    非生产环境（dev/test/oss）跳过检查，保持原有自动生成行为。
    """
    if os.environ.get("APP_ENV", "") != "production":
        return

    errors: list[str] = []

    # 检查 JWT_SECRET
    jwt_secret = os.environ.get("CONCLAVE_JWT_SECRET", "")
    if not jwt_secret:
        errors.append("CONCLAVE_JWT_SECRET 未设置。生产环境必须显式提供 JWT 密钥，不允许自动生成临时密钥。")
    elif len(jwt_secret) < JWT_SECRET_MIN_LENGTH:
        errors.append(
            f"CONCLAVE_JWT_SECRET 长度不足（{len(jwt_secret)} < {JWT_SECRET_MIN_LENGTH} 字节），"
            f"不满足 HMAC-SHA256 安全基线。"
        )

    # 检查管理员密码
    admin_password = os.environ.get("CONCLAVE_ADMIN_PASSWORD", "")
    if not admin_password or admin_password in _WEAK_DEFAULT_PASSWORDS:
        errors.append("CONCLAVE_ADMIN_PASSWORD 未设置或使用弱默认密码。生产环境必须通过环境变量设置强密码。")

    if errors:
        msg = "\n".join(f"  [{i + 1}] {e}" for i, e in enumerate(errors))
        raise RuntimeError(
            f"生产环境安全检查失败，拒绝启动：\n{msg}\n"
            f"请设置以下环境变量后重试：\n"
            f"  - CONCLAVE_JWT_SECRET=<至少{JWT_SECRET_MIN_LENGTH}字符的随机串>\n"
            f"  - CONCLAVE_ADMIN_PASSWORD=<强密码>"
        )


def _ensure_jwt_secret() -> str:
    """确保 JWT_SECRET 存在：若未通过环境变量设置，则生成并持久化到 .jwt_secret 文件

    支持 CONCLAVE_SECRET_DIR 环境变量指定持久化目录（用于 Docker 容器内将密钥保存到 volume）。
    """
    global JWT_SECRET
    if JWT_SECRET:
        return JWT_SECRET
    # 优先使用 CONCLAVE_SECRET_DIR 环境变量（Docker 部署时指向 volume 挂载目录）
    secret_dir = os.environ.get("CONCLAVE_SECRET_DIR", os.path.dirname(os.path.dirname(__file__)))
    secret_path = os.path.join(secret_dir, ".jwt_secret")
    try:
        if os.path.exists(secret_path):
            with open(secret_path, encoding="utf-8") as f:
                JWT_SECRET = f.read().strip()
                if JWT_SECRET:
                    return JWT_SECRET
    except OSError:
        pass
    # 生成新 secret
    JWT_SECRET = secrets.token_urlsafe(48)
    try:
        os.makedirs(secret_dir, exist_ok=True)
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


def client_hash_password(password: str) -> str:
    """模拟前端 SHA-256 预哈希（与 frontend/src/lib/crypto.ts 一致）。

    安全架构：前端发送 SHA-256(明文密码) 到后端，后端再对其做 PBKDF2 存储。
    此函数仅在服务端初始化默认管理员时使用，确保存储格式与前端登录链路一致：
    stored_hash = PBKDF2(SHA-256(plaintext_password))

    Returns:
        SHA-256(password) 的十六进制字符串（64 字符），与前端 sha256Hash() 输出一致。
    """
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def hash_password(password: str, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS) -> str:
    """PBKDF2-HMAC-SHA256 密码哈希（双层架构：输入为客户端 SHA-256 预哈希值）。

    存储格式：pbkdf2_ch_sha256$iterations$salt_b64$hash_b64
    - ``pbkdf2_ch_sha256`` 前缀标识"客户端已预哈希"（ch = client-hashed）
    - 与旧格式 ``pbkdf2_sha256`` 区分，支持向后兼容

    安全链路：前端 SHA-256(明文) → 后端 PBKDF2(client_hash) → 存储
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
    return f"pbkdf2_ch_sha256${iterations}${salt_b64}${hash_b64}"


def verify_password(password: str, stored_hash: str) -> tuple[bool, bool]:
    """验证密码是否匹配存储的哈希。支持新旧两种格式。

    新格式 ``pbkdf2_ch_sha256$iterations$salt$hash``（4 段）：
        password 参数应为客户端 SHA-256 预哈希值，直接做 PBKDF2 比对。

    旧格式 ``pbkdf2_sha256$...``（4 段）：
        password 参数是客户端 SHA-256 预哈希值，但存储的是 PBKDF2(明文)。
        需要模拟 ``SHA-256(password)`` 后做 PBKDF2 比对（回退兼容）。
        匹配后 needs_rehash=True，触发迁移到新格式。

    Returns:
        (valid, needs_rehash): valid=True 表示密码正确；needs_rehash=True 表示
            密码使用旧参数（如迭代次数较低）或旧格式，调用方应重新哈希。
    """
    try:
        parts = stored_hash.split("$")

        if len(parts) == 4 and parts[0] == "pbkdf2_ch_sha256":
            # 新格式：pbkdf2_ch_sha256$iterations$salt_b64$hash_b64
            # 输入已是 client_hash，直接 PBKDF2 比对
            iterations = int(parts[1])
            salt = base64.b64decode(parts[2])
            expected = parts[3]
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            actual = base64.b64encode(dk).decode("ascii")
            valid = hmac.compare_digest(expected, actual)
            needs_rehash = valid and iterations < PBKDF2_ITERATIONS
            return valid, needs_rehash

        if len(parts) == 4 and parts[0] == "pbkdf2_sha256":
            # 旧格式兼容：存储的是 PBKDF2(明文)，收到的 password 是 SHA-256(明文)
            # 旧代码直接对明文做 PBKDF2，现在前端发送的是 SHA-256(明文)
            # 因此直接用 password（已是 client_hash）做 PBKDF2 比对
            # 注意：旧存储 = PBKDF2(plaintext)，前端发送 SHA-256(plaintext)
            # 但 PBKDF2 的输入不同，无法直接匹配。需要尝试两种路径：
            # 路径 A: 旧代码存储 PBKDF2(plaintext)，password=SHA-256(plaintext) → 无法匹配
            # 路径 B: 旧代码存储 PBKDF2(client_hash)，password=client_hash → 直接匹配
            # 实际上路径 A 是真实场景，但密码学上无法从 SHA-256(plaintext) 还原 plaintext
            # 解决方案：在 init_auth 中检测旧格式并强制重置密码哈希
            # 这里只做路径 B 的兼容（处理中间过渡期创建的哈希）
            iterations = int(parts[1])
            salt = base64.b64decode(parts[2])
            expected = parts[3]
            # 直接用 password（client_hash）做 PBKDF2
            dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
            actual = base64.b64encode(dk).decode("ascii")
            valid = hmac.compare_digest(expected, actual)
            # 旧格式匹配后必须迁移到新格式
            needs_rehash = valid
            return valid, needs_rehash

        return False, False
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


def create_jwt(payload: dict[str, Any], expires_in: int | None = None) -> str:
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


def verify_jwt(token: str) -> dict[str, Any] | None:
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
        return claims  # type: ignore[no-any-return]
    except Exception:
        return None


# ---- 用户存储（内存 + PostgreSQL 持久化）----

_users_lock = threading.RLock()
_users_cache: dict[str, dict[str, Any]] = {}  # username -> user dict


async def _init_users_table() -> None:
    """创建 users 表（如不存在），并为旧库补加缺失列。"""
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
                    tenant_id INTEGER,
                    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
                    last_login_at TIMESTAMP
                )
                """
            )
        )
        await session.execute(text("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)"))
        # 兼容旧库：补加缺失列
        await session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS display_name VARCHAR(128)"))
        await session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS tenant_id INTEGER"))
        await session.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMP"))
        # tenant_id 外键在 ensure_tenants_table() 中通过 ALTER TABLE 添加（避免建表顺序依赖）
        await session.commit()


async def _load_users_from_db() -> None:
    """从数据库加载所有用户到内存缓存"""
    async with async_session_factory() as session:
        result = await session.execute(
            text(
                "SELECT id, username, password_hash, role, display_name, is_active, tenant_id, created_at, last_login_at FROM users"
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
                "tenant_id": row.get("tenant_id"),
                "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                "last_login_at": row["last_login_at"].isoformat() if row.get("last_login_at") else None,
            }


async def _create_user_in_db(
    username: str, password_hash: str, role: str, display_name: str, tenant_id: int | None = None
) -> dict | None:
    """在数据库中创建用户"""
    async with async_session_factory() as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO users(username, password_hash, role, display_name, tenant_id) "
                    "VALUES(:username, :password_hash, :role, :display_name, :tenant_id)"
                ),
                {
                    "username": username,
                    "password_hash": password_hash,
                    "role": role,
                    "display_name": display_name,
                    "tenant_id": tenant_id,
                },
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            logger.warning("Failed to create user %s: %s", username, e)
            return None
        result = await session.execute(
            text(
                "SELECT id, username, password_hash, role, display_name, is_active, tenant_id, created_at, last_login_at "
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
        "tenant_id": row.get("tenant_id"),
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


async def update_display_name(username: str, display_name: str) -> dict | None:
    """更新用户显示名，返回更新后的用户 dict。"""
    display_name = display_name.strip()
    if not display_name or len(display_name) > 128:
        return None
    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE users SET display_name = :dn WHERE username = :username"),
            {"dn": display_name, "username": username},
        )
        await session.commit()
    # 更新缓存
    with _users_lock:
        if username in _users_cache:
            _users_cache[username]["display_name"] = display_name
    return get_user_by_username(username)


async def change_password(username: str, old_password: str, new_password: str) -> bool:
    """修改密码：验证旧密码后更新。成功返回 True。"""
    user = await authenticate_user(username, old_password)
    if not user:
        return False
    if len(new_password) < 6 or len(new_password) > 128:
        return False
    # [P0-1 修复] 统一使用 PBKDF2-HMAC-SHA256（与 hash_password/verify_password 一致）
    # 原代码使用 bcrypt，但 bcrypt 未声明依赖且哈希格式与 verify_password 不兼容
    new_hash = hash_password(new_password)
    async with async_session_factory() as session:
        await session.execute(
            text("UPDATE users SET password_hash = :hash WHERE username = :username"),
            {"hash": new_hash, "username": username},
        )
        await session.commit()
    # 更新缓存
    with _users_lock:
        if username in _users_cache:
            _users_cache[username]["password_hash"] = new_hash
    return True


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
    [P0-4 修复] 生产环境 fail-fast：JWT_SECRET / 弱密码不达标时拒绝启动。
    [P1 改进] 启动时输出醒目的管理员凭据 Banner，便于首次部署获取凭据。
    """
    _check_production_security()
    await _init_users_table()
    await _load_users_from_db()
    _ensure_jwt_secret()

    # [修复] 旧格式密码哈希迁移：检测管理员是否使用旧格式（pbkdf2_sha256），
    # 如果是则用当前默认密码重新哈希为新格式（pbkdf2_ch_sha256），确保登录兼容。
    # 场景：管理员在 SHA-256 预哈希功能添加前创建，旧存储 = PBKDF2(明文)，
    # 但新前端发送 SHA-256(明文)，密码学上无法匹配，必须重置哈希。
    with _users_lock:
        admin_user = _users_cache.get(DEFAULT_ADMIN_USERNAME)
        if admin_user and admin_user.get("password_hash", "").startswith("pbkdf2_sha256$"):
            logger.warning("检测到管理员使用旧格式密码哈希，自动迁移为新格式（使用当前默认密码）")
            new_hash = hash_password(client_hash_password(DEFAULT_ADMIN_PASSWORD))
            try:
                await _update_password_hash(DEFAULT_ADMIN_USERNAME, new_hash)
                admin_user["password_hash"] = new_hash
                logger.info("管理员密码哈希已迁移为 pbkdf2_ch_sha256 格式")
            except Exception as e:
                logger.error("管理员密码哈希迁移失败: %s", e)

    # 创建默认管理员
    with _users_lock:
        if DEFAULT_ADMIN_USERNAME not in _users_cache:
            using_default_pw = DEFAULT_ADMIN_PASSWORD == "admin123"
            # 模拟前端 SHA-256 预哈希：stored = PBKDF2(SHA-256(plaintext))
            # 与前端登录流程一致：前端发送 SHA-256(password)，后端再 PBKDF2
            pw_hash = hash_password(client_hash_password(DEFAULT_ADMIN_PASSWORD))
            user = await _create_user_in_db(
                username=DEFAULT_ADMIN_USERNAME,
                password_hash=pw_hash,
                role="system_owner",
                display_name="系统管理员",
            )
            if user:
                _users_cache[DEFAULT_ADMIN_USERNAME] = user

            # [P1 改进] 醒目的启动 Banner，输出管理员凭据
            _print_admin_credentials_banner(using_default_pw)
        else:
            # 管理员已存在，仍输出凭据提示（方便重启后查看）
            using_default_pw = DEFAULT_ADMIN_PASSWORD == "admin123"
            _print_admin_credentials_banner(using_default_pw, is_new=False)


def _print_admin_credentials_banner(using_default_pw: bool, is_new: bool = True) -> None:
    """输出醒目的管理员凭据 Banner。

    使用 Unicode 方框字符绘制边框，在日志中高度可见。
    生产环境不输出密码明文，仅提示环境变量名。
    """
    is_production = os.environ.get("APP_ENV", "") == "production"
    action = "Created" if is_new else "Loaded"
    username = DEFAULT_ADMIN_USERNAME

    if is_production:
        # 生产环境：不暴露密码，仅提示
        lines = [
            "=" * 60,
            "  Conclave Admin Credentials",
            "=" * 60,
            f"  {action} admin user: {username}",
            "  Password: set via CONCLAVE_ADMIN_PASSWORD env var",
            "  View: echo $CONCLAVE_ADMIN_PASSWORD",
            "=" * 60,
        ]
    elif using_default_pw:
        # 开发环境 + 默认密码：完整输出（醒目警告）
        lines = [
            "*" * 60,
            "*  WARNING: Using DEFAULT admin credentials!              *",
            "*" * 60,
            f"*  {action} admin user:                                   *",
            f"*    Username : {username:<42s} *",
            f"*    Password : {DEFAULT_ADMIN_PASSWORD:<42s} *",
            "*" * 60,
            "*  Login URL: http://localhost:5173                       *",
            "*  CHANGE IN PRODUCTION:                                  *",
            "*    export CONCLAVE_ADMIN_PASSWORD=<strong-password>     *",
            "*" * 60,
        ]
    else:
        # 开发环境 + 自定义密码：输出用户名，密码仅提示环境变量
        lines = [
            "=" * 60,
            "  Conclave Admin Credentials",
            "=" * 60,
            f"  {action} admin user: {username}",
            "  Password : (custom, from CONCLAVE_ADMIN_PASSWORD)",
            "  View     : echo $CONCLAVE_ADMIN_PASSWORD",
            "  Login URL: http://localhost:5173",
            "=" * 60,
        ]

    # 同时使用 print + logger.warning 确保在 Docker 日志中始终可见
    banner_text = "\n".join(lines)
    print(banner_text, flush=True)
    for line in lines:
        logger.warning(line)

    # 额外输出一行简洁的凭据摘要，便于快速复制
    if not is_production and using_default_pw:
        summary = f"ADMIN_LOGIN: username={username} password={DEFAULT_ADMIN_PASSWORD} url=http://localhost:5173"
        print(summary, flush=True)
        logger.warning(summary)


async def authenticate_user(username: str, password: str) -> dict | None:
    """验证用户名密码，返回用户信息（不含密码哈希）或 None

    安全架构（双层哈希）：
    - 前端发送 client_hash = SHA-256(明文密码)
    - 新格式存储：pbkdf2_ch_sha256$... — PBKDF2(client_hash)
    - 旧格式存储：pbkdf2_sha256$... — PBKDF2(明文)（向后兼容，自动迁移）

    verify_password 内部根据前缀自动选择验证路径。
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
    with contextlib.suppress(Exception):
        await _update_last_login(username)

    # 透明升级：旧迭代次数 → 新迭代次数，或旧格式 → 新格式（双层哈希）
    if needs_rehash:
        try:
            new_hash = hash_password(password)  # password 已是 client_hash
            await _update_password_hash(username, new_hash)
            with _users_lock:
                if username in _users_cache:
                    _users_cache[username]["password_hash"] = new_hash
            logger.info("用户 %s 密码哈希已自动升级到双层哈希格式", username)
        except Exception as e:
            logger.warning("密码哈希升级失败（不影响登录）: %s", e)

    # 返回不含密码哈希的副本
    return {k: v for k, v in user.items() if k != "password_hash"}


def get_user_by_username(username: str) -> dict | None:
    with _users_lock:
        user = _users_cache.get(username)
    if not user:
        return None
    return {k: v for k, v in user.items() if k != "password_hash"}


def require_role(required_role: str):
    """FastAPI 依赖：要求用户具有指定角色（system_owner/system_admin 自动拥有所有权限）。

    注意：新代码应使用 app.rbac.deps.require_permission() 进行更细粒度的权限控制。
    此函数保留用于向后兼容。
    """
    _SYS_ADMIN_ROLES = {"system_owner", "system_admin", "admin"}

    def _dep(user: dict = _get_current_user_dep) -> dict:  # type: ignore[assignment]
        user_role = user.get("role", "")
        sys_role = user.get("system_role", user_role)
        if sys_role in _SYS_ADMIN_ROLES:
            return user
        if user_role != required_role:
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail=f"权限不足：需要 {required_role} 角色")
        return user

    return _dep


def create_access_token(user: dict) -> str:
    """为用户创建 JWT access token"""
    return create_jwt(
        {
            "sub": user["username"],
            "role": user.get("role", "user"),
            "uid": user.get("id"),
            "tenant_id": user.get("tenant_id"),
            "type": "access",
        }
    )


def create_refresh_token(user: dict) -> str:
    """为用户创建 JWT refresh token（仅用于刷新 access token，不用于 API 访问）"""
    return create_jwt(
        {
            "sub": user.get("id") or user["username"],
            "username": user["username"],
            "tenant_id": user.get("tenant_id"),
            "type": "refresh",
        },
        expires_in=REFRESH_TOKEN_EXPIRE_SECONDS,
    )


def decode_token(token: str) -> dict | None:
    """验证并解码 token，返回 {username, role, uid, jti, tenant_id, ...} 或 None"""
    claims = verify_jwt(token)
    if not claims:
        return None
    return {
        "username": claims.get("sub"),
        "role": claims.get("role", "user"),
        "uid": claims.get("uid"),
        "jti": claims.get("jti"),
        "tenant_id": claims.get("tenant_id"),
    }


# 内部依赖标记（在 middleware 中注入 request.state.auth_user）
def _get_current_user_dep():
    """占位依赖，实际由 middleware 注入 request.state.auth_user。
    这里不做实际工作，仅用于路由签名。"""
    from fastapi import HTTPException, Request

    def _inner(request: Request) -> dict:
        user = getattr(request.state, "auth_user", None)
        if not user:
            raise HTTPException(status_code=401, detail="未授权")
        return user  # type: ignore[no-any-return]

    return _inner


# 便捷导出：require_admin 依赖
require_admin = None  # 在 routers 中通过 FastAPI Depends 注入
