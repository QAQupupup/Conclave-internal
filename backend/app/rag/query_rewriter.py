# 查询改写：用 LLM 生成多角度检索查询，提升召回率
# 原理：原始查询可能存在口语化/术语不一致等问题，
#       通过 LLM 生成 2 个改写查询 + 原始查询，三路召回合并去重
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import settings

_QUERY_REWRITE_PROMPT = """你是一个搜索查询优化器。请将以下查询改写为 2 个不同角度的搜索查询，以提高检索召回率。

原始查询：{query}

改写规则：
1. 查询1：提取关键词，使用更正式/技术化的术语，去除口语化表达
2. 查询2：从不同角度描述同一问题（如同义词替换、换个问法），保持语义不变

请严格按以下 JSON 格式输出，不要输出其他内容：
{{"queries": ["改写查询1", "改写查询2"]}}"""


async def rewrite_query(query: str) -> list[str]:
    """用 LLM 生成改写查询（失败时返回原始查询）

    返回原始查询 + 改写查询的列表，最多 3 个去重查询
    """
    if not settings.use_real_llm:
        return [query]

    try:
        prompt = _QUERY_REWRITE_PROMPT.format(query=query)

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.0,
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()

            # 提取 JSON
            parsed = _extract_json(content)
            rewritten = parsed.get("queries", []) if isinstance(parsed, dict) else []
            if not isinstance(rewritten, list):
                rewritten = []

            # 过滤空串和过长查询
            rewritten = [q.strip() for q in rewritten if q.strip() and len(q.strip()) < 500]

            # 合并原始查询 + 改写查询，去重
            all_queries = [query]
            for q in rewritten:
                if q not in all_queries and q != query:
                    all_queries.append(q)

            return all_queries[:3]  # 最多 3 个

    except Exception:
        return [query]  # 任何失败都回退到原始查询


def _extract_json(text: str) -> Any:
    """从 LLM 输出中提取 JSON（兼容 markdown 代码块包裹）"""
    # 去掉 markdown 代码块
    text = re.sub(r"```(?:json)?\s*", "", text)
    text = re.sub(r"```\s*$", "", text)
    text = text.strip()

    # 尝试找到 JSON 对象
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None