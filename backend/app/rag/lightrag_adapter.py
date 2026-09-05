"""LightRAG 适配层（ADR-018 Phase A）。

把 Conclave 的 SiliconFlow Embedding / LLM 与 Qdrant 包装为 LightRAG 注入函数，
隔离上游 API（D9：requirements.lock 锁版本 + 本适配层防 API 漂移）。

关键决策（详见 docs/design/adr/018-codebase-understanding-lightrag.md）：

- D3 隔离键：workspace = ``{tenant_id}:proj-{project_id}``（项目级共享索引），
  无项目时退化 ``{tenant_id}:mtg-{meeting_id}``（会议级临时索引）。
- D4：复用 ``SiliconFlowEmbedding``（租户级覆盖链路原样继承），不引入第二套嵌入服务。
- D8：实体抽取温度锁 0.0（对齐设计原则温度纪律）。
- Qdrant：LightRAG 的 ``QdrantVectorDBStorage`` 读 ``QDRANT_URL`` 环境变量建客户端，
  初始化时由 ``settings.qdrant_url`` 同步写入（禁止硬编码 URL，AGENTS.md §5.4）。
- Stub 降级：Qdrant/Embedding/LLM 任一缺失时 ``get_semantic_index()`` 返回 None，
  调用方退回 ADR-016 纯结构层检索（功能可用、无语义理解）。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("rag.lightrag_adapter")

# D3：两类隔离键前缀，防止项目 UUID 与会议 UUID 撞键
_PROJECT_KEY_PREFIX = "proj-"
_MEETING_KEY_PREFIX = "mtg-"

# D8：语义索引构建属抽取类调用，温度锁 0.0
_EXTRACTION_TEMPERATURE = 0.0

# 摄入路径编码分隔符（把仓库相对路径压成单段 token，见 encode_ingest_path）
_PATH_SEP = "~"

# list_documents 分页枚举 DocStatus 的单页大小（上游允许 10-200）
_DOC_PAGE_SIZE = 200


def encode_ingest_path(rel_path: str) -> str:
    """把仓库相对路径编码为可在 LightRAG 内存活的 file_path token（D9 隔离）。

    上游 ``normalize_document_file_path`` 只保留 basename：直接传 ``src/a/util.py``
    会被归一成 ``util.py``，与 ``src/b/util.py`` 撞键——同名记录一律按重复文档
    拒绝（上游源码级核实，见 pipeline.py filename dedup），导致同名文件互相顶掉。

    编码规则（单射、可逆，逆运算见 decode_ingest_path）：
    先把已有的 ``~`` 转义为 ``~~``，再把 ``/`` 替换为 ``~``，
    结果不含路径分隔符，basename 归一化后原样保留。

    已知边界：上游另会剥离 ``名称.[解析引擎].扩展名`` 中的提示段（如
    ``x.[native].py`` → ``x.py``）；代码仓库文件名命中该模式的概率极低，
    且内容哈希去重仍兜底，不为此引入更重的转义。
    """
    normalized = rel_path.replace("\\", "/").strip().strip("/")
    if not normalized:
        raise ValueError(f"摄入路径编码拒绝空路径: {rel_path!r}")
    return normalized.replace(_PATH_SEP, _PATH_SEP * 2).replace("/", _PATH_SEP)


def decode_ingest_path(token: str) -> str:
    """``encode_ingest_path`` 的逆运算（配对函数，往返测试覆盖）。

    尽力而为：对未经编码的普通文件名原样返回，供引用展示与溯源。
    """
    out: list[str] = []
    i = 0
    n = len(token)
    while i < n:
        ch = token[i]
        if ch == _PATH_SEP:
            if i + 1 < n and token[i + 1] == _PATH_SEP:
                out.append(_PATH_SEP)
                i += 2
            else:
                out.append("/")
                i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def resolve_semantic_tenant_id() -> int:
    """语义索引操作的租户 ID 解析（摄入/检索/清理共用，保证隔离键一致）。

    请求/任务上下文租户 → 0（系统命名空间，开发模式约定）。
    与 ``routers/code.py`` 原 ``_resolve_tenant_id`` 同口径：真实租户 ID 从 1 起，
    0 不冲突（D3 租户前缀隔离不受影响）。
    """
    from app.tenants.context import get_tenant_id

    tenant_id = get_tenant_id()
    return tenant_id if tenant_id is not None else 0


def content_hash_of(text: str) -> str:
    """按 LightRAG 上游同口径计算文档内容哈希（增量比对的唯一事实源）。

    复用上游 ``compute_text_content_hash``：与 DocStatus 落库的 content_hash
    完全一致，本地比对结果等价于上游去重判定（D6 复用上游机制，不自研）。
    """
    from lightrag.utils_pipeline import compute_text_content_hash

    return str(compute_text_content_hash(text))


def _serialize_doc_status(status_obj: Any) -> dict[str, Any]:
    """把 LightRAG ``DocProcessingStatus`` 序列化为 JSON 安全 dict。

    只暴露前端进度展示所需字段；status 取枚举值（pending/parsing/analyzing/
    processing/preprocessed/processed/failed），上游新增字段不影响本层契约。
    """
    status = getattr(status_obj, "status", None)
    return {
        "file_path": getattr(status_obj, "file_path", "") or "",
        "status": getattr(status, "value", str(status)),
        "chunks_count": getattr(status_obj, "chunks_count", 0) or 0,
        "content_length": getattr(status_obj, "content_length", 0) or 0,
        "error_msg": getattr(status_obj, "error_msg", "") or "",
        "created_at": getattr(status_obj, "created_at", "") or "",
        "updated_at": getattr(status_obj, "updated_at", "") or "",
    }


def build_workspace_key(
    tenant_id: int,
    *,
    project_id: str | None = None,
    meeting_id: str | None = None,
) -> str:
    """构造 D3 隔离键：``{tenant_id}:proj-{project_id}`` 或 ``{tenant_id}:mtg-{meeting_id}``。

    project_id 与 meeting_id 必须提供其一（前者优先）。
    workspace 键会被 LightRAG 文件存储用作目录名，故禁止路径分隔符与相对路径引用
    （与上游 ``validate_workspace`` 同规则，提前失败给出清晰错误）。
    """
    if project_id:
        scope = f"{_PROJECT_KEY_PREFIX}{project_id}"
    elif meeting_id:
        scope = f"{_MEETING_KEY_PREFIX}{meeting_id}"
    else:
        raise ValueError("build_workspace_key 需要 project_id 或 meeting_id 至少其一")
    key = f"{tenant_id}:{scope}"
    if "/" in key or "\\" in key or key in (".", ".."):
        raise ValueError(f"非法 workspace 键（含路径分隔符或相对路径）: {key!r}")
    return key


def is_semantic_index_available() -> bool:
    """判断语义理解层是否可用：Qdrant + 真实 LLM + 真实 Embedding 三者齐备。

    任一缺失则 LightRAG 索引不可用，调用方应 graceful 降级到 ADR-016 纯结构层。
    注意：此处只查系统级配置；租户级 BYOK 覆盖在每次嵌入/LLM 调用时解析。
    """
    if not settings.use_qdrant:
        return False
    if not settings.use_real_llm:
        return False
    if settings.embed_api_key:
        return True
    try:
        from app.services.config_service import get_cached_system_settings

        return bool(get_cached_system_settings().get("embed_api_key"))
    except Exception:  # pragma: no cover - config_service 不可用时按无 key 处理
        return False


def _make_embedding_func(tenant_id: int | None) -> Any:
    """把 ``SiliconFlowEmbedding`` 包装为 LightRAG ``EmbeddingFunc``（D4）。

    - 每次调用显式设置租户上下文，保证租户级覆盖链路在 LightRAG 内部任务中生效；
    - 配置缺失时抛错而非静默降级 StubEmbedding——伪向量会污染语义索引。
    """
    from lightrag.utils import EmbeddingFunc

    from app.rag.store import SiliconFlowEmbedding
    from app.tenants.context import reset_tenant_ctx, set_tenant_id

    embed = SiliconFlowEmbedding()

    # 租户上下文下解析生效模型名，用于 Qdrant collection 后缀（嵌入模型变更时的隔离依据）
    token = set_tenant_id(tenant_id) if tenant_id is not None else None
    try:
        _base, _key, model = embed.resolve_config()
        dim = embed.dim
    finally:
        if token is not None:
            reset_tenant_ctx(token)

    async def _embed_texts(texts: list[str], **_kwargs: Any) -> np.ndarray:
        tk = set_tenant_id(tenant_id) if tenant_id is not None else None
        try:
            base_url, api_key, _model = embed.resolve_config()
            if not base_url or not api_key:
                raise RuntimeError("Embedding 未配置，无法构建 LightRAG 语义索引")
            vecs = await embed.embed_batch(list(texts))
        finally:
            if tk is not None:
                reset_tenant_ctx(tk)
        if len(vecs) != len(texts):
            raise RuntimeError(f"嵌入数量不匹配：期望 {len(texts)} 条，实际 {len(vecs)} 条")
        return np.asarray(vecs, dtype=np.float32)

    return EmbeddingFunc(
        embedding_dim=dim,
        func=_embed_texts,
        model_name=model or None,
        supports_asymmetric=False,
    )


def _make_llm_func(tenant_id: int | None) -> Any:
    """把 Conclave LLM 客户端包装为 LightRAG ``llm_model_func``。

    上游契约：``await func(prompt, system_prompt=..., **kwargs) -> str``。
    复用 ``get_llm()`` 链路（熔断器 + 会议/租户级配置覆盖）；
    温度按 D8 锁 0.0；无 key 时 get_llm() 返回 StubLLM，此处显式拒绝——
    桩数据进图谱会污染索引，调用方应在建索引前用 is_semantic_index_available() 拦截。
    """
    from app.tenants.context import reset_tenant_ctx, set_tenant_id

    async def _llm(
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict[str, str]] | None = None,
        **_kwargs: Any,
    ) -> str:
        from app.agents.llm import StubLLM, get_llm

        tk = set_tenant_id(tenant_id) if tenant_id is not None else None
        try:
            llm = get_llm()
            if isinstance(llm, StubLLM):
                raise RuntimeError("LLM 未配置，无法构建 LightRAG 语义索引")
            merged = "\n\n".join(p for p in (system_prompt, prompt) if p)
            if history_messages:
                hist = "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history_messages)
                merged = f"[历史对话]\n{hist}\n\n{merged}"
            return await llm.complete_text(merged, temperature=_EXTRACTION_TEMPERATURE)
        finally:
            if tk is not None:
                reset_tenant_ctx(tk)

    return _llm


class LightRAGIndex:
    """单个 workspace 的语义索引门面（隔离 LightRAG 上游 API，D9）。

    用法::

        index = get_semantic_index(tenant_id, project_id=...)
        if index is not None:          # None = 降级纯结构层
            await index.initialize()
            await index.insert_texts([...])
            answer = await index.query("这个仓库是干什么的？")
            await index.close()
    """

    def __init__(
        self,
        workspace: str,
        tenant_id: int | None = None,
        working_dir: str | None = None,
    ) -> None:
        self._workspace = workspace
        self._tenant_id = tenant_id
        # D10：文件存储（KV/图/DocStatus）落工作区目录；向量走 Qdrant（D2 独立 collection）
        self._working_dir = working_dir or str(Path(settings.workspace_root) / "lightrag")
        self._rag: Any = None

    @property
    def workspace(self) -> str:
        return self._workspace

    @property
    def is_ready(self) -> bool:
        return self._rag is not None

    async def initialize(self) -> None:
        """初始化 LightRAG 实例与全部存储（幂等）。"""
        if self._rag is not None:
            return
        from lightrag import LightRAG

        # LightRAG 的 QdrantVectorDBStorage 通过 QDRANT_URL 环境变量创建客户端：
        # 从 Conclave 统一配置同步，避免第二处硬编码 URL
        if settings.qdrant_url:
            os.environ["QDRANT_URL"] = settings.qdrant_url

        rag = LightRAG(
            working_dir=self._working_dir,
            workspace=self._workspace,
            vector_storage="QdrantVectorDBStorage",
            embedding_func=_make_embedding_func(self._tenant_id),
            llm_model_func=_make_llm_func(self._tenant_id),
            llm_model_name=settings.llm_model,
            # D8：首次全量索引限制并发，受配额约束的上游侧护栏
            max_parallel_insert=2,
            # 中文实体/关系抽取与摘要语言
            addon_params={"language": "Simplified Chinese"},
        )
        await rag.initialize_storages()
        self._rag = rag
        logger.info("LightRAG 语义索引已初始化: workspace=%s dir=%s", self._workspace, self._working_dir)

    def _require_rag(self) -> Any:
        if self._rag is None:
            raise RuntimeError("LightRAGIndex 未初始化：请先调用 initialize()")
        return self._rag

    async def insert_texts(
        self,
        texts: list[str],
        ids: list[str] | None = None,
        file_paths: list[str] | None = None,
        track_id: str | None = None,
    ) -> str:
        """插入文档并返回 track_id（DocStatus 进度查询的批次凭据）。

        LightRAG 内建内容哈希去重 + 增量合并（D6 直接复用）：不传 ids 时
        上游按内容哈希生成文档 ID——文件改名（内容不变）识别为同文档。
        file_paths 与 texts 一一对应，供引用溯源与按文件定位文档。
        """
        rag = self._require_rag()
        result = await rag.ainsert(texts, ids=ids, file_paths=file_paths, track_id=track_id)
        return str(result)

    async def query(self, question: str, mode: str = "mix") -> str:
        """双层检索查询。mode: local/global/hybrid/mix/naive（mix=实体+主题双层）。"""
        from lightrag.base import QueryParam

        rag = self._require_rag()
        # 未接入 rerank 服务，关闭 rerank 避免空配置报错（级联融合在 Phase C 接入）
        param = QueryParam(mode=mode, enable_rerank=False)
        # 上游 aquery 契约返回 str（lightrag 无类型存根，显式标注防 Any 泄漏）
        result: str = await rag.aquery(question, param=param)
        return result

    async def delete_doc(self, doc_id: str) -> None:
        """删除文档并触发图谱清理（D7：LightRAG 4 阶段 purge 直接复用）。"""
        rag = self._require_rag()
        await rag.adelete_by_doc_id(doc_id)

    @property
    def workspace_dir(self) -> Path:
        """workspace 文件存储目录（``working_dir/{workspace}/``，上游按 workspace 分子目录落盘）。"""
        return Path(self._working_dir) / self._workspace

    async def retrieve_chunks(self, question: str, top_k: int = 5) -> list[dict[str, Any]]:
        """结构化 chunk 召回（Phase C 检索级联的语义入口）。

        用上游 ``aquery_data`` naive 模式：纯向量召回预处理文档的 chunk，
        **零查询期 LLM 消耗**（D8 成本治理——mix 双层需查询期关键词抽取，
        不放在检索热路径；级联融合交 Conclave reranker 统一完成）。
        返回 ``[{text, file_path, chunk_id, reference_id}]``；无命中返回空列表。
        """
        from lightrag.base import QueryParam

        rag = self._require_rag()
        param = QueryParam(mode="naive", top_k=top_k, chunk_top_k=top_k, enable_rerank=False)
        # 上游 aquery_data 返回结构化 dict（lightrag 无类型存根，显式收窄防 Any 泄漏）
        raw: dict[str, Any] = await rag.aquery_data(question, param=param)
        data = raw.get("data") if isinstance(raw, dict) else None
        chunks = data.get("chunks") if isinstance(data, dict) else None
        out: list[dict[str, Any]] = []
        for chunk in chunks or []:
            if not isinstance(chunk, dict):
                continue
            text = str(chunk.get("content") or "")
            if not text.strip():
                continue
            out.append(
                {
                    "text": text,
                    "file_path": str(chunk.get("file_path") or ""),
                    "chunk_id": str(chunk.get("chunk_id") or ""),
                    "reference_id": str(chunk.get("reference_id") or ""),
                }
            )
        return out

    async def list_documents(self) -> dict[str, dict[str, Any]]:
        """枚举 workspace 全部文档（增量 diff 与整体清理的依据）。

        返回 ``{file_path: {doc_id, content_hash, status}}``。file_path 为上游
        归一化后的存储键（即 encode_ingest_path 的编码结果）。上游同名去重保证
        其唯一性；极端的历史撞键（上游 SourceConflict 记录）下后者覆盖前者，
        清理时按 doc_id 逐个删除不受影响。
        """
        rag = self._require_rag()
        out: dict[str, dict[str, Any]] = {}
        page = 1
        while True:
            result = await rag.doc_status.get_docs_paginated(page=page, page_size=_DOC_PAGE_SIZE)
            items, total = result
            for doc_id, status_obj in items:
                file_path = str(getattr(status_obj, "file_path", "") or "")
                status_enum = getattr(status_obj, "status", None)
                out[file_path] = {
                    "doc_id": str(doc_id),
                    "content_hash": str(getattr(status_obj, "content_hash", "") or ""),
                    "status": str(getattr(status_enum, "value", status_enum) or ""),
                }
            if not items or len(out) >= int(total):
                break
            page += 1
        return out

    async def purge_all_documents(self) -> int:
        """删除 workspace 全部文档（逐个触发上游 4 阶段 purge，D7）。

        图谱实体/关系的孤儿清理与 Qdrant 点位删除由上游 purge 机制承担；
        本方法只负责按 DocStatus 枚举并逐文档下发删除。返回删除文档数。
        """
        documents = await self.list_documents()
        for info in documents.values():
            await self.delete_doc(info["doc_id"])
        return len(documents)

    async def get_progress(self, track_id: str | None = None) -> dict[str, Any]:
        """DocStatus 进度查询（ADR-018 Phase B）：状态计数 + 按批次的逐文档明细。

        复用 LightRAG 内建 DocStatus 状态机（D6）：
        - status_counts：workspace 级各状态文档数（pending/.../processed/failed）
        - documents：指定 track_id（一次 insert 批次）时返回逐文档状态，
          未指定时为空列表（避免大仓库全量枚举拖慢查询）
        """
        rag = self._require_rag()
        status_counts: dict[str, int] = await rag.get_processing_status()
        documents: list[dict[str, Any]] = []
        if track_id:
            mapping = await rag.doc_status.get_docs_by_track_id(track_id)
            documents = [_serialize_doc_status(s) for s in mapping.values()]
        return {"status_counts": status_counts, "documents": documents}

    async def close(self) -> None:
        """关闭存储（flush 向量缓冲、释放客户端）。"""
        if self._rag is not None:
            await self._rag.finalize_storages()
            self._rag = None


def get_semantic_index(
    tenant_id: int,
    *,
    project_id: str | None = None,
    meeting_id: str | None = None,
    working_dir: str | None = None,
) -> LightRAGIndex | None:
    """语义索引工厂：不可用时返回 None（调用方降级 ADR-016 纯结构层检索）。

    返回的实例尚未初始化，调用方需 ``await index.initialize()``，
    用毕 ``await index.close()``。
    """
    if not is_semantic_index_available():
        logger.info("语义理解层不可用（Qdrant/Embedding/LLM 配置缺失），降级纯结构层检索")
        return None
    workspace = build_workspace_key(tenant_id, project_id=project_id, meeting_id=meeting_id)
    return LightRAGIndex(workspace=workspace, tenant_id=tenant_id, working_dir=working_dir)
