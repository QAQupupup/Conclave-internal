"""租户数据模型。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TenantInfo:
    """租户信息（API 返回/内存缓存用）。"""

    id: int
    name: str
    slug: str
    plan: str = "free"  # free / pro / enterprise
    owner_id: int | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None
    role: str | None = None  # 当前用户在该租户的角色（list_user_tenants 时填充）


@dataclass
class TenantCreate:
    """创建租户请求。"""

    name: str
    slug: str
    plan: str = "free"
    owner_id: int | None = None
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class TenantMember:
    """租户成员信息。"""

    user_id: int
    username: str
    display_name: str
    email: str | None = None
    role: str = "member"  # owner / admin / member
    joined_at: str | None = None
