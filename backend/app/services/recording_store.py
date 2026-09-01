# 录制回放文件存储：操作截图落盘 + 保留清理
from __future__ import annotations

import logging
import re
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)

# 文件名只允许安全字符（时间戳 + uuid hex + 扩展名），杜绝路径遍历
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")
# meeting_id 允许 uuid/自定义 id 的安全字符
_SAFE_MEETING_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _root() -> Path:
    """录制根目录（按需创建）。"""
    root = Path(settings.recording_dir)
    root.mkdir(parents=True, exist_ok=True)
    return root


def _meeting_dir(meeting_id: str) -> Path:
    """某会议的录制子目录，校验 meeting_id 合法性。"""
    if not meeting_id or not _SAFE_MEETING_RE.match(meeting_id):
        raise ValueError(f"非法 meeting_id: {meeting_id!r}")
    return _root() / meeting_id


def save_screenshot(meeting_id: str, image_bytes: bytes) -> str | None:
    """将一张截图原子写入磁盘，返回文件名（不含路径）；失败/关闭时返回 None。

    采用临时文件 + rename 原子写，避免回放读到半写文件。
    """
    if not settings.recording_enabled:
        return None
    if not image_bytes:
        return None
    try:
        d = _meeting_dir(meeting_id)
        d.mkdir(parents=True, exist_ok=True)
        filename = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:12]}.png"
        target = d / filename
        tmp = d / f".{filename}.tmp"
        tmp.write_bytes(image_bytes)
        tmp.replace(target)
        return filename
    except Exception as e:
        logger.warning(
            "录制截图落盘失败: meeting_id=%s error=%s: %s",
            meeting_id,
            type(e).__name__,
            str(e)[:200],
        )
        return None


def resolve_path(meeting_id: str, filename: str) -> Path | None:
    """解析并校验截图的磁盘路径；非法/不存在返回 None。

    双重校验：文件名白名单 + resolve 后确认仍在录制根目录内。
    """
    try:
        if not filename or not _SAFE_NAME_RE.match(filename) or filename.startswith("."):
            return None
        d = _meeting_dir(meeting_id)
        root = _root().resolve()
        target = (d / filename).resolve()
        # target 必须严格位于根目录之下（排除 .. 穿越与符号链接逃逸）
        if root != target and root not in target.parents:
            return None
        if not target.is_file():
            return None
        return target
    except (OSError, ValueError):
        return None


def delete_meeting_recordings(meeting_id: str) -> int:
    """删除某会议的全部录制文件，返回删除的文件数。"""
    try:
        d = _meeting_dir(meeting_id)
        if not d.is_dir():
            return 0
        files = [p for p in d.iterdir() if p.is_file()]
        for p in files:
            p.unlink(missing_ok=True)
        shutil.rmtree(d, ignore_errors=True)
        return len(files)
    except (OSError, ValueError):
        return 0


def _dir_latest_mtime(d: Path) -> float:
    """目录的最新活动时间：取目录内所有文件 mtime 的最大值（比目录 mtime 更可靠）。"""
    latest = d.stat().st_mtime
    for p in d.rglob("*"):
        if p.is_file():
            try:
                latest = max(latest, p.stat().st_mtime)
            except OSError:
                continue
    return latest


def cleanup_expired(retention_days: int | None = None) -> int:
    """清理超过保留期的会议录制目录，返回删除的目录数。

    retention_days 为 None 时使用配置 recording_retention_days；<=0 表示不清理。
    """
    days = settings.recording_retention_days if retention_days is None else retention_days
    if days <= 0:
        return 0
    root = _root()
    if not root.is_dir():
        return 0
    cutoff = time.time() - days * 86400
    removed = 0
    for d in root.iterdir():
        if not d.is_dir():
            continue
        try:
            if _dir_latest_mtime(d) < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                removed += 1
        except OSError:
            continue
    if removed:
        logger.info("录制文件保留清理完成：删除 %d 个过期会议录制目录", removed)
    return removed
