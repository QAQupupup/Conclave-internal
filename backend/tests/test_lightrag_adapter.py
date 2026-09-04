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
    get_semantic_index,
    is_semantic_index_available,
)
from app.rag.store import SiliconFlowEmbedding
from app.tenants.context import get_tenant_id

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


def _install_fake_rag(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """安装 fake LightRAG 类，捕获构造参数与操作记录（不 mock 适配层自身）。"""
    import lightrag as lightrag_module

    state: dict[str, Any] = {"init_count": 0, "ops": [], "kwargs": {}}

    class _FakeRAG:
        def __init__(self, **kwargs: Any) -> None:
            state["init_count"] += 1
            state["kwargs"] = kwargs

        async def initialize_storages(self) -> None:
            state["initialized"] = True

        async def finalize_storages(self) -> None:
            state["finalized"] = True

        async def ainsert(self, texts: list[str], ids: list[str] | None = None) -> None:
            state["ops"].append(("ainsert", list(texts), ids))

        async def aquery(self, question: str, param: Any = None) -> str:
            state["ops"].append(("aquery", question, param.mode))
            return "fake 答案"

        async def adelete_by_doc_id(self, doc_id: str) -> None:
            state["ops"].append(("adelete_by_doc_id", doc_id))

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
    """插入/查询/删除正确委托 LightRAG，查询默认 mix 双层检索。"""
    state = _install_fake_rag(monkeypatch)
    _patch_embed_config(monkeypatch)

    idx = LightRAGIndex(workspace="1:proj-x", working_dir=str(tmp_path))
    await idx.initialize()

    await idx.insert_texts(["t1", "t2"], ids=["id1", "id2"])
    answer = await idx.query("这个仓库是干什么的？")
    await idx.delete_doc("doc-9")
    await idx.close()

    assert answer == "fake 答案"
    ops = state["ops"]
    assert ops[0] == ("ainsert", ["t1", "t2"], ["id1", "id2"])
    assert ops[1][0] == "aquery"
    assert ops[1][2] == "mix"  # 默认双层检索模式
    assert ops[2] == ("adelete_by_doc_id", "doc-9")
    assert state["finalized"] is True
    assert idx.is_ready is False
