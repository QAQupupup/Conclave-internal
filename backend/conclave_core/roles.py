# 角色模糊匹配（模块级，支持中英文角色名）
from __future__ import annotations

from app.models import Role

_ROLE_KEYWORDS: dict[str, list[str]] = {
    Role.PRODUCT_ARCHITECT.value: ["product", "architect", "产品", "架构", "pm", "产品经理", "产品架构"],
    Role.SECURITY_EXPERT.value: ["security", "安全", "风控", "sec"],
    Role.DATA_ENGINEER.value: ["data", "数据", "analytics", "分析"],
    Role.UX_DESIGNER.value: ["ux", "design", "设计", "体验", "ui"],
    Role.MARKETING_EXPERT.value: ["marketing", "市场", "营销", "brand", "growth"],
    Role.ENGINEER.value: ["engineer", "develop", "开发", "工程", "后端", "前端", "技术"],
    Role.MODERATOR.value: ["moderator", "host", "主持", "协调", "facilitator"],
}


def match_role(role_str: str) -> Role | None:
    """模糊匹配角色名（支持中英文）"""
    role_lower = role_str.lower()
    for role, keywords in _ROLE_KEYWORDS.items():
        for kw in keywords:
            if kw in role_lower:
                return Role(role)
    return None
