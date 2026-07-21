#!/usr/bin/env python3
"""
DeepResearchAgent — 内置于 Web Search Service 的自主研究 Agent

核心能力：
- Plan:   将研究主题分解为多角度搜索查询
- Search: 并行执行搜索，收集证据
- Evaluate: 评估结果的充分性，识别知识缺口
- Refine:  生成补全查询，迭代搜索
- Synthesize: 生成结构化研究报告（含引用）

架构：
    Topic → Plan(LLM) → Search(多轮) → Evaluate(LLM) → [缺口?] → Refine(LLM) → Search → ...
    → Synthesize(LLM) → StructuredReport

与 Conclave 主 Agent 的关系：
    - Conclave Agent 是"会议主持人"，负责议题讨论、参会者协调
    - DeepResearchAgent 是"研究助理"，专注于信息检索与证据收集
    - 两者通过 ToolPort 协议协作：Conclave 调用 /research 获取结构化证据
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("research_agent")

# ── 配置：通过 app.config.settings 统一加载（与主进程一致） ─────────
from app.config import settings
LLM_BASE_URL = settings.llm_base_url
LLM_API_KEY = settings.llm_api_key
LLM_MODEL = os.environ.get("CONCLAVE_RESEARCH_MODEL", "deepseek-ai/DeepSeek-V3.2")
MAX_RESEARCH_ROUNDS = int(os.environ.get("CONCLAVE_RESEARCH_MAX_ROUNDS", "3"))
QUERIES_PER_ROUND = int(os.environ.get("CONCLAVE_RESEARCH_QUERIES_PER_ROUND", "4"))
TOP_K_PER_QUERY = int(os.environ.get("CONCLAVE_RESEARCH_TOP_K", "3"))

# ── 数据模型 ──────────────────────────────────────────────────
class ResearchPhase(Enum):
    PLANNING = "planning"
    SEARCHING = "searching"
    EVALUATING = "evaluating"
    REFINING = "refining"
    SYNTHESIZING = "synthesizing"
    DONE = "done"
    FAILED = "failed"


@dataclass
class ResearchFinding:
    """单条研究发现"""
    claim: str
    source_url: str
    source_title: str
    source_tier: str  # S/A/B/C
    relevance: float = 0.5  # 0-1，Agent 评估的相关性


@dataclass
class ResearchRound:
    """一轮研究的结果"""
    round_num: int
    queries: list[str]
    findings: list[ResearchFinding] = field(default_factory=list)
    evaluation: str = ""  # Agent 的评估结论
    gaps: list[str] = field(default_factory=list)  # 识别到的知识缺口


@dataclass
class ResearchReport:
    """最终研究报告"""
    topic: str
    summary: str  # 2-3 句总结
    key_findings: list[dict[str, Any]]  # [{claim, sources, confidence}]
    detailed_analysis: str  # 详细分析（Markdown）
    sources: list[dict[str, str]]  # [{url, title, tier}]
    rounds: int
    total_time_ms: float
    confidence: str  # high/medium/low


# ── Agent 核心 ────────────────────────────────────────────────
class DeepResearchAgent:
    """自主研究 Agent：Plan → Search → Evaluate → Refine → Synthesize"""

    def __init__(self, search_func: Any):
        """
        Args:
            search_func: async callable(query, top_k, session_key, language) → list[dict]
        """
        self._search = search_func
        self._session_key = "research_agent"  # Agent 自己使用独立的 session

    async def research(self, topic: str, *, max_rounds: int = MAX_RESEARCH_ROUNDS) -> ResearchReport:
        """主入口：对 topic 执行完整的研究流程

        Args:
            topic: 研究主题（自然语言描述，如 "微服务架构中服务网格的优缺点"）
            max_rounds: 最大迭代轮数

        Returns:
            ResearchReport: 结构化研究报告
        """
        start_time = time.monotonic()
        all_findings: list[ResearchFinding] = []
        rounds: list[ResearchRound] = []

        logger.info("DeepResearchAgent 开始研究: topic=%s", topic[:80])

        # ── Phase 1: Plan ─────────────────────────────────────
        plan_queries = await self._plan_queries(topic)
        if not plan_queries:
            logger.warning("Plan 阶段未生成查询，使用默认查询")
            plan_queries = [topic]

        # ── Phase 2-4: Search → Evaluate → Refine 循环 ────────
        for round_num in range(1, max_rounds + 1):
            logger.info("Round %d/%d: 执行 %d 个查询", round_num, max_rounds, len(plan_queries))

            # Search
            findings = await self._execute_searches(plan_queries, round_num)
            all_findings.extend(findings)

            # Evaluate
            evaluation, gaps = await self._evaluate_results(topic, all_findings, round_num, max_rounds)

            research_round = ResearchRound(
                round_num=round_num,
                queries=plan_queries,
                findings=findings,
                evaluation=evaluation,
                gaps=gaps,
            )
            rounds.append(research_round)

            # 检查是否充分
            if not gaps or round_num >= max_rounds:
                logger.info("研究充分 (%d 轮, %d 条证据)，进入合成阶段",
                           round_num, len(all_findings))
                break

            # Refine: 用缺口生成下一轮查询
            logger.info("发现 %d 个知识缺口，生成补全查询...", len(gaps))
            plan_queries = await self._refine_queries(topic, gaps, all_findings)
            if not plan_queries:
                break

        # ── Phase 5: Synthesize ───────────────────────────────
        report = await self._synthesize(topic, all_findings, rounds)

        elapsed = (time.monotonic() - start_time) * 1000
        report.rounds = len(rounds)
        report.total_time_ms = elapsed

        logger.info("DeepResearchAgent 完成: topic=%s rounds=%d findings=%d time=%.0fms",
                    topic[:60], len(rounds), len(all_findings), elapsed)
        return report

    # ── 内部方法 ──────────────────────────────────────────────

    async def _plan_queries(self, topic: str) -> list[str]:
        """Phase 1: LLM 将主题分解为多角度搜索查询"""
        prompt = f"""You are a research strategist. Given a research topic, generate {QUERIES_PER_ROUND} diverse search queries that cover different angles.

Topic: "{topic}"

Instructions:
- Each query should explore a different aspect of the topic
- Queries should be in English (for better search quality)
- Use specific technical terms, not vague descriptions
- Include queries that search for: definitions, comparisons, pros/cons, latest developments, expert opinions

Output ONLY a JSON array of strings, no explanation:
["query1", "query2", "query3", "query4"]
"""
        queries = await self._call_llm(prompt, expect_json=True)
        if isinstance(queries, list) and len(queries) > 0:
            return [q for q in queries if isinstance(q, str) and len(q) > 3][:QUERIES_PER_ROUND]
        return []

    async def _execute_searches(self, queries: list[str], round_num: int) -> list[ResearchFinding]:
        """Phase 2: 并行执行搜索，收集证据"""
        tasks = [
            self._search(q, TOP_K_PER_QUERY, self._session_key, "en-US")
            for q in queries
        ]
        results_list = await asyncio.gather(*tasks, return_exceptions=True)

        findings: list[ResearchFinding] = []
        for query, results in zip(queries, results_list):
            if isinstance(results, Exception):
                logger.warning("搜索失败 [%s]: %s", query[:40], str(results)[:80])
                continue
            if not isinstance(results, list):
                continue
            for r in results:
                if not isinstance(r, dict):
                    continue
                quote = r.get("quote", "") or ""
                if len(quote) < 20:  # 过滤太短的摘要
                    continue
                findings.append(ResearchFinding(
                    claim=quote[:500],
                    source_url=r.get("url", ""),
                    source_title=r.get("signals", {}).get("title", ""),
                    source_tier=r.get("source_tier", "C"),
                ))

        # 去重（按 URL）
        seen: set[str] = set()
        unique = []
        for f in findings:
            if f.source_url and f.source_url not in seen:
                seen.add(f.source_url)
                unique.append(f)
            elif not f.source_url:
                unique.append(f)

        return unique

    async def _evaluate_results(
        self, topic: str, findings: list[ResearchFinding], round_num: int, max_rounds: int,
    ) -> tuple[str, list[str]]:
        """Phase 3: LLM 评估结果充分性，识别知识缺口"""
        if not findings:
            return "No results found.", ["retry with broader query"]

        # 构建证据摘要（限制长度避免超出上下文）
        evidence_summary = self._build_evidence_summary(findings, max_chars=3000)

        prompt = f"""You are a research evaluator. Assess whether the search results provide sufficient coverage of the topic.

Topic: "{topic}"
Round: {round_num}/{max_rounds}
Findings collected: {len(findings)}

Evidence summary:
{evidence_summary}

Evaluate:
1. Are the findings sufficient to answer the topic comprehensively? (yes/mostly/partially/no)
2. What key aspects are covered?
3. What important information is missing? (list specific gaps)

Output ONLY a JSON object:
{{"sufficiency": "yes|mostly|partially|no", "covered": "brief summary of what's covered", "gaps": ["gap1", "gap2"]}}
"""
        result = await self._call_llm(prompt, expect_json=True)
        if isinstance(result, dict):
            evaluation = result.get("covered", "")
            sufficiency = result.get("sufficiency", "partially")
            gaps = result.get("gaps", [])

            # 如果充分或已是最后一轮，不返回缺口
            if sufficiency in ("yes", "mostly") or round_num >= max_rounds:
                return evaluation, []

            return evaluation, gaps[:3]  # 最多 3 个缺口

        return "Evaluation unavailable.", []

    async def _refine_queries(
        self, topic: str, gaps: list[str], findings: list[ResearchFinding],
    ) -> list[str]:
        """Phase 4: LLM 根据缺口生成补全查询"""
        if not gaps:
            return []

        evidence_summary = self._build_evidence_summary(findings, max_chars=1500)

        prompt = f"""You are a research strategist. Generate {QUERIES_PER_ROUND} search queries to fill knowledge gaps.

Topic: "{topic}"
Existing coverage:
{evidence_summary}

Knowledge gaps to fill:
{json.dumps(gaps, ensure_ascii=False)}

Generate specific, targeted search queries (in English). Each query should address one or more gaps.
Output ONLY a JSON array of strings:
["query1", "query2", "query3"]
"""
        queries = await self._call_llm(prompt, expect_json=True)
        if isinstance(queries, list):
            return [q for q in queries if isinstance(q, str) and len(q) > 3][:QUERIES_PER_ROUND]
        return []

    async def _synthesize(
        self, topic: str, findings: list[ResearchFinding], rounds: list[ResearchRound],
    ) -> ResearchReport:
        """Phase 5: LLM 合成结构化研究报告"""
        if not findings:
            return ResearchReport(
                topic=topic,
                summary="No relevant information found.",
                key_findings=[],
                detailed_analysis="The search did not return sufficient results to produce a meaningful analysis.",
                sources=[],
                rounds=len(rounds),
                total_time_ms=0,
                confidence="low",
            )

        evidence_summary = self._build_evidence_summary(findings, max_chars=5000)

        prompt = f"""You are a research analyst. Synthesize the following search results into a structured research report.

Topic: "{topic}"
Search rounds: {len(rounds)}
Total sources: {len(findings)}

Evidence:
{evidence_summary}

Produce a JSON report with the following structure:
{{
  "summary": "2-3 sentence executive summary of the key findings",
  "key_findings": [
    {{"claim": "specific finding with details", "sources": ["url1", "url2"], "confidence": "high|medium|low"}}
  ],
  "detailed_analysis": "A comprehensive markdown-formatted analysis with sections. Include specific facts, comparisons, and citations. Length: 300-800 words.",
  "confidence": "high|medium|low"
}}

Rules:
- Every claim in key_findings MUST be backed by at least one source URL
- detailed_analysis should cite sources inline using [1], [2] format
- Be precise and factual, not speculative
- If evidence is contradictory, note both sides

Output ONLY the JSON object, no markdown wrapping:
"""
        result = await self._call_llm(prompt, expect_json=True, max_tokens=2000)

        if isinstance(result, dict):
            # 构建来源列表
            seen_urls: set[str] = set()
            sources = []
            for f in findings:
                if f.source_url and f.source_url not in seen_urls:
                    seen_urls.add(f.source_url)
                    sources.append({
                        "url": f.source_url,
                        "title": f.source_title,
                        "tier": f.source_tier,
                    })

            return ResearchReport(
                topic=topic,
                summary=result.get("summary", ""),
                key_findings=result.get("key_findings", []),
                detailed_analysis=result.get("detailed_analysis", ""),
                sources=sources[:20],  # 最多 20 个来源
                rounds=len(rounds),
                total_time_ms=0,  # 由调用方设置
                confidence=result.get("confidence", "medium"),
            )

        # LLM 返回无效 JSON，构建降级报告
        return ResearchReport(
            topic=topic,
            summary=f"Research completed with {len(findings)} sources across {len(rounds)} rounds.",
            key_findings=[
                {"claim": f.claim[:200], "sources": [f.source_url], "confidence": "medium"}
                for f in findings[:5]
            ],
            detailed_analysis=self._build_evidence_summary(findings, max_chars=2000),
            sources=[{"url": f.source_url, "title": f.source_title, "tier": f.source_tier}
                      for f in findings[:10]],
            rounds=len(rounds),
            total_time_ms=0,
            confidence="low",
        )

    # ── 工具方法 ──────────────────────────────────────────────

    def _build_evidence_summary(self, findings: list[ResearchFinding], max_chars: int = 3000) -> str:
        """构建证据摘要文本（限制长度）"""
        lines = []
        total = 0
        for i, f in enumerate(findings[:20], 1):  # 最多 20 条
            line = f"[{i}] [{f.source_tier}] {f.claim[:150]}"
            if f.source_title:
                line += f" (from: {f.source_title[:60]})"
            if total + len(line) > max_chars:
                break
            lines.append(line)
            total += len(line) + 1
        return "\n".join(lines)

    async def _call_llm(
        self, prompt: str, *, expect_json: bool = False, max_tokens: int = 1000,
    ) -> Any:
        """调用 LLM（复用 SiliconFlow API）"""
        if not LLM_API_KEY:
            logger.warning("LLM API key 未配置，Agent 无法调用")
            return [] if expect_json else ""

        try:
            import httpx

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{LLM_BASE_URL}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {LLM_API_KEY}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": LLM_MODEL,
                        "messages": [{"role": "user", "content": prompt}],
                        "max_tokens": max_tokens,
                        "temperature": 0.3,
                        "stream": False,
                    },
                )

                if resp.status_code != 200:
                    logger.warning("LLM 调用失败 (%d): %s", resp.status_code, resp.text[:200])
                    return [] if expect_json else ""

                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()

                if expect_json:
                    return self._parse_json(content)
                return content

        except Exception as e:
            logger.warning("LLM 调用异常: %s", str(e)[:100])
            return [] if expect_json else ""

    @staticmethod
    def _parse_json(text: str) -> Any:
        """鲁棒 JSON 解析：处理 LLM 可能输出的 markdown 包裹"""
        import re

        text = text.strip()

        # 尝试直接解析
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # 尝试提取 ```json ... ``` 代码块
        m = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if m:
            try:
                return json.loads(m.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试提取第一个 { 到最后一个 } 的 JSON 对象
        m = re.search(r'\{[\s\S]*\}', text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

        # 尝试提取第一个 [ 到最后一个 ] 的 JSON 数组
        m = re.search(r'\[[\s\S]*\]', text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

        logger.warning("JSON 解析失败: %s...", text[:200])
        return None


# ── 单例 ──────────────────────────────────────────────────────
_agent: DeepResearchAgent | None = None


def get_research_agent(search_func: Any) -> DeepResearchAgent:
    """获取 ResearchAgent 单例"""
    global _agent
    if _agent is None:
        _agent = DeepResearchAgent(search_func)
    return _agent