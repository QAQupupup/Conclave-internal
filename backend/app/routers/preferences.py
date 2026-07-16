# 用户偏好（主题等）持久化 API
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.db_legacy import (
    delete_preference,
    get_all_preferences,
    get_preference,
    set_preference,
)
from app.schemas.preferences import PreferenceValue

router = APIRouter(prefix="/preferences", tags=["preferences"])

# 当前单用户，固定 user_id
DEFAULT_USER_ID = "default"


@router.get("/")
async def list_preferences() -> dict[str, str]:
    """返回当前用户全部偏好"""
    return await get_all_preferences(DEFAULT_USER_ID)


@router.get("/{key}")
async def get_preference_route(key: str) -> dict[str, str]:
    """取单条偏好，不存在返回 404"""
    value = await get_preference(DEFAULT_USER_ID, key)
    if value is None:
        raise HTTPException(404, f"偏好 '{key}' 不存在")
    return {key: value}


@router.put("/{key}")
async def set_preference_route(key: str, body: PreferenceValue) -> dict[str, Any]:
    """写入（upsert）单条偏好"""
    updated_at = await set_preference(DEFAULT_USER_ID, key, body.value)
    return {key: body.value, "updated_at": updated_at}


@router.delete("/{key}")
async def delete_preference_route(key: str) -> dict[str, str]:
    """删除单条偏好，不存在返回 404"""
    deleted = await delete_preference(DEFAULT_USER_ID, key)
    if not deleted:
        raise HTTPException(404, f"偏好 '{key}' 不存在")
    return {"deleted": key}
