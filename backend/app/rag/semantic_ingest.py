# 仓库级语义摄入编排（ADR-018 Phase B）：预处理 → 配额护栏 → 串行锁 → 分批摄入
#
# 接线 ADR-016 摄入层与 ADR-018 语义层：已摄入仓库经 code_to_text 三路分派
# 预处理后，分批写入 LightRAG（D3 隔离键、D6 哈希去重/增量合并由上游承担）。
#
# 设计要点：
# - 配额护栏（D8）：ADR-007 租户配额父池尚未实现，先以系统级摄入预算
#   （文件数/字符数上限）拦截巨型仓库；租户配额服务落地后在
#   check_ingest_budget 内叠加，调用方无需改动（单一入口）。
# - 分批（D8）：单批 BATCH_SIZE 篇文档，限制单次 LLM 抽取体积与失败爆炸半径；
#   每批一个 track_id，供 DocStatus 进度查询（TB.4）。
# - D12 串行锁：同一 workspace（项目/会议隔离键）的建索引请求进程内串行，
#   防 LightRAG 图合并竞态。当前为单进程锁（LazyLock），多实例部署需升级为
#   Redis/PG advisory lock（Phase C 随项目级索引落地）。
# - 降级哲学：语义层三要素（Qdrant/LLM/Embedding）缺一 → 返回 enabled=False，
#   调用方照常完成结构层索引，不阻断摄入。
from __future__ import annotations

import asyncio
import os
import threading
from pathlib import Path
from typing import Any

from app.core.exceptions import QuotaExceededError
from app.lazy_asyncio import LazyLock
from app.logging_config import get_logger
from app.rag.code_to_text import FileDocument, repo_to_documents
from app.rag.lightrag_adapter import get_semantic_index

logger = get_logger("rag.semantic_ingest")

# ---- 预算与批量参数（环境变量可调） ----
# 单批摄入文档数：LightRAG max_parallel_insert=2（适配层）配合，
# 16 篇/批在抽取质量与失败重试成本之间折中
BATCH_SIZE = int(os.environ.get("CONCLAVE_SEMANTIC_INGEST_BATCH", "16"))
# 单次摄入文档数上限：防巨型仓库一次性拖垮租户 LLM 额度（D8）
MAX_INGEST_DOCS = int(os.environ.get("CONCLAVE_SEMANTIC_INGEST_MAX_DOCS", "3000"))
# 单次摄入总字符数上限（600 万字符 ≈ 150 万 token 原文体积，预处理后会更更小）
MAX_INGEST_CHARS = int(os.environ.get("CONCLAVE_SEMANTIC_INGEST_MAX_CHARS", str(6_000_000)))

# D12：workspace → 串行锁注册表（进程内）
_index_locks: dict[str, LazyLock] = {}
_registry_guard = threading.Lock()


def check_ingest_budget(docs: list[FileDocument]) -> None:
    """摄入预算护栏（D8）：超限抛 ``QuotaExceededError``（全局处理器转 429）。

    当前为系统级上限；ADR-007 租户配额服务实现后在此叠加租户级检查，
    保持单一入口，调用方无感知。
    """
    if len(docs) > MAX_INGEST_DOCS:
        raise QuotaExceededError(
            f"语义摄入超出文档数预算：{len(docs)} 篇，上限 {MAX_INGEST_DOCS} 篇",
            details={"docs": len(docs), "max_docs": MAX_INGEST_DOCS},
        )
    total_chars = sum(d.char_count for d in docs)
    if total_chars > MAX_INGEST_CHARS:
        raise QuotaExceededError(
            f"语义摄入超出字符数预算：{total_chars} 字符，上限 {MAX_INGEST_CHARS} 字符",
            details={"chars": total_chars, "max_chars": MAX_INGEST_CHARS},
        )


def _workspace_lock(workspace: str) -> LazyLock:
    """取/建 workspace 级串行锁（D12）。"""
    with _registry_guard:
        lock = _index_locks.get(workspace)
        if lock is None:
            lock = LazyLock()
            _index_locks[workspace] = lock
        return lock


async def ingest_repo_semantic(
    repo_root: str | Path,
    *,
    meeting_id: str,
    tenant_id: int,
    project_id: str | None = None,
) -> dict[str, Any]:
    """对已摄入仓库构建/更新 LightRAG 语义索引（幂等：内容哈希去重）。

    Args:
        repo_root: 已摄入仓库绝对路径（workspace/{meeting_id}/{repo}）。
        meeting_id: 会议作用域（无 project_id 时的退化隔离键，D3）。
        tenant_id: 租户 ID（隔离键前缀，P8 红线）。
        project_id: 项目 ID；projects 表（ADR-017 Phase 2）落地前传 None，
            退化会议级索引。

    Returns:
        摄入结果 dict：
        - enabled=False + reason：语义层不可用（降级，不阻断摄入）
        - enabled=True：workspace / docs_ingested / batches / track_ids

    Raises:
        QuotaExceededError: 超出摄入预算（D8），由全局异常处理器转 429。
    """
    index = get_semantic_index(tenant_id, project_id=project_id, meeting_id=meeting_id)
    if index is None:
        logger.info("语义理解层不可用，跳过语义索引: meeting_id=%s", meeting_id)
        return {"enabled": False, "reason": "semantic_layer_unavailable", "docs_ingested": 0}

    # CPU/IO 密集的文件扫描 + 预处理放线程池（与 code_index.index_repo 同策略）
    docs = await asyncio.to_thread(repo_to_documents, repo_root)
    check_ingest_budget(docs)

    if not docs:
        logger.info("仓库无可摄入文档，跳过语义索引: meeting_id=%s", meeting_id)
        return {
            "enabled": True,
            "workspace": index.workspace,
            "docs_ingested": 0,
            "batches": 0,
            "track_ids": [],
        }

    batches = [docs[i : i + BATCH_SIZE] for i in range(0, len(docs), BATCH_SIZE)]
    track_ids: list[str] = []

    # D12：同一 workspace 串行建索引，防图合并竞态
    async with _workspace_lock(index.workspace):
        await index.initialize()
        try:
            for batch in batches:
                track_id = await index.insert_texts(
                    [d.text for d in batch],
                    file_paths=[d.rel_path for d in batch],
                )
                track_ids.append(track_id)
        finally:
            await index.close()

    logger.info(
        "语义索引摄入完成 meeting_id=%s workspace=%s docs=%d batches=%d",
        meeting_id,
        index.workspace,
        len(docs),
        len(batches),
    )
    return {
        "enabled": True,
        "workspace": index.workspace,
        "docs_ingested": len(docs),
        "batches": len(batches),
        "track_ids": track_ids,
    }
