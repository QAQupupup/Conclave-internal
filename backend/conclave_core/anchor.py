# 宪章锚点构造（无副作用，只读 state）
from __future__ import annotations

from app.models import MeetingState
from conclave_core.charter_logic import to_prompt_anchor
from conclave_core.conclusion_logic import get_locked_context


def get_charter_anchor(state: MeetingState) -> str:
    """取会议宪章锚点文本，charter 不存在时返回空串"""
    if state.charter is None:
        return ""
    return to_prompt_anchor(state.charter)


def get_code_anchor(state: MeetingState) -> str:
    """构造已摄入代码仓库的锚点文本，无代码仓库时返回空串。

    [P1 修复] 打通"代码上传 → LLM 感知"：锚点告知各阶段 Agent 会议已导入
    哪些代码、根目录在哪、是否已建索引，并引导用 fs.list/fs.read 取证，
    避免 LLM 对已导入代码零感知、只能靠用户口述或盲探。
    """
    repos = getattr(state, "code_repos", None) or []
    lines: list[str] = []
    for repo in repos:
        name = str(repo.get("name") or repo.get("path") or "").strip()
        if not name:
            continue
        path = str(repo.get("path") or name)
        detail = f"- {name}：根目录 {path}"
        file_count = repo.get("file_count")
        if isinstance(file_count, int) and file_count >= 0:
            detail += f"，{file_count} 个文件"
        detail += "，已建立代码索引" if repo.get("indexed") else "，未建立代码索引"
        lines.append(detail)
    if not lines:
        return ""
    lines.insert(0, "[已导入代码仓库]")
    lines.append("涉及代码的问题，优先用 fs.list/fs.read 浏览、读取对应目录下的文件获取事实，不要凭空猜测代码内容。")
    return "\n".join(lines)


def get_full_anchor(state: MeetingState, stage: str) -> str:
    """构造完整锚点：宪章锚点 + 已锁定结论上下文 + 历史会议引用上下文 + 代码仓库锚点"""
    parts: list[str] = []
    charter_anchor = get_charter_anchor(state)
    if charter_anchor:
        parts.append(charter_anchor)
    locked_context = get_locked_context(state.conclusion_chain, stage)
    if locked_context:
        parts.append(locked_context)
    if state.reference_context:
        parts.append(state.reference_context)
    code_anchor = get_code_anchor(state)
    if code_anchor:
        parts.append(code_anchor)
    return "\n\n".join(parts) if parts else ""
