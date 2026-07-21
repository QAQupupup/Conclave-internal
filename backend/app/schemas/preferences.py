# 用户偏好相关 DTO
from __future__ import annotations

from pydantic import BaseModel


class PreferenceValue(BaseModel):
    """偏好写入请求体"""

    value: str
