"""系统级内省路由（ADR-015 Phase 1）。

当前提供：
- GET /system/prompts/snapshot — prompt 源文件版本快照，
  供 eval_v2 将每次评估结果绑定到精确的 prompt 版本。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])

# backend/ 目录（app/routers/system.py → parents[2]）
_BACKEND_ROOT = Path(__file__).resolve().parents[2]
# Git 仓库根目录（backend 的上一级）；Docker 镜像内可能不存在 .git
_REPO_ROOT = _BACKEND_ROOT.parent

# Prompt 源文件范围（ADR-015 §1）：(逻辑名, 相对 backend/ 的路径)
# 注意：核心 prompt 模板已迁移至 conclave_core/prompts.py
# （app/agents/prompts.py 仅为 re-export 入口），必须纳入快照范围。
PROMPT_SOURCE_FILES: tuple[tuple[str, str], ...] = (
    ("conclave_core.prompts", "conclave_core/prompts.py"),
    ("orchestrator.system_prompt", "app/orchestrator/system_prompt.py"),
    ("agents.role_templates", "app/agents/role_templates.py"),
    ("agents.compute", "app/agents/compute.py"),
    ("orchestrator.stage_runners", "app/orchestrator/stage_runners.py"),
    ("orchestrator.borrow_helpers", "app/orchestrator/borrow_helpers.py"),
)

# git 命令超时（秒）：大仓库下 git status 可能较慢，5s 足够且防止端点挂起
_GIT_TIMEOUT_SECONDS = 5.0


def hash_prompt_file(path: Path) -> dict[str, Any]:
    """计算单个 prompt 文件的 sha256 hash 与字节长度。

    文件缺失时返回 {"missing": True, ...}，保证快照结构在文件缺失时仍稳定。
    """
    if not path.is_file():
        return {"hash": "", "length": 0, "missing": True}
    data = path.read_bytes()
    return {
        "hash": "sha256:" + hashlib.sha256(data).hexdigest(),
        "length": len(data),
    }


def compute_snapshot_id(prompts: dict[str, dict[str, Any]]) -> str:
    """将各 prompt 文件 hash 聚合为整体 snapshot_id。

    按逻辑名排序后摘要，保证与 dict 遍历顺序无关（幂等）。
    """
    digest = hashlib.sha256()
    for name in sorted(prompts):
        digest.update(f"{name}:{prompts[name].get('hash', '')}\n".encode())
    return "sha256:" + digest.hexdigest()


async def _run_git(*args: str) -> str | None:
    """best-effort 执行 git 命令，返回去除首尾空白的 stdout；任何失败返回 None。

    超时或失败时主动 kill 子进程，避免泄漏。
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(_REPO_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        # git 不存在（如精简容器镜像）
        return None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_GIT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        with contextlib.suppress(ProcessLookupError):
            await proc.wait()
        return None
    if proc.returncode != 0:
        return None
    return stdout.decode("utf-8", errors="replace").strip() or None


async def _git_info() -> tuple[str, bool]:
    """获取 git commit 与 dirty 状态；容器内/无仓库时返回 ("unknown", False)。"""
    commit = await _run_git("rev-parse", "--short", "HEAD")
    if commit is None:
        return "unknown", False
    status = await _run_git("status", "--porcelain")
    return commit, bool(status)


@router.get("/prompts/snapshot")
async def get_prompt_snapshot() -> dict[str, Any]:
    """获取当前 prompt 源文件快照（ADR-015 Phase 1）。

    返回每个 prompt 源文件的 hash/length、整体 snapshot_id 与 git 版本信息，
    供 eval_v2 将评估结果绑定到精确的 prompt 版本。
    """
    prompts: dict[str, dict[str, Any]] = {}
    for logical_name, rel_path in PROMPT_SOURCE_FILES:
        prompts[logical_name] = hash_prompt_file(_BACKEND_ROOT / rel_path)

    missing = [name for name, info in prompts.items() if info.get("missing")]
    if missing:
        logger.warning("Prompt 快照：文件缺失 %s", missing)

    git_commit, git_dirty = await _git_info()
    return {
        "snapshot_id": compute_snapshot_id(prompts),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_commit": git_commit,
        "git_dirty": git_dirty,
        "prompts": prompts,
    }
