"""Produce 阶段辅助函数（从 nodes/produce.py 提取的独立副本）

仅包含 stage_runners.py 需要的函数：
- _emit_progress: 发布 produce 进度事件
- _scan_artifacts: 扫描沙箱工作区收集产出文件

这些函数不依赖 nodes/_helpers，可被 stage_runners.py 直接导入，
消除 stage_runners 对 nodes/produce.py 的反向依赖。

注意：nodes/produce.py 中保留原始定义供内部使用，本文件为独立副本。
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.events import bus, make_event
from app.models import MeetingState


async def _emit_progress(state: MeetingState, step: str, message: str, percent: int = 0) -> None:
    """发送 produce 阶段进度事件到前端"""
    try:
        await bus.publish(
            make_event(
                "produce.progress",
                state.meeting_id,
                {
                    "meeting_id": state.meeting_id,
                    "step": step,
                    "message": message,
                    "percent": percent,
                },
            )
        )
    except Exception:
        pass  # 进度事件失败不影响主流程


def _scan_artifacts(ws_root: Path, meeting_id: str) -> list[dict[str, Any]]:
    """扫描沙箱工作区，收集产出的文件作为附件。

    ws_root 可以是 workspace 根目录（自动找 meeting_id 子目录），
    也可以已经是 meeting_id 子目录（不再重复拼接）。
    """
    attachments: list[dict[str, Any]] = []
    supported_exts = {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".vue", ".java", ".go", ".rs",
        ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh", ".bat", ".ps1", ".sql",
        ".md", ".txt", ".json", ".csv", ".log", ".pdf", ".doc", ".docx",
        ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
    }
    supported_noext = {"Dockerfile", "Makefile", "README", "LICENSE", ".env", ".gitignore"}

    if ws_root.name == meeting_id and ws_root.exists() and ws_root.is_dir():
        scan_dir = ws_root
    else:
        meeting_dir = ws_root / meeting_id
        scan_dir = meeting_dir if meeting_dir.exists() and meeting_dir.is_dir() else ws_root

    if not scan_dir.exists():
        return attachments

    for f in sorted(scan_dir.iterdir()):
        if not f.is_file():
            continue
        is_supported = (
            f.suffix.lower() in supported_exts
            or f.name in supported_noext
            or (not f.suffix and f.name.startswith("Dockerfile"))
        )
        if not is_supported:
            continue
        try:
            stat = f.stat()
        except OSError:
            continue
        if ws_root.name == meeting_id:
            rel_path = f"{meeting_id}/{f.name}"
        elif (ws_root / meeting_id).exists():
            rel_path = f"{meeting_id}/{f.name}"
        else:
            rel_path = f.name
        attachments.append({
            "filename": f.name,
            "path": rel_path,
            "size": stat.st_size,
            "ext": f.suffix.lower().lstrip(".") if f.suffix else "",
            "meeting_id": meeting_id,
        })
    return attachments
