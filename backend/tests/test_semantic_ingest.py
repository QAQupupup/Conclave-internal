# 仓库级语义摄入测试（ADR-018 Phase B）
# 验证真实函数：check_ingest_budget / _workspace_lock / ingest_repo_semantic
# 以及路由层 _build_semantic_index / _semantic_index_status 的降级与透传行为。
# 覆盖正向 + 边界（空仓库/分批）+ 异常（配额超限/语义层不可用/索引失败降级）+ 并发（D12 串行锁）。
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from app.core.exceptions import QuotaExceededError
from app.rag import semantic_ingest
from app.rag.code_to_text import FileDocument
from app.routers import code as code_router


class FakeIndex:
    """LightRAGIndex 测试替身：记录调用，不触达 Qdrant/LLM。"""

    def __init__(self, workspace: str = "0:mtg-m1", insert_delay: float = 0.0) -> None:
        self.workspace = workspace
        self.initialized = 0
        self.closed = 0
        self.calls: list[tuple[list[str], list[str]]] = []
        self.progress_queries: list[str | None] = []
        self._insert_delay = insert_delay
        self._active = 0
        self.max_active = 0
        self.progress_result: dict[str, Any] = {"status_counts": {"processed": 2}, "documents": []}

    async def initialize(self) -> None:
        self.initialized += 1

    async def insert_texts(
        self,
        texts: list[str],
        ids: list[str] | None = None,
        file_paths: list[str] | None = None,
        track_id: str | None = None,
    ) -> str:
        self._active += 1
        self.max_active = max(self.max_active, self._active)
        try:
            if self._insert_delay:
                await asyncio.sleep(self._insert_delay)
            self.calls.append((list(texts), list(file_paths or [])))
            return f"track-{len(self.calls)}"
        finally:
            self._active -= 1

    async def get_progress(self, track_id: str | None = None) -> dict[str, Any]:
        self.progress_queries.append(track_id)
        return self.progress_result

    async def close(self) -> None:
        self.closed += 1


def _build_repo(root: Path, count: int) -> None:
    """造 N 个 .md 文件（走 plain 路径，不依赖 tree-sitter）。"""
    for i in range(count):
        (root / f"f{i}.md").write_text(f"# 文档 {i}\n内容 {i}\n", encoding="utf-8")


def _patch_index(monkeypatch: pytest.MonkeyPatch, index: FakeIndex | None) -> None:
    def _factory(_tenant_id: int, **_kwargs: Any) -> FakeIndex | None:
        return index

    monkeypatch.setattr(semantic_ingest, "get_semantic_index", _factory)


# ---------------------------------------------------------------------------
# check_ingest_budget：配额护栏（D8）
# ---------------------------------------------------------------------------


class TestCheckIngestBudget:
    def test_within_budget_passes(self) -> None:
        docs = [FileDocument(rel_path=f"f{i}.md", category="plain", text="x" * 10) for i in range(3)]
        semantic_ingest.check_ingest_budget(docs)  # 不抛错即通过

    def test_empty_docs_pass(self) -> None:
        semantic_ingest.check_ingest_budget([])

    def test_exceeds_max_docs_raises_quota(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非正向：文档数超限 → QuotaExceededError（全局处理器转 429）。"""
        monkeypatch.setattr(semantic_ingest, "MAX_INGEST_DOCS", 2)
        docs = [FileDocument(rel_path=f"f{i}.md", category="plain", text="x") for i in range(3)]
        with pytest.raises(QuotaExceededError, match="文档数预算"):
            semantic_ingest.check_ingest_budget(docs)

    def test_exceeds_max_chars_raises_quota(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非正向：字符数超限 → QuotaExceededError。"""
        monkeypatch.setattr(semantic_ingest, "MAX_INGEST_CHARS", 100)
        docs = [FileDocument(rel_path="big.md", category="plain", text="x" * 200)]
        with pytest.raises(QuotaExceededError, match="字符数预算"):
            semantic_ingest.check_ingest_budget(docs)


# ---------------------------------------------------------------------------
# _workspace_lock：D12 串行锁注册表
# ---------------------------------------------------------------------------


class TestWorkspaceLock:
    def test_same_workspace_same_lock(self) -> None:
        a = semantic_ingest._workspace_lock("0:mtg-lock-a")
        b = semantic_ingest._workspace_lock("0:mtg-lock-a")
        assert a is b

    def test_different_workspace_different_lock(self) -> None:
        a = semantic_ingest._workspace_lock("0:mtg-lock-b")
        b = semantic_ingest._workspace_lock("0:mtg-lock-c")
        assert a is not b


# ---------------------------------------------------------------------------
# ingest_repo_semantic：编排主流程
# ---------------------------------------------------------------------------


class TestIngestRepoSemantic:
    async def test_degrades_when_semantic_layer_unavailable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """非正向：语义层不可用 → enabled=False，不抛错不阻断。"""
        _patch_index(monkeypatch, None)
        _build_repo(tmp_path, 2)
        result = await semantic_ingest.ingest_repo_semantic(tmp_path, meeting_id="m1", tenant_id=0)
        assert result["enabled"] is False
        assert result["reason"] == "semantic_layer_unavailable"
        assert result["docs_ingested"] == 0

    async def test_empty_repo_returns_zero_batches(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """边界：仓库无三路范围内文件 → 0 文档 0 批次，不调 insert。"""
        index = FakeIndex()
        _patch_index(monkeypatch, index)
        (tmp_path / "binary.bin").write_bytes(b"\x00\x01")
        result = await semantic_ingest.ingest_repo_semantic(tmp_path, meeting_id="m1", tenant_id=0)
        assert result["enabled"] is True
        assert result["workspace"] == "0:mtg-m1"
        assert result["docs_ingested"] == 0
        assert result["batches"] == 0
        assert result["track_ids"] == []
        assert index.calls == []

    async def test_batches_docs_and_returns_track_ids(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """正向：3 篇文档按 BATCH_SIZE=2 分 2 批，file_paths 与文本一一对应。"""
        index = FakeIndex()
        _patch_index(monkeypatch, index)
        monkeypatch.setattr(semantic_ingest, "BATCH_SIZE", 2)
        _build_repo(tmp_path, 3)

        result = await semantic_ingest.ingest_repo_semantic(tmp_path, meeting_id="m1", tenant_id=0)

        assert result["enabled"] is True
        assert result["docs_ingested"] == 3
        assert result["batches"] == 2
        assert result["track_ids"] == ["track-1", "track-2"]
        # 初始化一次、用毕关闭一次
        assert index.initialized == 1
        assert index.closed == 1
        # 批次切分：2 + 1
        assert [len(texts) for texts, _ in index.calls] == [2, 1]
        # file_paths 与文本对应且为仓库相对路径
        all_paths = [p for _, paths in index.calls for p in paths]
        assert sorted(all_paths) == ["f0.md", "f1.md", "f2.md"]
        first_texts = index.calls[0][0]
        assert all("[文件]" in t for t in first_texts)

    async def test_quota_exceeded_before_any_insert(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """非正向：超预算在摄入前拦截，索引不被初始化。"""
        index = FakeIndex()
        _patch_index(monkeypatch, index)
        monkeypatch.setattr(semantic_ingest, "MAX_INGEST_DOCS", 1)
        _build_repo(tmp_path, 3)

        with pytest.raises(QuotaExceededError):
            await semantic_ingest.ingest_repo_semantic(tmp_path, meeting_id="m1", tenant_id=0)
        assert index.calls == []
        assert index.initialized == 0

    async def test_same_workspace_serialized_d12(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """非正向（并发）：同 workspace 两次摄入必须串行，不得并发 insert。"""
        index = FakeIndex(insert_delay=0.05)
        _patch_index(monkeypatch, index)
        _build_repo(tmp_path, 2)

        await asyncio.gather(
            semantic_ingest.ingest_repo_semantic(tmp_path, meeting_id="m1", tenant_id=0),
            semantic_ingest.ingest_repo_semantic(tmp_path, meeting_id="m1", tenant_id=0),
        )
        assert index.max_active == 1  # 串行：任一时刻只有一个 insert 在跑
        assert len(index.calls) == 2  # 两次摄入各 1 批 × 2 篇（内容哈希去重由上游承担）
        assert all(len(texts) == 2 for texts, _ in index.calls)


# ---------------------------------------------------------------------------
# 路由层：_build_semantic_index 降级语义 + _semantic_index_status 透传
# ---------------------------------------------------------------------------


class TestBuildSemanticIndexHelper:
    async def test_quota_error_propagates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """非正向：配额超限不被吞成"可重试失败"，上抛由全局处理器转 429。"""

        async def _raise(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise QuotaExceededError("超预算")

        monkeypatch.setattr("app.rag.semantic_ingest.ingest_repo_semantic", _raise)
        with pytest.raises(QuotaExceededError):
            await code_router._build_semantic_index(tmp_path, "m1")

    async def test_other_errors_degrade_not_block(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """非正向：一般异常降级为 enabled=False，不阻断导入。"""

        async def _raise(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("qdrant down")

        monkeypatch.setattr("app.rag.semantic_ingest.ingest_repo_semantic", _raise)
        result = await code_router._build_semantic_index(tmp_path, "m1")
        assert result["enabled"] is False
        assert "RuntimeError" in result["reason"]
        assert result["docs_ingested"] == 0

    async def test_success_passthrough(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        async def _ok(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            return {"enabled": True, "workspace": "0:mtg-m1", "docs_ingested": 3, "batches": 1, "track_ids": ["t1"]}

        monkeypatch.setattr("app.rag.semantic_ingest.ingest_repo_semantic", _ok)
        result = await code_router._build_semantic_index(tmp_path, "m1")
        assert result["enabled"] is True
        assert result["docs_ingested"] == 3


class TestSemanticIndexStatus:
    @pytest.fixture(autouse=True)
    def _patched_meeting_ownership(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """隔离会议归属校验（依赖 DB），聚焦验证进度查询逻辑。"""

        async def _noop(_meeting_id: str | None = None) -> None:
            return None

        monkeypatch.setattr(code_router, "_ensure_meeting_owned", _noop)

    async def test_degrades_when_layer_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非正向：语义层不可用 → enabled=False（降级语义，非错误）。"""
        monkeypatch.setattr("app.rag.lightrag_adapter.get_semantic_index", lambda *a, **k: None)
        resp = await code_router.code_index_status("m1", track_id=None)
        assert resp["enabled"] is False
        assert resp["reason"] == "semantic_layer_unavailable"
        assert resp["status_counts"] == {}
        assert resp["documents"] == []

    async def test_returns_progress_and_closes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """正向：透传 get_progress 结果，查询后关闭索引，track_id 传达到适配层。"""
        index = FakeIndex()
        index.progress_result = {
            "status_counts": {"pending": 1, "processed": 2},
            "documents": [{"file_path": "f0.md", "status": "processed"}],
        }
        monkeypatch.setattr("app.rag.lightrag_adapter.get_semantic_index", lambda *a, **k: index)

        resp = await code_router.code_index_status("m1", track_id="track-1")

        assert resp["enabled"] is True
        assert resp["workspace"] == "0:mtg-m1"
        assert resp["status_counts"] == {"pending": 1, "processed": 2}
        assert resp["documents"] == [{"file_path": "f0.md", "status": "processed"}]
        assert index.progress_queries == ["track-1"]
        assert index.initialized == 1
        assert index.closed == 1

    async def test_progress_error_degrades_and_closes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """非正向：查询异常降级为 enabled=False（非 500），且索引仍被关闭。"""
        index = FakeIndex()

        async def _fail(_track_id: str | None = None) -> dict[str, Any]:
            raise RuntimeError("doc_status storage down")

        index.get_progress = _fail  # type: ignore[method-assign]
        monkeypatch.setattr("app.rag.lightrag_adapter.get_semantic_index", lambda *a, **k: index)

        resp = await code_router.code_index_status("m1", track_id=None)
        assert resp["enabled"] is False
        assert "RuntimeError" in resp["reason"]
        assert resp["status_counts"] == {}
        assert index.closed == 1
