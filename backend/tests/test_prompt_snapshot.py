"""Prompt 快照端点测试（ADR-015 Phase 1）。

覆盖 GET /system/prompts/snapshot 端点契约与 hash/snapshot_id 纯函数逻辑：
- 正向：端点结构完整、hash 格式正确、幂等
- 非正向：文件缺失边界、hash 变化敏感性、dict 顺序无关性
"""

from __future__ import annotations

import hashlib

from app.routers.system import (
    PROMPT_SOURCE_FILES,
    compute_snapshot_id,
    hash_prompt_file,
)

_EXPECTED_NAMES = {name for name, _ in PROMPT_SOURCE_FILES}


# ---------- 纯函数测试 ----------


def test_hash_prompt_file_matches_sha256(tmp_path):
    """hash_prompt_file 与 hashlib.sha256 对同一内容的结果一致（往返核验）"""
    content = b"SYSTEM PROMPT CONTENT v1"
    f = tmp_path / "prompt.py"
    f.write_bytes(content)

    info = hash_prompt_file(f)

    assert info["hash"] == "sha256:" + hashlib.sha256(content).hexdigest()
    assert info["length"] == len(content)
    assert "missing" not in info


def test_hash_prompt_file_missing(tmp_path):
    """文件缺失时返回 missing 标记而非抛异常（边界）"""
    info = hash_prompt_file(tmp_path / "not_exist.py")
    assert info == {"hash": "", "length": 0, "missing": True}


def test_compute_snapshot_id_deterministic_and_order_free():
    """snapshot_id 与 dict 插入顺序无关（幂等契约）"""
    a = {"x": {"hash": "sha256:1"}, "y": {"hash": "sha256:2"}}
    b = {"y": {"hash": "sha256:2"}, "x": {"hash": "sha256:1"}}
    assert compute_snapshot_id(a) == compute_snapshot_id(b)


def test_compute_snapshot_id_sensitive_to_change():
    """任一文件 hash 变化时 snapshot_id 必须变化（版本绑定核心契约）"""
    base = {"x": {"hash": "sha256:1"}, "y": {"hash": "sha256:2"}}
    changed = {"x": {"hash": "sha256:1"}, "y": {"hash": "sha256:CHANGED"}}
    assert compute_snapshot_id(base) != compute_snapshot_id(changed)


def test_compute_snapshot_id_empty():
    """空快照仍返回合法 sha256 格式（边界）"""
    sid = compute_snapshot_id({})
    assert sid.startswith("sha256:")
    assert len(sid) == len("sha256:") + 64


# ---------- 端点契约测试 ----------


def test_endpoint_returns_full_structure(client):
    """GET /system/prompts/snapshot 返回完整快照结构"""
    resp = client.get("/system/prompts/snapshot")
    assert resp.status_code == 200
    data = resp.json()

    assert data["snapshot_id"].startswith("sha256:")
    assert data["timestamp"]
    assert isinstance(data["git_commit"], str) and data["git_commit"]
    assert isinstance(data["git_dirty"], bool)

    prompts = data["prompts"]
    assert set(prompts.keys()) == _EXPECTED_NAMES
    for name, info in prompts.items():
        assert info["hash"].startswith("sha256:"), f"{name} hash 格式错误"
        assert info["length"] > 0, f"{name} 长度应大于 0（文件应存在）"
        assert not info.get("missing"), f"{name} 不应缺失"


def test_endpoint_idempotent(client):
    """连续两次调用 snapshot_id 与明细一致（幂等）"""
    first = client.get("/system/prompts/snapshot").json()
    second = client.get("/system/prompts/snapshot").json()
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["prompts"] == second["prompts"]
