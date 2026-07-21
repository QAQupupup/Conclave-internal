# HyDE: Hypothetical Document Embeddings
# 原理：用 LLM 生成假设性文档，用该文档的 embedding 检索（而非原始 query），
#       因为假设文档在 embedding 空间中更接近实际文档。
# 参考：Gao et al. 2022, "Precise Zero-Shot Dense Retrieval without Relevance Labels"
from __future__ import annotations

import re
from typing import Any

import httpx

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("rag.hyde")

_HYDE_PROMPT = """你是一个技术文档生成器。请根据以下问题或冲突描述，生成一段假设性的技术文档内容（200-300字）。
这段内容应该是一个可能包含相关答案的文档段落，用于语义检索。

问题/冲突：{query}

要求：
1. 写成技术文档风格（不是问答，不要加"答："前缀）
2. 包含可能的技术方案、架构描述或工程实践
3. 不要加标题或 markdown 格式标记，直接写段落内容
4. 内容应与问题领域相关，包含可能出现在真实文档中的关键词和术语

假设文档："""


async def generate_hypothetical_document(query: str) -> str:
    """用 LLM 生成假设性文档（HyDE）。

    失败时返回空字符串，调用方应跳过 HyDE 检索路径。

    Args:
        query: 原始查询/冲突摘要

    Returns:
        假设性文档文本（200-300字），或空字符串（LLM 不可用时）
    """
    # 解析当前生效的 LLM 配置（支持租户级覆盖）
    from app.tenants.context import get_tenant_id
    from app.tenants.settings_override import resolve_llm_config

    _tid = get_tenant_id()
    base_url, api_key, model = resolve_llm_config(_tid, settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    if not base_url or not api_key:
        logger.debug("HyDE 跳过：LLM 未配置")
        return ""

    try:
        prompt = _HYDE_PROMPT.format(query=query[:500])  # 限制 query 长度

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,  # 低温度：生成稳定且相关的文档
                    "max_tokens": 400,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()

            # 清理：去掉可能的 markdown 标记和多余空行
            content = _clean_hypothetical_doc(content)
            if not content:
                logger.warning("HyDE 生成空文档")
                return ""

            logger.debug("HyDE 生成文档: %s...", content[:80])
            return content

    except Exception as e:
        logger.warning("HyDE 生成失败，跳过: %s", e)
        return ""


def _clean_hypothetical_doc(text: str) -> str:
    """清理假设性文档：去掉 markdown 标记、多余空行、前缀。"""
    # 去掉 markdown 标题标记
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    # 去掉 markdown 代码块
    text = re.sub(r"```(?:\w+)?\s*", "", text)
    text = text.replace("```", "")
    # 去掉可能的 "答：" / "假设文档：" 前缀
    text = re.sub(r"^(答[:：]|假设文档[:：]|文档[:：])\s*", "", text)
    # 压缩多余空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


async def hyde_retrieve(
    store: Any,
    query: str,
    top_k: int = 5,
) -> list[tuple[Any, float]]:
    """HyDE 检索：生成假设文档 → 用假设文档搜索向量库。

    Args:
        store: VectorStore 实例（需有 search 方法）
        query: 原始查询
        top_k: 返回结果数

    Returns:
        [(chunk, score), ...] 列表，或空列表（HyDE 失败时）
    """
    hypo_doc = await generate_hypothetical_document(query)
    if not hypo_doc:
        return []

    # 用假设文档作为查询（store.search 内部会 embed 并搜索）
    results: list[tuple[Any, float]] = list(await store.search(hypo_doc, top_k=top_k))
    return results
