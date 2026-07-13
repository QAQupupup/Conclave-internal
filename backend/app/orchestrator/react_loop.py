# ReAct 循环控制器：think → act → observe → think
#
# 设计原则（Claude 交叉评审共识）：
# - max_iterations 作为一等公民终态：不是异常，是正常的循环终止条件
# - 循环检测：连续两次相同工具+相同参数 → 判定卡死，终止
# - O(1) 上下文：每轮只带裁剪后的 tool_history，不带完整原始输出
# - 目标锚定：每轮 prompt 带原始任务 + 当前迭代序号
# - 工具执行隔离：工具异常不终止循环，记为 error 后继续
#
# 与 RefineLoop 的区别：
# - RefineLoop：LLM 只做"给定报错修正代码"，不做决策
# - ReactLoop：LLM 自主决定"下一步调用什么工具"，工具执行后 LLM 观察结果再决策
from __future__ import annotations

import os
import time
from typing import Any, Awaitable, Callable

from app.agents.compute import (
    AgentCompute,
    ThinkRequest,
    ThinkResponse,
    ToolCall,
    ToolResult,
    get_compute,
)
from app.observability.log_bus import log_bus

logger = log_bus  # 使用 LogBus 统一日志


# ---------- 工具注册表 ----------

ToolFn = Callable[[dict[str, Any]], Awaitable[Any]]


class ToolRegistry:
    """可被 Agent 调用的工具注册表

    使用方式：
        registry = ToolRegistry()
        registry.register("web_search", "搜索网络获取证据", search_fn,
                         {"query": "str", "top_k": "int"})
        registry.register("browser.goto", "导航到指定 URL", goto_fn,
                         {"url": "str"})
    """

    def __init__(self) -> None:
        self._tools: dict[str, dict[str, Any]] = {}

    def register(
        self,
        name: str,
        description: str,
        fn: ToolFn,
        parameters: dict[str, str] | None = None,
    ) -> None:
        """注册一个工具"""
        self._tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters or {},
            "fn": fn,
        }

    def get_available_tools(self) -> list[dict[str, Any]]:
        """返回工具描述列表（用于 ThinkRequest.available_tools）"""
        return [
            {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}
            for t in self._tools.values()
        ]

    async def execute(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        """执行一个工具调用"""
        t0 = time.monotonic()
        tool = self._tools.get(tool_name)
        if tool is None:
            return ToolResult(
                tool_name=tool_name,
                arguments=arguments,
                success=False,
                error=f"未知工具: {tool_name}",
                latency_ms=0,
            )
        try:
            result = await tool["fn"](arguments)
            return ToolResult(
                tool_name=tool_name,
                arguments=arguments,
                success=True,
                result=result,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception as e:
            return ToolResult(
                tool_name=tool_name,
                arguments=arguments,
                success=False,
                error=f"{type(e).__name__}: {e}",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )


# ---------- tool_history 裁剪（Phase B-4） ----------

def prune_tool_history(
    history: list[ToolResult],
    keep_full: int = 2,
    max_quote_tokens: int = 100,
) -> list[ToolResult]:
    """裁剪 tool_history：最近 keep_full 轮保留完整结果，更早的轮次折叠为摘要

    设计原则（Claude 交叉评审共识）：
    - 最近 2 轮保留完整 tool 输出
    - 更早的轮次折叠为结构化字段 + 最高 tier 证据的 raw quote（截断到 ~100 tokens）
    - 保持 O(1) 上下文增长

    Args:
        history: 完整的 ToolResult 列表
        keep_full: 保留完整结果的最近轮次数
        max_quote_tokens: 摘要中保留的 quote 最大 token 数（近似为字符数/4）
    Returns:
        裁剪后的 ToolResult 列表
    """
    if len(history) <= keep_full:
        return history

    # 分割：前面折叠，后面保留完整
    to_collapse = history[:-keep_full]
    to_keep = history[-keep_full:]

    collapsed: list[ToolResult] = []
    for tr in to_collapse:
        # 将 result 折叠为摘要
        summary = _summarize_tool_result(tr, max_quote_tokens * 4)
        collapsed.append(ToolResult(
            tool_name=tr.tool_name,
            arguments=tr.arguments,
            success=tr.success,
            result=summary,  # 摘要替代完整结果
            error=tr.error,
            latency_ms=tr.latency_ms,
            iteration=tr.iteration,
        ))

    return collapsed + to_keep


def _summarize_tool_result(tr: ToolResult, max_chars: int = 400) -> dict[str, Any]:
    """将 ToolResult.result 折叠为结构化摘要

    对于 web_search 结果：保留 evidence 数量 + 最高 tier + 第一条 quote（截断）
    对于 browser 操作：保留 status + 数据摘要
    """
    if not isinstance(tr.result, (list, dict)):
        return {"summary": str(tr.result)[:max_chars]}

    if isinstance(tr.result, list):
        # web_search 返回 evidence 列表
        count = len(tr.result)
        tiers = []
        first_quote = ""
        for item in tr.result:
            if isinstance(item, dict):
                tier = item.get("source_tier", item.get("signals", {}).get("effective_tier", "C"))
                tiers.append(tier)
                if not first_quote and item.get("quote"):
                    # 去掉定界符
                    q = item["quote"].replace("[EVIDENCE_DATA_BEGIN]", "").replace("[EVIDENCE_DATA_END]", "")
                    first_quote = q[:max_chars]
        best_tier = min(tiers) if tiers else "C"  # S < A < B < C < D
        return {
            "evidence_count": count,
            "best_tier": best_tier,
            "tier_distribution": {t: tiers.count(t) for t in set(tiers)},
            "first_quote_truncated": first_quote,
        }

    # dict 结果
    if isinstance(tr.result, dict):
        status = tr.result.get("status", tr.result.get("success", "unknown"))
        data = tr.result.get("data", tr.result.get("result", ""))
        return {
            "status": status,
            "data_summary": str(data)[:max_chars],
        }

    return {"summary": str(tr.result)[:max_chars]}


# ---------- 循环检测 ----------

def _is_loop_detected(tool_calls: list[ToolCall], history: list[ToolResult]) -> bool:
    """检测循环：连续两次相同工具+相同参数

    Args:
        tool_calls: 当前轮次的工具调用请求
        history: 历史工具调用结果
    Returns:
        True 如果检测到循环
    """
    if not tool_calls or not history:
        return False

    # 取最近一轮的工具调用
    last_results = []
    if history:
        last_iteration = history[-1].iteration
        last_results = [h for h in history if h.iteration == last_iteration]

    if len(last_results) != len(tool_calls):
        return False

    # 逐个比较工具名和参数
    for call, result in zip(tool_calls, last_results):
        if call.tool_name != result.tool_name:
            return False
        if call.arguments != result.arguments:
            return False

    return True


# ---------- ReAct 循环控制器 ----------

class ReactLoop:
    """ReAct 循环控制器：think → act → observe → think

    使用方式：
        registry = ToolRegistry()
        registry.register("web_search", ...)
        loop = ReactLoop(compute=get_compute(), tools=registry, meeting_id="m1")
        result = await loop.run(req, max_iterations=10)
    """

    # 默认最大迭代次数（可通过环境变量 REACT_MAX_ITERATIONS 覆盖）
    DEFAULT_MAX_ITERATIONS = int(os.environ.get("REACT_MAX_ITERATIONS", "10"))

    def __init__(
        self,
        compute: AgentCompute | None = None,
        tools: ToolRegistry | None = None,
        meeting_id: str = "",
    ) -> None:
        self._compute = compute or get_compute()
        self._tools = tools or ToolRegistry()
        self._meeting_id = meeting_id  # 用于注入到浏览器工具调用中

    async def run(
        self,
        req: ThinkRequest,
        max_iterations: int | None = None,
    ) -> ThinkResponse:
        """执行 ReAct 循环

        Args:
            req: 初始 ThinkRequest（prompt 中包含任务描述）
            max_iterations: 最大迭代次数（None 使用 DEFAULT_MAX_ITERATIONS）
        Returns:
            最终的 ThinkResponse（result 字段包含最终结论）
        """
        if max_iterations is None:
            max_iterations = self.DEFAULT_MAX_ITERATIONS
        # 注入 available_tools
        req.available_tools = self._tools.get_available_tools()

        tool_history: list[ToolResult] = []
        last_response: ThinkResponse | None = None

        for iteration in range(max_iterations):
            req.iteration = iteration
            # 裁剪 tool_history 注入 request
            req.tool_history = prune_tool_history(tool_history)

            # 记录每轮迭代
            log_bus.info(
                f"ReAct 迭代 {iteration + 1}/{max_iterations}",
                logger="orchestrator.react_loop",
                extra={
                    "stage": req.stage,
                    "iteration": iteration,
                    "tool_history_count": len(tool_history),
                },
            )

            # 1. Think
            response = await self._compute.think(req)
            last_response = response

            if not response.success:
                log_bus.warning(
                    f"ReAct think 失败: {response.error[:100]}",
                    logger="orchestrator.react_loop",
                    extra={"iteration": iteration, "error": response.error},
                )
                return response

            # 2. 检查是否需要继续
            if not response.need_continue or not response.tool_calls:
                # Agent 认为任务完成，无需继续
                log_bus.info(
                    f"ReAct 循环正常终止: iteration={iteration}, need_continue=False",
                    logger="orchestrator.react_loop",
                    extra={"stage": req.stage, "iterations_used": iteration + 1},
                )
                return response

            # 3. 循环检测
            if _is_loop_detected(response.tool_calls, tool_history):
                log_bus.warning(
                    "ReAct 循环检测: 连续两次相同工具调用，终止",
                    logger="orchestrator.react_loop",
                    extra={
                        "iteration": iteration,
                        "tool_calls": [tc.tool_name for tc in response.tool_calls],
                    },
                )
                # 返回当前响应，标记循环终止
                response.need_continue = False
                return response

            # 4. Act: 执行工具调用
            for call in response.tool_calls:
                # 注入 meeting_id（浏览器工具和工作区工具都需要）
                args = dict(call.arguments)
                if self._meeting_id:
                    # 所有工具都可能需要 meeting_id（用于文件隔离、浏览器上下文等）
                    args.setdefault("meeting_id", self._meeting_id)
                # 记录工具调用成本
                time.monotonic()
                result = await self._tools.execute(call.tool_name, args)
                result.iteration = iteration
                tool_history.append(result)

                # 记录到 CostTracker
                try:
                    from app.observability.cost_tracker import get_cost_tracker
                    get_cost_tracker().record_tool(
                        node=req.stage,
                        tool_name=call.tool_name,
                        latency_ms=result.latency_ms,
                        status="ok" if result.success else "error",
                        extra={"iteration": iteration, "arguments": call.arguments},
                    )
                except Exception:
                    pass

                log_bus.info(
                    f"ReAct 工具执行: {call.tool_name}",
                    logger="orchestrator.react_loop",
                    extra={
                        "tool_name": call.tool_name,
                        "success": result.success,
                        "latency_ms": result.latency_ms,
                        "iteration": iteration,
                    },
                )

            # 5. Observe: tool_history 已更新，下一轮 think 会看到

        # max_iterations 达到，作为一等公民终态
        log_bus.info(
            f"ReAct 达到 max_iterations={max_iterations}，正常终止",
            logger="orchestrator.react_loop",
            extra={"stage": req.stage, "max_iterations": max_iterations},
        )

        if last_response:
            last_response.need_continue = False
            # 在 result 中标注因 max_iterations 终止
            if isinstance(last_response.result, dict):
                last_response.result["_react_terminated"] = "max_iterations"
                last_response.result["_react_iterations_used"] = max_iterations
            return last_response

        # 不应该到达这里
        return ThinkResponse(
            success=False,
            error="ReAct 循环异常终止",
            validation_status="invalid",
        )


# ---------- 默认工具注册表工厂 ----------

def create_default_tool_registry() -> ToolRegistry:
    """创建默认工具注册表（web_search + browser 操作 + workspace 文件/命令工具）

    在 evidence_check 和 produce 节点中使用。
    """
    registry = ToolRegistry()

    # ========== 网络搜索工具 ==========
    async def _web_search(args: dict[str, Any]) -> Any:
        from app.tools.web_search import get_web_search
        query = args.get("query", "")
        top_k = args.get("top_k", 5)
        tool = get_web_search()
        # 传递可选参数：language, time_range, country
        kwargs: dict[str, Any] = {}
        for key in ("language", "time_range", "country"):
            if key in args and args[key]:
                kwargs[key] = args[key]
        return await tool.search(query, top_k, **kwargs)

    registry.register(
        "web_search",
        "搜索网络获取证据。返回证据列表，每条包含 quote（引用文本）、url、source_tier（S/A/B/C/D）、signals（信号袋）。"
        "支持中文搜索（默认）和英文搜索，可按时间过滤结果。",
        _web_search,
        {
            "query": "str（搜索查询）",
            "top_k": "int（最大结果数，默认5）",
            "language": "str（可选，搜索语言：zh-CN/en-US，默认zh-CN）",
            "time_range": "str（可选，时间过滤：day/week/month/year）",
        },
    )

    # web_fetch 工具：直接抓取指定 URL 内容
    async def _web_fetch(args: dict[str, Any]) -> Any:
        from app.tools.web_search import get_web_fetch
        url = args.get("url", "")
        max_chars = args.get("max_chars", 5000)
        tool = get_web_fetch()
        return await tool.fetch_url(url, max_chars)

    registry.register(
        "web_fetch",
        "直接抓取指定 URL 的网页内容，无需先搜索。当你已知具体网址（如从搜索结果中获得）时使用此工具获取详细内容。"
        "返回页面标题、正文内容、分块信息和来源评级。",
        _web_fetch,
        {
            "url": "str（要抓取的完整URL，如 https://example.com/doc）",
            "max_chars": "int（可选，最大返回字符数，默认5000）",
        },
    )

    # ---------- Browser 操作工具 ----------

    async def _browser_goto(args: dict[str, Any]) -> Any:
        from app.tools.browser_tool import get_browser_tool
        tool = get_browser_tool()
        url = str(args.get("url", ""))
        meeting_id = str(args.get("meeting_id", ""))
        return await tool.goto(meeting_id, url)

    registry.register(
        "browser.goto",
        "导航到指定 URL。返回页面标题和文本内容摘要（前3000字符），自动去除广告和导航栏。",
        _browser_goto,
        {"url": "str（目标网址）", "meeting_id": "str（会议ID，从上下文获取）"},
    )

    async def _browser_extract(args: dict[str, Any]) -> Any:
        from app.tools.browser_tool import get_browser_tool
        tool = get_browser_tool()
        meeting_id = str(args.get("meeting_id", ""))
        max_length = int(args.get("max_length", 5000))
        return await tool.extract_content(meeting_id, max_length)

    registry.register(
        "browser.extract",
        "提取当前页面的主要内容（去除广告、导航等噪音）。返回清洗后的文本。",
        _browser_extract,
        {"meeting_id": "str（会议ID）", "max_length": "int（最大字符数，默认5000）"},
    )

    async def _browser_click(args: dict[str, Any]) -> Any:
        from app.tools.browser_tool import get_browser_tool
        tool = get_browser_tool()
        meeting_id = str(args.get("meeting_id", ""))
        selector = str(args.get("selector", ""))
        return await tool.click(meeting_id, selector)

    registry.register(
        "browser.click",
        "点击页面上的元素。使用 CSS 选择器定位，如 'a.more', 'button.next', '#load-more'。",
        _browser_click,
        {"meeting_id": "str（会议ID）", "selector": "str（CSS选择器）"},
    )

    async def _browser_scroll(args: dict[str, Any]) -> Any:
        from app.tools.browser_tool import get_browser_tool
        tool = get_browser_tool()
        meeting_id = str(args.get("meeting_id", ""))
        amount = int(args.get("amount", 500))
        return await tool.scroll(meeting_id, "down", amount)

    registry.register(
        "browser.scroll",
        "向下滚动页面以加载更多内容（如无限滚动页面）。",
        _browser_scroll,
        {"meeting_id": "str（会议ID）", "amount": "int（滚动像素，默认500）"},
    )

    async def _browser_evaluate(args: dict[str, Any]) -> Any:
        from app.tools.browser_tool import get_browser_tool
        tool = get_browser_tool()
        meeting_id = str(args.get("meeting_id", ""))
        expression = str(args.get("expression", "document.title"))
        return await tool.evaluate(meeting_id, expression)

    registry.register(
        "browser.evaluate",
        "在页面中执行 JavaScript 表达式并返回结果。用于提取特定数据，如 'document.querySelector(\".price\").innerText'。",
        _browser_evaluate,
        {"meeting_id": "str（会议ID）", "expression": "str（JavaScript表达式）"},
    )

    # ========== 工作区文件/命令工具 ==========
    try:
        from app.tools.workspace_tools import register_workspace_tools
        register_workspace_tools(registry)
    except Exception as e:
        import logging
        logging.getLogger("orchestrator.react_loop").warning(
            "工作区工具注册失败: %s", str(e)[:200]
        )

    return registry
