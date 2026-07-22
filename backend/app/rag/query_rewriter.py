# 查询改写：用 LLM 生成多角度检索查询，提升召回率
# 原理：原始查询可能存在口语化/术语不一致等问题，
#       通过 LLM 生成 2 个改写查询 + 原始查询，三路召回合并去重
from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("rag.query_rewriter")

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

    异常处理策略：
    - LLM 调用失败（网络/超时/HTTP 错误）：warning 日志 + 回退原始查询
    - JSON 解析失败：warning 日志 + 回退原始查询
    - 改写结果为空/无效：debug 日志 + 回退原始查询
    所有回退都有日志，确保审计可追溯。
    """
    # 解析当前生效的 LLM 配置（支持租户级覆盖）
    from app.tenants.context import get_tenant_id
    from app.tenants.settings_override import resolve_llm_config

    _tid = get_tenant_id()
    base_url, api_key, model = resolve_llm_config(_tid, settings.llm_base_url, settings.llm_api_key, settings.llm_model)
    if not base_url or not api_key:
        logger.debug("查询改写跳过：LLM 未配置 (tenant_id=%s)", _tid)
        return [query]

    try:
        prompt = _QUERY_REWRITE_PROMPT.format(query=query)

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
                    "temperature": 0.0,
                    "max_tokens": 200,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()

            # 提取 JSON
            parsed = _extract_json(content)
            if parsed is None:
                logger.warning(
                    "查询改写 JSON 解析失败，回退原始查询: model=%s, content=%s",
                    model,
                    content[:200],
                )
                return [query]

            rewritten = parsed.get("queries", []) if isinstance(parsed, dict) else []
            if not isinstance(rewritten, list):
                logger.warning(
                    "查询改写结果格式异常（queries 不是 list），回退原始查询: parsed=%s",
                    str(parsed)[:200],
                )
                return [query]

            # 过滤空串和过长查询
            rewritten = [q.strip() for q in rewritten if q.strip() and len(q.strip()) < 500]

            # 合并原始查询 + 改写查询，去重
            all_queries = [query]
            for q in rewritten:
                if q not in all_queries and q != query:
                    all_queries.append(q)

            result = all_queries[:3]  # 最多 3 个
            logger.info(
                "查询改写成功: 原始=%s..., 改写=%d 条, 返回=%d 路",
                query[:60],
                len(rewritten),
                len(result),
            )
            return result

    except httpx.TimeoutException as e:
        logger.warning(
            "查询改写超时，回退原始查询: model=%s, timeout=15s, error=%s",
            model,
            e,
        )
        return [query]
    except httpx.HTTPStatusError as e:
        logger.warning(
            "查询改写 HTTP 错误，回退原始查询: model=%s, status=%d, error=%s",
            model,
            e.response.status_code,
            str(e)[:200],
        )
        return [query]
    except (KeyError, IndexError) as e:
        logger.warning(
            "查询改写响应解析失败（结构异常），回退原始查询: model=%s, error=%s: %s",
            model,
            type(e).__name__,
            e,
        )
        return [query]
    except Exception as e:
        logger.warning(
            "查询改写未知异常，回退原始查询: model=%s, error=%s: %s",
            model,
            type(e).__name__,
            str(e)[:200],
        )
        return [query]


def _extract_json(text: str) -> Any:
    """从 LLM 输出中提取 JSON（兼容多种格式）

    处理策略（按优先级尝试）：
    1. 去掉 markdown 代码块后直接 json.loads
    2. 正则提取第一个 JSON 对象 {...}
    3. 正则提取 JSON 数组 [...]
    4. 全部失败返回 None

    常见失败场景：
    - LLM 返回前后有解释性文本（"好的，结果如下：{...}"）
    - markdown 代码块包裹（```json\\n{...}\\n```）
    - LLM 返回多行 JSON 但有尾随逗号
    """
    if not text:
        return None

    # 去掉 markdown 代码块
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"```\s*$", "", cleaned)
    cleaned = cleaned.strip()

    # 策略 1：直接解析（最理想情况）
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 策略 2：正则提取第一个 JSON 对象
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            # 尝试修复常见 JSON 格式问题：尾随逗号
            fixed = re.sub(r",\s*}", "}", match.group())
            fixed = re.sub(r",\s*]", "]", fixed)
            try:
                return json.loads(fixed)
            except json.JSONDecodeError:
                pass

    # 策略 3：正则提取 JSON 数组
    match = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None
