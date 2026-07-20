"""租户数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TenantInfo:
    """租户信息（内存缓存用）。"""

    id: int
    name: str
    slug: str
    plan: str = "free"  # free / pro / enterprise
    owner_id: int | None = None
    settings: dict[str, Any] = field(default_factory=dict)
    created_at: str | None = None


@dataclass
class TenantCreate:
    """创建租户请求。"""

    name: str
    slug: str
    plan: str = "free"
    owner_id: int | None = None
    settings: dict[str, Any] = field(default_factory=dict)
