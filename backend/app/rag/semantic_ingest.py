# 仓库级语义摄入编排（ADR-018 Phase B/C）：预处理 → 配额护栏 → 增量 diff → 串行锁 → 分批摄入
#
# 接线 ADR-016 摄入层与 ADR-018 语义层：已摄入仓库经 code_to_text 三路分派
# 预处理后，分批写入 LightRAG（D3 隔离键、D6 哈希去重/增量合并由上游承担）。
#
# 设计要点：
# - 增量摄入（Phase C，D6/D13）：重摄入先枚举 DocStatus 现有文档，按内容哈希
#   四分类——新增直插 / 不变跳过 / 变更删旧插新 / 仓库已删的文件清理旧文档。
#   上游同名记录一律按重复拒绝（源码级核实），变更文件不删旧永远无法更新；
#   failed 记录删后重插，使重摄入天然具备失败重试语义。
#   合入触发（D13）：ADR-017 D11 议题合入 main 流程尚未落地，无接线点；
#   合入完成后直接重调 ingest_repo_semantic 即增量重摄（能力已预备，不虚构钩子）。
# - 配额护栏（D8）：ADR-007 租户配额父池尚未实现，先以系统级摄入预算
#   （文件数/字符数上限）拦截巨型仓库；租户配额服务落地后在
#   check_ingest_budget 内叠加，调用方无需改动（单一入口）。
# - 分批（D8）：单批 BATCH_SIZE 篇文档，限制单次 LLM 抽取体积与失败爆炸半径；
#   每批一个 track_id，供 DocStatus 进度查询（TB.4）。
# - D12 串行锁：同一 workspace（项目/会议隔离键）的建索引/清理请求进程内串行，
#   防 LightRAG 图合并竞态。当前为单进程锁（LazyLock），多实例部署需升级为
#   Redis/PG advisory lock（随项目级索引落地）。
# - 降级哲学：语义层三要素（Qdrant/LLM/Embedding）缺一 → 返回 enabled=False，
#   调用方照常完成结构层索引，不阻断摄入。
from __future__ import annotations

import asyncio
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from app.core.exceptions import QuotaExceededError
from app.lazy_asyncio import LazyLock
from app.logging_config import get_logger
from app.rag.code_to_text import FileDocument, repo_to_documents
from app.rag.lightrag_adapter import content_hash_of, encode_ingest_path, get_semantic_index

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


def _diff_documents(
    docs: list[FileDocument],
    existing: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """增量 diff（D6/D13）：本地扫描结果对比 DocStatus 现有记录，四分类。

    - 新增：现有记录没有该编码路径 → 直接摄入
    - 不变：内容哈希一致 → 跳过（省去上游入队与抽取开销）
    - 变更：哈希不一致 → 删旧文档后重新摄入（上游同名记录一律按重复拒绝，
      不删旧则变更永远无法入库——源码级核实，见 lightrag pipeline.py）
    - failed 记录：视为待重建（删后重插），重摄入即失败重试
    - 仓库已删除的文件：现有记录不在本次扫描 → 删除旧文档（触发上游 purge）

    无 content_hash 的记录（pending/parsing 等在途任务）保守跳过，
    不打断上游正在进行的处理；其结果由下次重摄入再行比对。
    """
    delete_ids: list[str] = []
    to_insert: list[FileDocument] = []
    new = 0
    updated = 0
    unchanged = 0
    skipped_in_progress = 0
    seen_tokens: set[str] = set()

    for doc in docs:
        token = encode_ingest_path(doc.rel_path)
        seen_tokens.add(token)
        record = existing.get(token)
        if record is None:
            to_insert.append(doc)
            new += 1
            continue
        if record["status"] == "failed":
            delete_ids.append(record["doc_id"])
            to_insert.append(doc)
            updated += 1
            continue
        if not record["content_hash"]:
            skipped_in_progress += 1
            continue
        if record["content_hash"] == content_hash_of(doc.text):
            unchanged += 1
        else:
            delete_ids.append(record["doc_id"])
            to_insert.append(doc)
            updated += 1

    removed = 0
    for token, record in existing.items():
        if token not in seen_tokens:
            delete_ids.append(record["doc_id"])
            removed += 1

    return {
        "to_insert": to_insert,
        "delete_ids": delete_ids,
        "new": new,
        "updated": updated,
        "unchanged": unchanged,
        "skipped_in_progress": skipped_in_progress,
        "removed": removed,
    }


async def ingest_repo_semantic(
    repo_root: str | Path,
    *,
    meeting_id: str,
    tenant_id: int,
    project_id: str | None = None,
) -> dict[str, Any]:
    """对已摄入仓库构建/增量更新 LightRAG 语义索引（幂等：内容哈希比对）。

    增量语义（Phase C）：重复摄入只处理变更——新增直插、变更删旧插新、
    仓库已删文件清理旧文档、内容不变跳过。空扫描不触发任何删除动作
    （防目录错配误清索引；显式清理走 cleanup_semantic_workspace）。

    Args:
        repo_root: 已摄入仓库绝对路径（workspace/{meeting_id}/{repo}）。
        meeting_id: 会议作用域（无 project_id 时的退化隔离键，D3）。
        tenant_id: 租户 ID（隔离键前缀，P8 红线）。
        project_id: 项目 ID；projects 表（ADR-017 Phase 2）落地前传 None，
            退化会议级索引。

    Returns:
        摄入结果 dict：
        - enabled=False + reason：语义层不可用（降级，不阻断摄入）
        - enabled=True：workspace / docs_ingested（新增+变更）/ batches / track_ids
          + 增量明细 docs_new / docs_updated / docs_unchanged / docs_removed

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
            "docs_new": 0,
            "docs_updated": 0,
            "docs_unchanged": 0,
            "docs_removed": 0,
        }

    track_ids: list[str] = []

    # D12：同一 workspace 串行建索引，防图合并竞态
    async with _workspace_lock(index.workspace):
        await index.initialize()
        try:
            existing = await index.list_documents()
            diff = _diff_documents(docs, existing)

            # 删旧：变更/已删/failed 文档先清理，再插新（上游同名去重所迫）
            for doc_id in diff["delete_ids"]:
                await index.delete_doc(doc_id)

            to_insert: list[FileDocument] = diff["to_insert"]
            batches = [to_insert[i : i + BATCH_SIZE] for i in range(0, len(to_insert), BATCH_SIZE)]
            for batch in batches:
                track_id = await index.insert_texts(
                    [d.text for d in batch],
                    file_paths=[encode_ingest_path(d.rel_path) for d in batch],
                )
                track_ids.append(track_id)
        finally:
            await index.close()

    logger.info(
        "语义索引增量摄入完成 meeting_id=%s workspace=%s 扫描=%d 新增=%d 变更=%d 不变=%d 清理=%d batches=%d",
        meeting_id,
        index.workspace,
        len(docs),
        diff["new"],
        diff["updated"],
        diff["unchanged"],
        diff["removed"],
        len(track_ids),
    )
    return {
        "enabled": True,
        "workspace": index.workspace,
        "docs_ingested": len(diff["to_insert"]),
        "batches": len(track_ids),
        "track_ids": track_ids,
        "docs_new": diff["new"],
        "docs_updated": diff["updated"],
        "docs_unchanged": diff["unchanged"] + diff["skipped_in_progress"],
        "docs_removed": diff["removed"],
    }


async def cleanup_semantic_workspace(
    tenant_id: int,
    *,
    project_id: str | None = None,
    meeting_id: str | None = None,
) -> dict[str, Any]:
    """整体清理语义索引工作区（D10/D7：会议硬删除/项目删除触发）。

    流程（D12 串行锁内，与摄入互斥）：枚举全部文档 → 逐个 adelete_by_doc_id
    （上游 4 阶段 purge 清理图谱/向量孤儿）→ 关闭存储 → 删除文件目录。
    语义层不可用 → no-op（enabled=False）。清理失败上抛由调用方决定降级策略
    （会议删除接线处只告警不阻断删除）。
    """
    index = get_semantic_index(tenant_id, project_id=project_id, meeting_id=meeting_id)
    if index is None:
        return {"enabled": False, "reason": "semantic_layer_unavailable", "docs_purged": 0}

    async with _workspace_lock(index.workspace):
        await index.initialize()
        try:
            purged = await index.purge_all_documents()
        finally:
            await index.close()
        # 目录删除放 close 之后：存储句柄释放后再动文件，避免写回竞态
        shutil.rmtree(index.workspace_dir, ignore_errors=True)

    logger.info(
        "语义索引工作区已清理 workspace=%s docs_purged=%d",
        index.workspace,
        purged,
    )
    return {"enabled": True, "workspace": index.workspace, "docs_purged": purged}
