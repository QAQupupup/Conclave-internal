# 会议宪章：不可变锚点 + 漂移检查 + 流程裁剪
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

# 约束文件路径（可通过环境变量覆盖）
_CONSTRAINTS_FILE = os.environ.get(
    "CONCLAVE_CONSTRAINTS_FILE",
    "/workspace/constraints.yaml",
)

# 文件安全限制
_MAX_FILE_SIZE = 1 * 1024 * 1024  # 1MB
_MAX_CONSTRAINT_TEXT_LENGTH = 2000  # 单条约束最大长度
_MAX_TOTAL_CONSTRAINTS = 50  # 总约束数量上限


def _load_constraints_from_file() -> list[str]:
    """从 YAML 文件动态加载约束（安全校验）

    安全措施：
    1. 文件大小限制（1MB）
    2. 仅解析 YAML，不执行任何代码
    3. 校验数据类型和长度
    4. 脱敏处理（移除潜在的注入模式）
    5. 失败时回退到内置默认约束
    """
    try:
        file_path = Path(_CONSTRAINTS_FILE)
        if not file_path.exists():
            return DEFAULT_CONSTRAINTS

        # 1. 文件大小检查
        if file_path.stat().st_size > _MAX_FILE_SIZE:
            return DEFAULT_CONSTRAINTS

        # 2. 仅读取和解析 YAML（不执行代码）
        with open(file_path, encoding="utf-8") as f:
            raw = f.read()

        # 3. 脱敏：移除潜在的模板注入模式
        raw = re.sub(r"\{\{.*?\}\}", "[FILTERED]", raw)
        raw = re.sub(r"\{\%.*?\%\}", "[FILTERED]", raw)
        raw = re.sub(r"__import__|exec\(|eval\(|compile\(", "[FILTERED]", raw)

        data = yaml.safe_load(raw)  # safe_load 不执行任意 Python 代码

        if not isinstance(data, dict):
            return DEFAULT_CONSTRAINTS

        constraints_data = data.get("constraints", [])
        if not isinstance(constraints_data, list):
            return DEFAULT_CONSTRAINTS

        # 4. 提取和校验每条约束
        result: list[str] = []
        for item in constraints_data[:_MAX_TOTAL_CONSTRAINTS]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "")).strip()
            if not text or len(text) > _MAX_CONSTRAINT_TEXT_LENGTH:
                continue
            result.append(text)

        return result if result else DEFAULT_CONSTRAINTS

    except Exception:
        # 任何异常都回退到默认约束，保证系统可用性
        return DEFAULT_CONSTRAINTS


# 系统预设行为约束（clarify 阶段构造 charter 时写入，可追加）
DEFAULT_CONSTRAINTS: list[str] = [
    "只讨论与议题直接相关的内容",
    "不扩展到议题边界外的领域",
    "不重复已裁决的冲突",
    "借调需经三问法裁决",
    "每个 agent 发言必须与当前阶段目标一致",
]


class DriftCheck(BaseModel):
    """漂移检查结果"""

    is_drift: bool = False
    reason: str = ""
    severity: str = "none"  # "none" | "minor" | "major"


class MeetingCharter(BaseModel):
    """会议宪章：不可变锚点，每阶段注入 agent prompt 防止漂移

    - original_topic：用户原始输入，不可篡改
    - clarified_topic：clarify 阶段 LLM 澄清后的议题
    - meeting_goal：会议目标
    - scope：议题边界短语（clarify 阶段确定）
    - constraints：行为约束（系统预设 + 可追加）
    - forbidden_topics：禁止话题（防漂移）
    - borrow_history：已拒绝/批准的借调角色记录（防重复借调）
    """

    meeting_id: str
    original_topic: str
    clarified_topic: str = ""
    meeting_goal: str = ""
    scope: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    forbidden_topics: list[str] = Field(default_factory=list)
    borrow_history: list[str] = Field(default_factory=list)


def build_charter_from_clarify(
    meeting_id: str,
    original_topic: str,
    clarified_topic: str,
    key_questions: list[str] | None = None,
    extra_constraints: list[str] | None = None,
    forbidden_topics: list[str] | None = None,
) -> MeetingCharter:
    """clarify_node 调用：根据澄清结果构造会议宪章

    - meeting_goal 由澄清议题推导
    - scope 用关键问题 + 澄清议题作为边界短语
    - constraints 注入系统预设约束，可追加
    """
    key_questions = key_questions or []
    scope: list[str] = []
    if clarified_topic:
        scope.append(clarified_topic)
    scope.extend(q for q in key_questions if q)

    goal = f"针对「{clarified_topic or original_topic}」达成决策共识并产出 PRD 与 OpenAPI"

    constraints = _load_constraints_from_file()
    if extra_constraints:
        constraints.extend(extra_constraints)

    return MeetingCharter(
        meeting_id=meeting_id,
        original_topic=original_topic,
        clarified_topic=clarified_topic or original_topic,
        meeting_goal=goal,
        scope=scope,
        constraints=constraints,
        forbidden_topics=forbidden_topics or [],
        borrow_history=[],
    )
