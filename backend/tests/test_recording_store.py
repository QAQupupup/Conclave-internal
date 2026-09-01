# 录制回放文件存储单元测试：覆盖落盘、路径穿越防护、删除、保留清理
from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

from app.services import recording_store as rs


@pytest.fixture
def recording_env(monkeypatch, tmp_path):
    """注入假的 settings，将录制根目录指向临时目录，并默认开启落盘。"""
    fake = SimpleNamespace(
        recording_enabled=True,
        recording_dir=str(tmp_path),
        recording_retention_days=7,
        recording_max_screenshot_bytes=1024 * 1024,
    )
    monkeypatch.setattr(rs, "settings", fake)
    return tmp_path


def test_save_screenshot_writes_file(recording_env):
    name = rs.save_screenshot("meeting-1", b"\x89PNG-fake-bytes")
    assert name is not None
    assert name.endswith(".png")
    assert (recording_env / "meeting-1" / name).is_file()


def test_save_screenshot_returns_none_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setattr(
        rs,
        "settings",
        SimpleNamespace(
            recording_enabled=False,
            recording_dir=str(tmp_path),
            recording_retention_days=7,
            recording_max_screenshot_bytes=1024,
        ),
    )
    assert rs.save_screenshot("meeting-1", b"x") is None


def test_save_screenshot_returns_none_for_empty(recording_env):
    assert rs.save_screenshot("meeting-1", b"") is None


def test_resolve_path_valid(recording_env):
    name = rs.save_screenshot("meeting-1", b"img")
    assert name is not None
    p = rs.resolve_path("meeting-1", name)
    assert p is not None
    assert p.is_file()


def test_resolve_path_rejects_traversal(recording_env):
    # 文件名含 ".." 与 "/" 都必须被白名单拦截，杜绝路径穿越
    assert rs.resolve_path("meeting-1", "../evil.png") is None
    assert rs.resolve_path("meeting-1", "a/b.png") is None


def test_resolve_path_rejects_missing(recording_env):
    assert rs.resolve_path("meeting-1", "nope.png") is None


def test_resolve_path_rejects_dotfile(recording_env):
    assert rs.resolve_path("meeting-1", ".hidden.png") is None


def test_resolve_path_rejects_bad_meeting_id(recording_env):
    # meeting_id 含 ".." 或 "/" 被 _meeting_dir 拒绝，抛 ValueError 后由 resolve_path 吞掉返回 None
    assert rs.resolve_path("../escape", "a.png") is None
    assert rs.resolve_path("a/b", "a.png") is None


def test_delete_meeting_recordings(recording_env):
    rs.save_screenshot("meeting-1", b"a")
    rs.save_screenshot("meeting-1", b"b")
    assert rs.delete_meeting_recordings("meeting-1") == 2
    assert not (recording_env / "meeting-1").exists()


def test_delete_meeting_recordings_missing_dir(recording_env):
    assert rs.delete_meeting_recordings("ghost") == 0


def test_cleanup_expired_disabled(recording_env):
    # <=0 表示不自动清理
    assert rs.cleanup_expired(retention_days=0) == 0
    assert rs.cleanup_expired(retention_days=-3) == 0


def test_cleanup_expired_removes_old(recording_env):
    rs.save_screenshot("old-meeting", b"x")
    old = time.time() - 3 * 86400
    d = recording_env / "old-meeting"
    # 同时回拨目录与文件的 mtime，确保 _dir_latest_mtime 低于 cutoff
    os.utime(d, (old, old))
    for p in d.iterdir():
        os.utime(p, (old, old))
    removed = rs.cleanup_expired(retention_days=1)
    assert removed == 1
    assert not d.exists()
