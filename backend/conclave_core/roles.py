# 角色模糊匹配（模块级，支持中英文角色名）
# 注意：迭代顺序即优先级——特定专业角色（security/data/ux/marketing/engineer）
# 必须排在 product_architect 之前，避免 "后端架构师" 等复合角色名被
# product_architect 的 "架构" 关键词贪婪匹配。
# product_architect 的关键词中不包含单独的 "架构"（太宽泛）和 "pm"（太短），
# 只保留 "产品架构" 和 "architect" 等更明确的词。
from __future__ import annotations

from app.models import Role

_ROLE_KEYWORDS: dict[str, list[str]] = {
    Role.SECURITY_EXPERT.value: ["security", "安全", "风控", "sec"],
    Role.DATA_ENGINEER.value: ["data", "数据", "analytics", "分析"],
    Role.UX_DESIGNER.value: ["ux", "design", "设计", "体验", "ui"],
    Role.MARKETING_EXPERT.value: ["marketing", "市场", "营销", "brand", "growth"],
    Role.ENGINEER.value: ["engineer", "develop", "开发", "工程", "后端", "前端", "技术"],
    Role.PRODUCT_ARCHITECT.value: ["product", "architect", "产品", "pm", "产品经理", "产品架构"],
    Role.MODERATOR.value: ["moderator", "host", "主持", "协调", "facilitator"],
}


def match_role(role_str: str) -> Role | None:
    """模糊匹配角色名（支持中英文）

    按 _ROLE_KEYWORDS 的迭代顺序检查（特定专业角色优先于 product_architect），
    避免复合角色名（如 "后端架构师"）被错误映射到 product_architect。
    """
    role_lower = role_str.lower()
    for role, keywords in _ROLE_KEYWORDS.items():
        for kw in keywords:
            if kw in role_lower:
                return Role(role)
    return None
