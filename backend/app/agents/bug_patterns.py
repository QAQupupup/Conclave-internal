"""经验库加载器：加载bug_patterns.yaml并格式化为LLM可读文本"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

_PATTERNS_FILE = Path(__file__).resolve().parent.parent / "prompts" / "bug_patterns.yaml"


@lru_cache(maxsize=1)
def load_bug_patterns() -> dict[str, Any]:
    """加载bug_patterns.yaml，返回原始dict（带缓存）"""
    if not _PATTERNS_FILE.exists():
        return {"version": 0, "python_fastapi": [], "docker_deployment": [], "frontend_react": [], "architecture": []}
    with open(_PATTERNS_FILE, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def format_bug_patterns_for_prompt() -> str:
    """将经验库格式化为可注入LLM prompt的文本块"""
    data = load_bug_patterns()
    sections = []

    category_titles = {
        "python_fastapi": "Python/FastAPI 常见错误",
        "docker_deployment": "Docker/部署常见错误",
        "frontend_react": "前端/React常见错误",
        "architecture": "架构/设计问题",
    }

    for cat_key, title in category_titles.items():
        items = data.get(cat_key, [])
        if not items:
            continue
        lines = [f"### {title}"]
        for item in items:
            severity = item.get("severity", "medium")
            sev_mark = (
                "🔴"
                if severity == "critical"
                else "🟠"
                if severity == "high"
                else "🟡"
                if severity == "medium"
                else "⚪"
            )
            pattern = item.get("pattern", "")
            fix = item.get("fix", "")
            lines.append(f"{sev_mark} **{item.get('name', '')}** (ID:{item.get('id', '')}, {severity})")
            lines.append(f"   - 问题: {pattern}")
            lines.append(f"   - 修复: {fix}")
            if item.get("example_bad"):
                lines.append(f"   - ❌ 错误: {item['example_bad']}")
            if item.get("example_good"):
                lines.append(f"   - ✅ 正确: {item['example_good']}")
        sections.append("\n".join(lines))

    review_list = data.get("review_checklist", [])
    if review_list:
        lines = ["### 代码自查清单（生成后逐项检查）"]
        for i, item in enumerate(review_list, 1):
            lines.append(f"{i}. {item}")
        sections.append("\n".join(lines))

    return "\n\n".join(sections)


def append_bug_pattern(category: str, pattern: dict[str, Any]) -> None:
    """向经验库追加新的bug模式（运行时动态添加，用于BugFix循环后沉淀经验）"""
    data = load_bug_patterns()
    # 清除缓存以重新加载
    load_bug_patterns.cache_clear()

    if category not in data:
        data[category] = []

    # 检查是否已存在相同模式
    existing_ids = {p.get("id") for p in data[category]}
    if pattern.get("id") not in existing_ids:
        data[category].append(pattern)
        # 追加到YAML文件
        try:
            with open(_PATTERNS_FILE, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
        except Exception:
            pass  # 文件写入失败不影响主流程
    load_bug_patterns.cache_clear()
