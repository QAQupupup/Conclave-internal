"""ADR-018 Phase A：LightRAG 适配层单元测试。

覆盖范围（对应 docs/design/adr/018-codebase-understanding-lightrag.md）：
- D3 隔离键构造：项目级/会议级前缀、跨租户区分、路径穿越拒绝（非正向）
- 语义索引可用性判定：Qdrant/LLM/Embedding 缺一即降级（非正向）
- Embedding 包装：维度/模型元数据、租户上下文注入、拒绝无配置静默降级（非正向）
- LLM 包装：D8 温度锁 0.0、system_prompt/history 合并、拒绝 StubLLM（非正向）
- LightRAGIndex 门面：未初始化保护（非正向）、Qdrant 存储接线、委托转发、幂等

不依赖外网 / Qdrant / 真实 LLM：外部依赖全部替换为进程内 fake。
"""

from __future__ import annotations

import os
from typing import Any

import numpy as np
import pytest

from app.agents.llm import StubLLM
from app.config import settings
from app.rag.lightrag_adapter import (
    LightRAGIndex,
    _make_embedding_func,
    _make_llm_func,
    build_workspace_key,
    content_hash_of,
    decode_ingest_path,
    encode_ingest_path,
    get_semantic_index,
    is_semantic_index_available,
    resolve_semantic_tenant_id,
)
from app.rag.store import SiliconFlowEmbedding
from app.tenants.context import get_tenant_id, reset_tenant_ctx, set_tenant_id

# ---------------------------------------------------------------------------
# fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def patch_settings():
    """临时 patch settings 字段，测试后恢复原值。

    settings 为 pydantic BaseSettings，沿用 test_memory.py 的 object.__setattr__ 写法。
    """
    originals: dict[str, Any] = {}

    def _set(**kwargs: Any) -> None:
        for name, value in kwargs.items():
            if name not in originals:
                originals[name] = getattr(settings, name)
            object.__setattr__(settings, name, value)

    yield _set
    for name, value in originals.items():
        object.__setattr__(settings, name, value)


def _patch_embed_config(
    monkeypatch: pytest.MonkeyPatch,
    base: str = "http://embed.local",
    key: str = "sk-emb",
    model: str = "bge-m3",
) -> None:
    """替换 SiliconFlowEmbedding.resolve_config，避免触碰真实配置链路。"""
    monkeypatch.setattr(SiliconFlowEmbedding, "resolve_config", lambda self: (base, key, model))


class _FakeStatusEnum:
    value = "processed"


class _FakeDocProcessingStatus:
    """DocProcessingStatus 测试替身：字段与 _serialize_doc_status 读取面一致。"""

    def __init__(self) -> None:
        self.file_path = "app/main.py"
        self.status = _FakeStatusEnum()
        self.chunks_count = 3
        self.content_length = 120
        self.error_msg = ""
        self.created_at = "2026-09-05T10:00:00"
        self.updated_at = "2026-09-05T10:01:00"


def _install_fake_rag(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """安装 fake LightRAG 类，捕获构造参数与操作记录（不 mock 适配层自身）。"""
    import lightrag as lightrag_module

    state: dict[str, Any] = {"init_count": 0, "ops": [], "kwargs": {}, "doc_pages": [], "query_data_result": {}}

    class _FakeDocStatus:
        async def get_docs_by_track_id(self, track_id: str) -> dict[str, Any]:
            state["ops"].append(("get_docs_by_track_id", track_id))
            return {"doc-1": _FakeDocProcessingStatus()}

        async def get_docs_paginated(
            self, page: int = 1, page_size: int = 50, **_kwargs: Any
        ) -> tuple[list[tuple[str, Any]], int]:
            state["ops"].append(("get_docs_paginated", page, page_size))
            pages: list[list[tuple[str, Any]]] = state["doc_pages"]
            total = sum(len(p) for p in pages)
            items = pages[page - 1] if 0 < page <= len(pages) else []
            return list(items), total

    class _FakeRAG:
        def __init__(self, **kwargs: Any) -> None:
            state["init_count"] += 1
            state["kwargs"] = kwargs
            self.doc_status = _FakeDocStatus()

        async def initialize_storages(self) -> None:
            state["initialized"] = True

        async def finalize_storages(self) -> None:
            state["finalized"] = True

        async def ainsert(
            self,
            texts: list[str],
            ids: list[str] | None = None,
            file_paths: list[str] | None = None,
            track_id: str | None = None,
        ) -> str:
            state["ops"].append(("ainsert", list(texts), ids, file_paths, track_id))
            return track_id or "fake-track-id"

        async def aquery(self, question: str, param: Any = None) -> str:
            state["ops"].append(("aquery", question, param.mode))
            return "fake 答案"

        async def aquery_data(self, question: str, param: Any = None) -> dict[str, Any]:
            state["ops"].append(("aquery_data", question, param.mode, param.enable_rerank))
            return state["query_data_result"]

        async def adelete_by_doc_id(self, doc_id: str) -> None:
            state["ops"].append(("adelete_by_doc_id", doc_id))

        async def get_processing_status(self) -> dict[str, int]:
            state["ops"].append(("get_processing_status",))
            return {"pending": 1, "processed": 2}

    monkeypatch.setattr(lightrag_module, "LightRAG", _FakeRAG)
    return state


# ---------------------------------------------------------------------------
# D3 隔离键
# ---------------------------------------------------------------------------


def test_workspace_key_project_scope() -> None:
    assert build_workspace_key(1, project_id="p-123") == "1:proj-p-123"


def test_workspace_key_meeting_scope() -> None:
    assert build_workspace_key(2, meeting_id="m-456") == "2:mtg-m-456"


def test_workspace_key_project_takes_precedence() -> None:
    """同时提供时 project_id 优先（项目级共享索引是常态路径）。"""
    assert build_workspace_key(1, project_id="p1", meeting_id="m1") == "1:proj-p1"


def test_workspace_key_cross_tenant_distinct() -> None:
    """同一 project_id 在不同租户下必须生成不同键（多租户隔离前提）。"""
    k1 = build_workspace_key(1, project_id="shared-uuid")
    k2 = build_workspace_key(2, project_id="shared-uuid")
    assert k1 != k2


def test_workspace_key_requires_scope() -> None:
    """project_id 与 meeting_id 均未提供 → 提前失败。"""
    with pytest.raises(ValueError, match="至少其一"):
        build_workspace_key(1)


@pytest.mark.parametrize("bad_id", ["a/b", "a\\b", "../evil", "x\\..\\y"])
def test_workspace_key_rejects_path_traversal(bad_id: str) -> None:
    """workspace 键会被用作目录名，路径分隔符/相对路径引用必须拒绝。"""
    with pytest.raises(ValueError, match="workspace"):
        build_workspace_key(1, project_id=bad_id)


# ---------------------------------------------------------------------------
# 可用性判定与降级
# ---------------------------------------------------------------------------


def test_available_when_all_configured(patch_settings) -> None:
    patch_settings(qdrant_url="http://qdrant:6333", llm_api_key="sk-llm", embed_api_key="sk-emb")
    assert is_semantic_index_available() is True


def test_unavailable_without_qdrant(patch_settings) -> None:
    patch_settings(qdrant_url="", llm_api_key="sk-llm", embed_api_key="sk-emb")
    assert is_semantic_index_available() is False


def test_unavailable_without_llm_key(patch_settings) -> None:
    patch_settings(qdrant_url="http://qdrant:6333", llm_api_key="", embed_api_key="sk-emb")
    assert is_semantic_index_available() is False


def test_unavailable_without_embed_key(patch_settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量与 DB 系统配置均无 embed key → 不可用。"""
    patch_settings(qdrant_url="http://qdrant:6333", llm_api_key="sk-llm", embed_api_key="")
    monkeypatch.setattr("app.services.config_service.get_cached_system_settings", lambda: {})
    assert is_semantic_index_available() is False


def test_available_with_db_level_embed_key(patch_settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """环境变量无 key 但管理员在 DB 配置了 embed_api_key → 仍可用。"""
    patch_settings(qdrant_url="http://qdrant:6333", llm_api_key="sk-llm", embed_api_key="")
    monkeypatch.setattr(
        "app.services.config_service.get_cached_system_settings",
        lambda: {"embed_api_key": "sk-db-level"},
    )
    assert is_semantic_index_available() is True


# ---------------------------------------------------------------------------
# 工厂 get_semantic_index
# ---------------------------------------------------------------------------


def test_get_semantic_index_none_when_unavailable(patch_settings) -> None:
    """三要素缺失 → 返回 None，调用方降级纯结构层。"""
    patch_settings(qdrant_url="", llm_api_key="", embed_api_key="")
    assert get_semantic_index(1, project_id="p1") is None


def test_get_semantic_index_returns_uninitialized_index(patch_settings) -> None:
    patch_settings(qdrant_url="http://qdrant:6333", llm_api_key="sk-llm", embed_api_key="sk-emb")
    idx = get_semantic_index(7, project_id="p1")
    assert idx is not None
    assert idx.workspace == "7:proj-p1"
    assert idx.is_ready is False


def test_get_semantic_index_workspace_matches_build_key(patch_settings) -> None:
    """工厂与隔离键构造的一致性（会议级退化路径）。"""
    patch_settings(qdrant_url="http://qdrant:6333", llm_api_key="sk-llm", embed_api_key="sk-emb")
    idx = get_semantic_index(3, meeting_id="m9")
    assert idx is not None
    assert idx.workspace == build_workspace_key(3, meeting_id="m9")


def test_get_semantic_index_requires_scope(patch_settings) -> None:
    patch_settings(qdrant_url="http://qdrant:6333", llm_api_key="sk-llm", embed_api_key="sk-emb")
    with pytest.raises(ValueError):
        get_semantic_index(1)


# ---------------------------------------------------------------------------
# Embedding 包装（D4）
# ---------------------------------------------------------------------------


def test_embedding_func_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_embed_config(monkeypatch)
    ef = _make_embedding_func(1)
    assert ef.embedding_dim == 1024  # bge-m3 固定 1024 维
    assert ef.model_name == "bge-m3"


async def test_embedding_func_returns_ndarray_and_sets_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_embed_config(monkeypatch)
    captured: dict[str, Any] = {}

    async def fake_embed_batch(self: SiliconFlowEmbedding, texts: list[str]) -> list[list[float]]:
        captured["tenant"] = get_tenant_id()
        captured["texts"] = list(texts)
        return [[0.5] * self.dim for _ in texts]

    monkeypatch.setattr(SiliconFlowEmbedding, "embed_batch", fake_embed_batch)

    before = get_tenant_id()
    ef = _make_embedding_func(42)
    result = await ef.func(["文本甲", "文本乙"])

    assert isinstance(result, np.ndarray)
    assert result.shape == (2, 1024)
    assert result.dtype == np.float32
    assert captured["texts"] == ["文本甲", "文本乙"]
    assert captured["tenant"] == 42  # 嵌入调用期间租户上下文已注入
    assert get_tenant_id() == before  # 调用结束后上下文恢复


async def test_embedding_func_rejects_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    """无 base_url/key 时抛错——StubEmbedding 伪向量会污染语义索引，禁止静默降级。"""
    _patch_embed_config(monkeypatch, base="", key="", model="")
    ef = _make_embedding_func(1)
    with pytest.raises(RuntimeError, match="Embedding 未配置"):
        await ef.func(["text"])


async def test_embedding_func_count_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    """嵌入返回数量与输入不一致 → 抛错而非错位入库。"""
    _patch_embed_config(monkeypatch)

    async def short_batch(self: SiliconFlowEmbedding, texts: list[str]) -> list[list[float]]:
        return [[0.1] * self.dim]  # 两条输入只回一条

    monkeypatch.setattr(SiliconFlowEmbedding, "embed_batch", short_batch)
    ef = _make_embedding_func(1)
    with pytest.raises(RuntimeError, match="嵌入数量不匹配"):
        await ef.func(["a", "b"])


# ---------------------------------------------------------------------------
# LLM 包装（D8 温度 0.0）
# ---------------------------------------------------------------------------


class _FakeLLM:
    """捕获 complete_text 调用参数（替换外部 LLM 依赖，非 mock 被测函数）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []

    async def complete_text(self, prompt: str, temperature: float = 0.1) -> str:
        self.calls.append((prompt, temperature))
        return "实体抽取结果"


async def test_llm_func_temperature_locked_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeLLM()
    monkeypatch.setattr("app.agents.llm.get_llm", lambda: fake)
    llm_func = _make_llm_func(None)
    result = await llm_func("抽取实体与关系")
    assert result == "实体抽取结果"
    prompt, temperature = fake.calls[0]
    assert temperature == 0.0  # D8：抽取类调用温度锁 0.0
    assert "抽取实体与关系" in prompt


async def test_llm_func_merges_system_prompt_and_history(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _FakeLLM()
    monkeypatch.setattr("app.agents.llm.get_llm", lambda: fake)
    llm_func = _make_llm_func(None)
    await llm_func(
        "抽取实体",
        system_prompt="你是实体抽取器",
        history_messages=[{"role": "user", "content": "上一轮输入"}],
    )
    prompt, _ = fake.calls[0]
    assert "你是实体抽取器" in prompt
    assert "[历史对话]" in prompt
    assert "user: 上一轮输入" in prompt


async def test_llm_func_rejects_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_llm() 返回 StubLLM 时显式拒绝——桩数据进图谱会污染索引。"""
    monkeypatch.setattr("app.agents.llm.get_llm", lambda: StubLLM())
    llm_func = _make_llm_func(None)
    with pytest.raises(RuntimeError, match="LLM 未配置"):
        await llm_func("抽取实体")


async def test_llm_func_sets_tenant_context(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _TenantSpyLLM:
        async def complete_text(self, prompt: str, temperature: float = 0.1) -> str:
            captured["tenant"] = get_tenant_id()
            return "ok"

    monkeypatch.setattr("app.agents.llm.get_llm", _TenantSpyLLM)
    before = get_tenant_id()
    llm_func = _make_llm_func(9)
    await llm_func("hi")
    assert captured["tenant"] == 9
    assert get_tenant_id() == before


# ---------------------------------------------------------------------------
# LightRAGIndex 门面
# ---------------------------------------------------------------------------


async def test_index_ops_require_initialize() -> None:
    """未 initialize 就调用插入/查询/删除 → 明确报错（防静默空操作）。"""
    idx = LightRAGIndex(workspace="1:proj-x")
    assert idx.is_ready is False
    with pytest.raises(RuntimeError, match="未初始化"):
        await idx.insert_texts(["a"])
    with pytest.raises(RuntimeError, match="未初始化"):
        await idx.query("q")
    with pytest.raises(RuntimeError, match="未初始化"):
        await idx.delete_doc("doc-1")


async def test_index_close_without_initialize_is_noop() -> None:
    idx = LightRAGIndex(workspace="1:proj-x")
    await idx.close()  # 不应抛错
    assert idx.is_ready is False


def test_index_default_working_dir_under_workspace_root(patch_settings, tmp_path) -> None:
    """D10：文件存储默认落 workspace_root/lightrag。"""
    patch_settings(workspace_root=str(tmp_path))
    idx = LightRAGIndex(workspace="1:proj-x")
    assert idx._working_dir == str(tmp_path / "lightrag")


def test_index_explicit_working_dir(tmp_path) -> None:
    idx = LightRAGIndex(workspace="1:proj-x", working_dir=str(tmp_path / "custom"))
    assert idx._working_dir == str(tmp_path / "custom")


async def test_initialize_wires_qdrant_storage_and_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """initialize 以 Qdrant 向量存储 + D3 隔离键构造 LightRAG，且幂等。"""
    state = _install_fake_rag(monkeypatch)
    _patch_embed_config(monkeypatch)

    idx = LightRAGIndex(workspace="5:proj-abc", working_dir=str(tmp_path))
    await idx.initialize()

    assert idx.is_ready is True
    assert state["initialized"] is True
    kwargs = state["kwargs"]
    assert kwargs["workspace"] == "5:proj-abc"
    assert kwargs["vector_storage"] == "QdrantVectorDBStorage"
    assert kwargs["working_dir"] == str(tmp_path)

    # 幂等：二次 initialize 不重建实例
    await idx.initialize()
    assert state["init_count"] == 1


async def test_initialize_syncs_qdrant_url_from_settings(
    monkeypatch: pytest.MonkeyPatch, patch_settings, tmp_path
) -> None:
    state = _install_fake_rag(monkeypatch)
    _patch_embed_config(monkeypatch)
    patch_settings(qdrant_url="http://qdrant.internal:6333")
    monkeypatch.delenv("QDRANT_URL", raising=False)

    idx = LightRAGIndex(workspace="1:proj-x", working_dir=str(tmp_path))
    await idx.initialize()

    assert os.environ["QDRANT_URL"] == "http://qdrant.internal:6333"
    assert state["init_count"] == 1


async def test_index_delegates_ops_to_rag(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """插入/查询/删除正确委托 LightRAG，查询默认 mix 双层检索。

    Phase B 扩展：insert_texts 透传 file_paths 并返回 track_id（批次凭据）。
    """
    state = _install_fake_rag(monkeypatch)
    _patch_embed_config(monkeypatch)

    idx = LightRAGIndex(workspace="1:proj-x", working_dir=str(tmp_path))
    await idx.initialize()

    track = await idx.insert_texts(["t1", "t2"], ids=["id1", "id2"], file_paths=["a.py", "b.py"])
    answer = await idx.query("这个仓库是干什么的？")
    await idx.delete_doc("doc-9")
    await idx.close()

    assert track == "fake-track-id"
    assert answer == "fake 答案"
    ops = state["ops"]
    assert ops[0] == ("ainsert", ["t1", "t2"], ["id1", "id2"], ["a.py", "b.py"], None)
    assert ops[1][0] == "aquery"
    assert ops[1][2] == "mix"  # 默认双层检索模式
    assert ops[2] == ("adelete_by_doc_id", "doc-9")
    assert state["finalized"] is True
    assert idx.is_ready is False


async def test_get_progress_counts_and_batch_details(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """DocStatus 进度查询（Phase B）：状态计数 + 按 track_id 的逐文档序列化明细。"""
    state = _install_fake_rag(monkeypatch)
    _patch_embed_config(monkeypatch)

    idx = LightRAGIndex(workspace="1:proj-x", working_dir=str(tmp_path))
    await idx.initialize()
    try:
        # 不传 track_id：只有计数，无逐文档明细（避免大仓库全量枚举）
        overview = await idx.get_progress()
        assert overview["status_counts"] == {"pending": 1, "processed": 2}
        assert overview["documents"] == []

        # 传 track_id：返回该批次逐文档状态，枚举值序列化为字符串
        detail = await idx.get_progress(track_id="track-1")
        assert detail["documents"] == [
            {
                "file_path": "app/main.py",
                "status": "processed",
                "chunks_count": 3,
                "content_length": 120,
                "error_msg": "",
                "created_at": "2026-09-05T10:00:00",
                "updated_at": "2026-09-05T10:01:00",
            }
        ]
    finally:
        await idx.close()

    op_names = [op[0] for op in state["ops"]]
    assert op_names.count("get_processing_status") == 2
    assert ("get_docs_by_track_id", "track-1") in state["ops"]


# ---------------------------------------------------------------------------
# Phase C：摄入路径编码（防 basename 碰撞）
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rel_path",
    [
        "src/a/util.py",
        "deep/nested/dir/file.md",
        "a~b/c~d.py",  # 含分隔符字符本身，需转义
        "模块/工具/说明.md",
        "single-file.txt",
        "a/b~c/d.py",
    ],
)
def test_encode_decode_path_roundtrip(rel_path: str) -> None:
    """配对函数往返测试（testing-rules §3）：编码后解码必须还原原路径。"""
    token = encode_ingest_path(rel_path)
    assert "/" not in token and "\\" not in token  # 单段 token 才能存活于 basename 归一化
    assert decode_ingest_path(token) == rel_path


def test_encode_path_normalizes_backslash_and_strips() -> None:
    assert encode_ingest_path("a\\b\\c.py") == encode_ingest_path("a/b/c.py")
    assert encode_ingest_path("  /x/y.py/  ") == encode_ingest_path("x/y.py")


@pytest.mark.parametrize("bad", ["", "   ", "///", "\\\\"])
def test_encode_path_rejects_empty(bad: str) -> None:
    """非正向：空路径/纯分隔符拒绝编码（防静默生成空 token）。"""
    with pytest.raises(ValueError, match="空路径"):
        encode_ingest_path(bad)


def test_decode_plain_filename_passthrough() -> None:
    """尽力而为解码：未编码的普通文件名原样返回（历史数据兼容）。"""
    assert decode_ingest_path("readme.md") == "readme.md"


def test_distinct_paths_same_basename_encode_differently() -> None:
    """核心动机：同名文件不同目录必须生成不同 token，避免上游重复拒绝。"""
    assert encode_ingest_path("src/a/util.py") != encode_ingest_path("src/b/util.py")


# ---------------------------------------------------------------------------
# Phase C：租户解析与内容哈希
# ---------------------------------------------------------------------------


def test_resolve_semantic_tenant_id_defaults_to_zero() -> None:
    assert get_tenant_id() is None  # 测试环境默认无租户上下文
    assert resolve_semantic_tenant_id() == 0


def test_resolve_semantic_tenant_id_uses_context() -> None:
    token = set_tenant_id(7)
    try:
        assert resolve_semantic_tenant_id() == 7
    finally:
        reset_tenant_ctx(token)


def test_content_hash_deterministic_and_distinct() -> None:
    """同口径哈希（与上游 DocStatus 落库一致）：确定性 + 内容敏感。"""
    assert content_hash_of("代码内容甲") == content_hash_of("代码内容甲")
    assert content_hash_of("代码内容甲") != content_hash_of("代码内容乙")


# ---------------------------------------------------------------------------
# Phase C：retrieve_chunks（检索级联语义入口）
# ---------------------------------------------------------------------------


def _chunk_item(content: str, file_path: str = "src~a.py", chunk_id: str = "c1") -> dict[str, Any]:
    return {"content": content, "file_path": file_path, "chunk_id": chunk_id, "reference_id": f"ref-{chunk_id}"}


async def test_retrieve_chunks_parses_structured_result(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """aquery_data(naive) 结构化解析：文本/路径/ID 透传，空内容过滤。"""
    state = _install_fake_rag(monkeypatch)
    _patch_embed_config(monkeypatch)
    state["query_data_result"] = {
        "status": "success",
        "data": {
            "chunks": [
                _chunk_item("def foo(): pass", chunk_id="c1"),
                _chunk_item("   ", chunk_id="c-empty"),  # 空白内容应被过滤
                _chunk_item("class Bar: ...", file_path="pkg~b.py", chunk_id="c2"),
                "非 dict 噪声",  # 异常形状应被跳过
            ]
        },
    }

    idx = LightRAGIndex(workspace="1:proj-x", working_dir=str(tmp_path))
    await idx.initialize()
    try:
        chunks = await idx.retrieve_chunks("foo 在哪定义", top_k=7)
    finally:
        await idx.close()

    assert [c["chunk_id"] for c in chunks] == ["c1", "c2"]
    assert chunks[0]["text"] == "def foo(): pass"
    assert chunks[0]["file_path"] == "src~a.py"
    assert chunks[0]["reference_id"] == "ref-c1"
    # 查询参数：naive 模式 + rerank 关闭（级联融合交 Conclave reranker）
    op = next(op for op in state["ops"] if op[0] == "aquery_data")
    assert op[1] == "foo 在哪定义"
    assert op[2] == "naive"
    assert op[3] is False


async def test_retrieve_chunks_failure_response_returns_empty(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """非正向：上游失败响应（data={}）→ 空列表而非抛错。"""
    state = _install_fake_rag(monkeypatch)
    _patch_embed_config(monkeypatch)
    state["query_data_result"] = {"status": "failure", "message": "empty query", "data": {}}

    idx = LightRAGIndex(workspace="1:proj-x", working_dir=str(tmp_path))
    await idx.initialize()
    try:
        assert await idx.retrieve_chunks("q") == []
    finally:
        await idx.close()


# ---------------------------------------------------------------------------
# Phase C：list_documents / purge_all_documents（增量 diff 与整体清理）
# ---------------------------------------------------------------------------


class _FakeDocRecord:
    """DocProcessingStatus 最小替身：list_documents 读取面（file_path/status/content_hash）。"""

    def __init__(self, file_path: str, content_hash: str, status_value: str = "processed") -> None:
        self.file_path = file_path
        self.content_hash = content_hash
        self.status = _FakeStatusEnum() if status_value == "processed" else type("S", (), {"value": status_value})()


async def test_list_documents_aggregates_pages(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """分页枚举聚合：跨页收集 {file_path: {doc_id, content_hash, status}}。"""
    state = _install_fake_rag(monkeypatch)
    _patch_embed_config(monkeypatch)
    state["doc_pages"] = [
        [("doc-1", _FakeDocRecord("a.py", "h1")), ("doc-2", _FakeDocRecord("b.py", "h2", "failed"))],
        [("doc-3", _FakeDocRecord("c.py", "h3"))],
    ]

    idx = LightRAGIndex(workspace="1:proj-x", working_dir=str(tmp_path))
    await idx.initialize()
    try:
        docs = await idx.list_documents()
    finally:
        await idx.close()

    assert set(docs) == {"a.py", "b.py", "c.py"}
    assert docs["a.py"] == {"doc_id": "doc-1", "content_hash": "h1", "status": "processed"}
    assert docs["b.py"]["status"] == "failed"
    # 两页各请求一次，单页大小取适配层常量
    pages = [op for op in state["ops"] if op[0] == "get_docs_paginated"]
    assert [(p[1], p[2]) for p in pages] == [(1, 200), (2, 200)]


async def test_list_documents_empty_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """边界：空 workspace → 空 dict，不无限翻页。"""
    state = _install_fake_rag(monkeypatch)
    _patch_embed_config(monkeypatch)
    state["doc_pages"] = []

    idx = LightRAGIndex(workspace="1:proj-x", working_dir=str(tmp_path))
    await idx.initialize()
    try:
        assert await idx.list_documents() == {}
    finally:
        await idx.close()
    assert sum(1 for op in state["ops"] if op[0] == "get_docs_paginated") == 1


async def test_purge_all_deletes_each_document(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """整体清理：枚举全部文档并逐个触发上游删除，返回删除数。"""
    state = _install_fake_rag(monkeypatch)
    _patch_embed_config(monkeypatch)
    state["doc_pages"] = [[("doc-1", _FakeDocRecord("a.py", "h1")), ("doc-2", _FakeDocRecord("b.py", "h2"))]]

    idx = LightRAGIndex(workspace="1:proj-x", working_dir=str(tmp_path))
    await idx.initialize()
    try:
        purged = await idx.purge_all_documents()
    finally:
        await idx.close()

    assert purged == 2
    deleted = [op[1] for op in state["ops"] if op[0] == "adelete_by_doc_id"]
    assert sorted(deleted) == ["doc-1", "doc-2"]


def test_workspace_dir_is_working_dir_scoped(tmp_path) -> None:
    """workspace 文件目录 = working_dir/{workspace}（清理时 rmtree 的目标）。"""
    idx = LightRAGIndex(workspace="1:proj-x", working_dir=str(tmp_path))
    assert idx.workspace_dir == tmp_path / "1:proj-x"
