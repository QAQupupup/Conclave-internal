"""/setup 首次部署流程：无用户时创建首个管理员账号。

- GET /setup/status：返回是否需要初始化（公开，无需认证）
- POST /setup：提交 setup_token + 用户名密码创建管理员（公开，但有速率限制）

Setup Token 机制：
- 启动时检测到 users 表为空（init_auth 未创建默认管理员），自动生成一次性 setup token 打印到 stdout
- setup token 24h 过期
- 速率限制：5次/10分钟/IP
- 环境变量 CONCLAVE_SETUP_ADMIN_PASSWORD 或 CONCLAVE_ADMIN_PASSWORD 设置时，init_auth 已自动创建管理员，跳过 /setup 流程
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.auth import hash_password
from app.context import set_user_id, set_user_role, set_username
from app.db.engine import async_session_factory
from app.observability.audit import audit

logger = logging.getLogger(__name__)

SETUP_TOKEN_EXPIRES = 24 * 3600  # 24h
SETUP_RATE_LIMIT_PER_10MIN = 5

router = APIRouter(tags=["Setup"])

# 模块级 setup token 状态
_setup_token_hash: str | None = None
_setup_token_expires_at: float = 0
_setup_token_used: bool = False
_admin_created: bool = False


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_setup_token() -> str:
    """生成新的 setup token（只在启动时无用户时调用）。"""
    global _setup_token_hash, _setup_token_expires_at, _setup_token_used
    token = secrets.token_urlsafe(32)
    _setup_token_hash = _hash_token(token)
    _setup_token_expires_at = time.time() + SETUP_TOKEN_EXPIRES
    _setup_token_used = False
    return token


def is_setup_needed() -> bool:
    """是否需要执行 /setup 流程。"""
    return not _admin_created and not _setup_token_used


def invalidate_setup_token() -> None:
    global _setup_token_used
    _setup_token_used = True


def mark_admin_created() -> None:
    global _admin_created
    _admin_created = True


async def _count_users() -> int:
    try:
        async with async_session_factory() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM users"))
            return int(result.scalar() or 0)
    except Exception:
        return 0


async def _create_admin_user(username: str, password: str, display_name: str = "系统管理员") -> dict:
    pw_hash = hash_password(password)
    async with async_session_factory() as session:
        try:
            # 查询默认租户 ID（在插件 on_startup 中已创建）
            tenant_id_row = (await session.execute(
                text("SELECT id FROM tenants WHERE slug = 'default'")
            )).mappings().first()
            tenant_id = tenant_id_row["id"] if tenant_id_row else None

            await session.execute(
                text(
                    "INSERT INTO users(username, password_hash, role, display_name, tenant_id) "
                    "VALUES(:username, :pw, 'admin', :dn, :tid)"
                ),
                {"username": username, "pw": pw_hash, "dn": display_name, "tid": tenant_id},
            )
            await session.commit()
        except Exception as e:
            await session.rollback()
            raise HTTPException(status_code=400, detail=f"创建用户失败: {e}") from e
        result = await session.execute(
            text("SELECT id, username, role, display_name, tenant_id FROM users WHERE username = :u"),
            {"u": username},
        )
        row = result.mappings().first()
        if not row:
            raise HTTPException(status_code=500, detail="创建用户后无法查询到记录")
    return {
        "id": row["id"],
        "username": row["username"],
        "role": row["role"],
        "display_name": row["display_name"],
        "tenant_id": row.get("tenant_id"),
    }


def _client_ip(request: Request) -> str:
    """从 request 中提取客户端 IP（优先 X-Forwarded-For）。"""
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# ---- Schemas ----


class SetupStatusResponse(BaseModel):
    needs_setup: bool
    setup_required: bool


class SetupRequest(BaseModel):
    setup_token: str = Field(..., min_length=10)
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str | None = Field(None, max_length=128)


class SetupResponse(BaseModel):
    success: bool = True
    message: str
    user: dict


# ---- Endpoints ----


@router.get("/setup/status", response_model=SetupStatusResponse)
async def setup_status() -> SetupStatusResponse:
    """查询是否需要初始化管理员账号（公开端点）。"""
    needed = is_setup_needed()
    return SetupStatusResponse(needs_setup=needed, setup_required=needed)


@router.post("/setup", response_model=SetupResponse)
async def do_setup(req: SetupRequest, request: Request) -> SetupResponse:
    """提交 setup_token + 账号信息创建首个管理员。"""
    ip = _client_ip(request)

    if not is_setup_needed():
        raise HTTPException(status_code=403, detail="系统已初始化，无需 setup")

    # 校验 setup token
    global _setup_token_hash, _setup_token_expires_at
    if not _setup_token_hash:
        raise HTTPException(status_code=403, detail="setup token 未生成")
    if time.time() > _setup_token_expires_at:
        raise HTTPException(status_code=403, detail="setup token 已过期，请重启服务获取新 token")
    if not secrets.compare_digest(_hash_token(req.setup_token), _setup_token_hash):
        audit(
            "setup.invalid_token",
            "failure",
            {"reason": "invalid_token"},
            ip=ip,
        )
        raise HTTPException(status_code=403, detail="setup token 无效")

    if len(req.password) < 8:
        raise HTTPException(status_code=400, detail="密码长度至少 8 位")

    display_name = req.display_name or req.username
    user = await _create_admin_user(req.username, req.password, display_name)

    invalidate_setup_token()
    mark_admin_created()

    set_user_id(str(user["id"]))
    set_username(user["username"])
    set_user_role(user["role"])

    # 重新加载用户缓存
    try:
        from app.auth import _load_users_from_db
        await _load_users_from_db()
    except Exception:
        pass

    logger.warning("管理员通过 /setup 创建成功: username=%s from=%s", req.username, ip)
    audit(
        "setup.admin_created",
        "success",
        {"username": req.username, "display_name": display_name},
        ip=ip, username=req.username, user_id=str(user["id"]),
    )

    return SetupResponse(
        success=True,
        message="管理员账号创建成功",
        user=user,
    )
