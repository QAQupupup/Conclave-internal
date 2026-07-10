"""Conclave Agent Skill 系统

Skill 是可被 Agent 动态加载的知识/规范/偏好模块。
每个 Skill 是一个 YAML 文件，包含元数据（触发条件）和 prompt 内容（注入片段）。

与硬编码 prompt 的区别：
- Skills 按需加载，不相关的 Skill 不会占用 token
- 用户可以创建自定义 Skill 来定制行为
- Skills 可以组合叠加（一个任务可能同时激活 design + code_review + communication 多个 Skill）
- Skills 与 bug_patterns 互补：bug_patterns 是"不要犯的错"（负面清单），Skills 是"应该怎么做"（正面指南）

Skill 文件位置：backend/app/skills/*.yaml
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass
class Skill:
    """一个 Skill 的结构化表示"""
    id: str                           # 唯一ID，如 "ui_design_system"
    name: str                         # 人类可读名称
    description: str                  # 简介
    version: int = 1
    type: str = "guideline"           # guideline / constraint / style / checklist
    applies_to: dict[str, Any] = field(default_factory=lambda: {
        "stages": [],       # 生效阶段：["produce", "intra_team", ...]，空=全部
        "deliverable_types": [],  # 生效产出类型：["deployable_service", ...]，空=全部
        "roles": [],        # 生效角色：["engineer", "ux_designer", ...]，空=全部
        "complexity": [],   # 生效复杂度：["simple", "standard", "full"]，空=全部
    })
    priority: int = 50                # 加载优先级（0-100），高优先级先注入
    prompt: str = ""                  # 注入到 LLM prompt 的内容
    tags: list[str] = field(default_factory=list)

    def matches(
        self,
        stage: str = "",
        deliverable_type: str = "",
        role: str = "",
        complexity: str = "",
    ) -> bool:
        """判断此 Skill 是否在给定上下文中激活"""
        a = self.applies_to
        if a.get("stages") and stage and stage not in a["stages"]:
            return False
        if a.get("deliverable_types") and deliverable_type and deliverable_type not in a["deliverable_types"]:
            return False
        if a.get("roles") and role and role not in a["roles"]:
            return False
        if a.get("complexity") and complexity and complexity not in a["complexity"]:
            return False
        return True


@lru_cache(maxsize=4)
def load_all_skills() -> list[Skill]:
    """加载 skills/ 目录下所有 Skill 文件（带缓存）"""
    skills: list[Skill] = []
    if not SKILLS_DIR.exists():
        return skills
    for f in sorted(SKILLS_DIR.glob("*.yaml")):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            if not data.get("id") or not data.get("prompt"):
                continue
            skills.append(Skill(
                id=data["id"],
                name=data.get("name", data["id"]),
                description=data.get("description", ""),
                version=data.get("version", 1),
                type=data.get("type", "guideline"),
                applies_to=data.get("applies_to", {}),
                priority=data.get("priority", 50),
                prompt=data["prompt"],
                tags=data.get("tags", []),
            ))
        except Exception as e:
            import logging
            logging.getLogger("skills").warning(f"加载 Skill 文件失败 {f.name}: {e}")
    # 按优先级排序
    skills.sort(key=lambda s: -s.priority)
    return skills


def get_active_skills(
    stage: str = "",
    deliverable_type: str = "",
    role: str = "",
    complexity: str = "",
) -> list[Skill]:
    """获取在给定上下文中激活的所有 Skill，按优先级排序"""
    all_skills = load_all_skills()
    return [
        s for s in all_skills
        if s.matches(stage=stage, deliverable_type=deliverable_type, role=role, complexity=complexity)
    ]


def format_skills_for_prompt(
    stage: str = "",
    deliverable_type: str = "",
    role: str = "",
    complexity: str = "",
) -> str:
    """将激活的 Skills 格式化为 prompt 注入文本块"""
    active = get_active_skills(stage=stage, deliverable_type=deliverable_type, role=role, complexity=complexity)
    if not active:
        return ""
    sections = []
    for s in active:
        header = f"## 【Skill: {s.name}】"
        if s.description:
            header += f" — {s.description}"
        sections.append(f"{header}\n{s.prompt}")
    return "\n\n".join(sections)


def reload_skills() -> None:
    """清除 Skill 缓存（用于运行时更新 Skill 文件后刷新）"""
    load_all_skills.cache_clear()


def list_skills() -> list[dict[str, Any]]:
    """列出所有已加载的 Skill（供API/调试使用）"""
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "type": s.type,
            "version": s.version,
            "priority": s.priority,
            "applies_to": s.applies_to,
            "tags": s.tags,
        }
        for s in load_all_skills()
    ]
