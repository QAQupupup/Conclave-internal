# 用户偏好（主题等）持久化 API
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request

from app.db_legacy import (
    delete_preference,
    get_all_preferences,
    get_preference,
    set_preference,
)
from app.schemas.preferences import PreferenceValue

router = APIRouter(prefix="/preferences", tags=["preferences"])


def _get_user_id(request: Request) -> str:
    """从认证中间件注入的 request.state.auth_user 获取当前用户 ID"""
    auth_user = getattr(request.state, "auth_user", None)
    if not auth_user:
        raise HTTPException(status_code=401, detail="未登录")
    uid = auth_user.get("uid") or auth_user.get("username")
    return str(uid)


@router.get("/")
async def list_preferences(request: Request) -> dict[str, str]:
    """返回当前用户全部偏好"""
    return await get_all_preferences(_get_user_id(request))


@router.get("/{key}")
async def get_preference_route(key: str, request: Request) -> dict[str, str]:
    """取单条偏好，不存在返回 404"""
    value = await get_preference(_get_user_id(request), key)
    if value is None:
        raise HTTPException(404, f"偏好 '{key}' 不存在")
    return {key: value}


@router.put("/{key}")
async def set_preference_route(key: str, body: PreferenceValue, request: Request) -> dict[str, Any]:
    """写入（upsert）单条偏好"""
    updated_at = await set_preference(_get_user_id(request), key, body.value)
    return {key: body.value, "updated_at": updated_at}


@router.delete("/{key}")
async def delete_preference_route(key: str, request: Request) -> dict[str, str]:
    """删除单条偏好，不存在返回 404"""
    deleted = await delete_preference(_get_user_id(request), key)
    if not deleted:
        raise HTTPException(404, f"偏好 '{key}' 不存在")
    return {"deleted": key}
