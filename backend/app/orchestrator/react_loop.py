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

import asyncio
import base64
import contextlib
import os
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

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
            # [Wave 7] 工具返回值清洗：外部内容（网页、搜索结果）可能含指令注入
            from app.orchestrator.prompt_safety import sanitize_tool_result

            sanitized_result = sanitize_tool_result(result)
            return ToolResult(
                tool_name=tool_name,
                arguments=arguments,
                success=True,
                result=sanitized_result,
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
        collapsed.append(
            ToolResult(
                tool_name=tr.tool_name,
                arguments=tr.arguments,
                success=tr.success,
                result=summary,  # 摘要替代完整结果
                error=tr.error,
                latency_ms=tr.latency_ms,
                iteration=tr.iteration,
            )
        )

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
    for call, result in zip(tool_calls, last_results, strict=False):
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
        on_tool_event: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._compute = compute or get_compute()
        self._tools = tools or ToolRegistry()
        self._meeting_id = meeting_id  # 用于注入到浏览器工具调用中
        self._on_tool_event = on_tool_event  # 工具事件回调（用于 WS 推送）

    def _make_step_callback(self, call_id: str, tool_name: str):
        """创建工具步骤回调，供 browser/web_search 工具推送中间步骤事件"""

        async def _cb(step_type: str, step_data: dict[str, Any]) -> None:
            if self._on_tool_event is None:
                return
            with contextlib.suppress(Exception):
                await self._on_tool_event(
                    "tool.step",
                    {
                        "call_id": call_id,
                        "tool_name": tool_name,
                        "step_type": step_type,
                        "data": step_data,
                        "ts": _now_iso(),
                    },
                )

        return _cb

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
                # [Wave 3] 安全：强制覆盖 meeting_id，防止 LLM 通过工具参数注入其他会议 ID
                # 旧代码用 setdefault 允许 LLM 覆盖 meeting_id，存在跨租户数据泄露风险
                args = dict(call.arguments)
                if self._meeting_id:
                    args["meeting_id"] = self._meeting_id  # 强制覆盖，不接受 LLM 提供的值

                # 生成工具调用 ID
                call_id = f"tool-{iteration}-{call.tool_name}-{id(call) & 0xFFFF:04x}"

                # 推送 tool.started 事件
                if self._on_tool_event is not None:
                    with contextlib.suppress(Exception):
                        await self._on_tool_event(
                            "tool.started",
                            {
                                "call_id": call_id,
                                "tool_name": call.tool_name,
                                "arguments": _sanitize_args(args),
                                "reason": call.reason,
                                "iteration": iteration,
                                "ts": _now_iso(),
                            },
                        )

                # 为 browser / 搜索 / 代码类工具注入步骤回调（tool.step 监控回放）
                if call.tool_name.startswith("browser.") or call.tool_name in (
                    "web_search",
                    "web_fetch",
                    "code.retrieve",
                    "code.structure",
                ):
                    args["_step_callback"] = self._make_step_callback(call_id, call.tool_name)

                t0 = time.monotonic()
                result = await self._tools.execute(call.tool_name, args)
                latency_ms = int((time.monotonic() - t0) * 1000)
                result.iteration = iteration
                result.latency_ms = latency_ms
                tool_history.append(result)

                # 推送 tool.completed / tool.failed 事件
                if self._on_tool_event is not None:
                    try:
                        event_type = "tool.completed" if result.success else "tool.failed"
                        await self._on_tool_event(
                            event_type,
                            {
                                "call_id": call_id,
                                "tool_name": call.tool_name,
                                "success": result.success,
                                "error": result.error[:500] if result.error else "",
                                "latency_ms": latency_ms,
                                "summary": _summarize_result(result.result, call.tool_name),
                                "ts": _now_iso(),
                            },
                        )
                    except Exception:
                        pass

                # 记录到 CostTracker
                try:
                    from app.observability.cost_tracker import get_cost_tracker

                    await get_cost_tracker().record_tool(
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


# ---------- 中间步骤事件（tool.step）发射助手 ----------

# 内联截图 base64 上限（约 200KB），防止 tool.step 事件过大拖垮 WS 与 DB
_STEP_SCREENSHOT_MAX_BYTES = 200 * 1024


async def _emit_step(step_cb: Any, step_type: str, data: dict[str, Any]) -> None:
    """安全调用步骤回调，未提供回调时静默跳过。

    step_cb 由 ReactLoop.run 经 args["_step_callback"] 注入，回调内部把
    tool.step 事件发布到事件总线（WS 推送 + PostgreSQL 持久化）。
    """
    if step_cb is None:
        return
    with contextlib.suppress(Exception):
        await step_cb(step_type, data)


async def _capture_step_screenshot(meeting_id: str) -> dict[str, str] | None:
    """为浏览器步骤捕获一张 viewport 截图（best-effort）。

    借鉴 Skyvern 的逐步截图记录思路。Phase 2：截图落盘到录制存储，返回
    {"ref": 文件名}；落盘关闭/失败时降级为 {"inline": base64}（有界）。
    调用方据此写 events 的 screenshot_ref / screenshot 字段，避免大 base64 进 events。
    """
    if not meeting_id:
        return None
    try:
        from app.tools.browser_tool import get_browser_tool

        shot = await get_browser_tool().screenshot(meeting_id, full_page=False)
        if shot.get("status") != "ok":
            return None
        b64 = shot.get("base64")
        if not b64:
            return None

        # Phase 2：优先落盘，events 只存引用
        from app.config import settings
        from app.services import recording_store

        if settings.recording_enabled:
            raw = base64.b64decode(b64)
            if raw and len(raw) <= settings.recording_max_screenshot_bytes:
                ref = recording_store.save_screenshot(meeting_id, raw)
                if ref:
                    return {"ref": ref}

        # 降级：有界内联 base64
        if len(b64) <= _STEP_SCREENSHOT_MAX_BYTES:
            return {"inline": b64}
        return None
    except Exception:
        return None


# ---------- 默认工具注册表工厂 ----------


def _clamp_int(value: Any, default: int, lo: int, hi: int) -> int:
    """把 LLM 传来的参数安全收敛为 [lo, hi] 内的 int。

    LLM 可能给字符串、浮点或越界值；一律兜底为默认值/边界，
    避免工具调用因参数类型错误直接失败。
    """
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(parsed, hi))


def create_default_tool_registry() -> ToolRegistry:
    """创建默认工具注册表（web_search + browser 操作 + workspace 文件/命令 + 代码检索工具）

    全部六个阶段节点（clarify/intra_team/cross_team/evidence_check/arbitrate/produce）
    经 _build_tool_registry() 共用本注册表，工具在所有流程环节可用。
    """
    registry = ToolRegistry()

    # ========== 网络搜索工具 ==========
    async def _web_search(args: dict[str, Any]) -> Any:
        from app.tools import get_web_search

        step_cb = args.get("_step_callback")
        query = args.get("query", "")
        top_k = args.get("top_k", 5)
        await _emit_step(step_cb, "search_started", {"label": f"搜索：{query}", "status": "running", "query": query})
        tool = get_web_search()
        # 传递可选参数：language, time_range, country, session_key
        kwargs: dict[str, Any] = {}
        for key in ("language", "time_range", "country"):
            if args.get(key):
                kwargs[key] = args[key]
        # 使用 meeting_id 作为 session_key，保证同一会议内搜索复用 Context
        meeting_id = args.get("meeting_id", "")
        if meeting_id:
            kwargs["session_key"] = str(meeting_id)
        result = await tool.search(query, top_k, **kwargs)
        count = len(result) if isinstance(result, list) else 0
        await _emit_step(
            step_cb, "results_found", {"label": f"找到 {count} 条结果", "status": "completed", "count": count}
        )
        return result

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
        from app.tools import get_web_fetch

        step_cb = args.get("_step_callback")
        url = args.get("url", "")
        max_chars = args.get("max_chars", 5000)
        await _emit_step(step_cb, "fetch_started", {"label": f"抓取：{url}", "status": "running", "url": url})
        tool = get_web_fetch()
        result = await tool.fetch_url(url, max_chars)
        await _emit_step(step_cb, "content_extracted", {"label": "正文提取完成", "status": "completed", "url": url})
        return result

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

        step_cb = args.get("_step_callback")
        tool = get_browser_tool()
        url = str(args.get("url", ""))
        meeting_id = str(args.get("meeting_id", ""))
        await _emit_step(step_cb, "navigating", {"label": f"导航到 {url}", "status": "running", "url": url})
        result = await tool.goto(meeting_id, url)
        final_url = str((result or {}).get("url") or url)
        title = str((result or {}).get("title") or "")
        step_data: dict[str, Any] = {"label": f"已打开 {title or final_url}", "status": "completed", "url": final_url}
        if title:
            step_data["title"] = title
        if (result or {}).get("status") != "ok":
            step_data["status"] = "failed"
            step_data["label"] = str((result or {}).get("error") or "导航失败")
        shot = await _capture_step_screenshot(meeting_id)
        if shot:
            if "ref" in shot:
                # 存相对 URL 路径（外链引用），前端据此带鉴权拉取截图
                step_data["screenshot_ref"] = f"/meetings/{meeting_id}/recordings/{shot['ref']}"
            elif "inline" in shot:
                step_data["screenshot"] = shot["inline"]
        await _emit_step(step_cb, "page_navigated", step_data)
        return result

    registry.register(
        "browser.goto",
        "导航到指定 URL。返回页面标题和文本内容摘要（前3000字符），自动去除广告和导航栏。",
        _browser_goto,
        {"url": "str（目标网址）", "meeting_id": "str（会议ID，从上下文获取）"},
    )

    async def _browser_extract(args: dict[str, Any]) -> Any:
        from app.tools.browser_tool import get_browser_tool

        step_cb = args.get("_step_callback")
        tool = get_browser_tool()
        meeting_id = str(args.get("meeting_id", ""))
        max_length = int(args.get("max_length", 5000))
        await _emit_step(step_cb, "extracting", {"label": "提取页面内容", "status": "running"})
        result = await tool.extract_content(meeting_id, max_length)
        await _emit_step(step_cb, "content_extracted", {"label": "内容提取完成", "status": "completed"})
        return result

    registry.register(
        "browser.extract",
        "提取当前页面的主要内容（去除广告、导航等噪音）。返回清洗后的文本。",
        _browser_extract,
        {"meeting_id": "str（会议ID）", "max_length": "int（最大字符数，默认5000）"},
    )

    async def _browser_click(args: dict[str, Any]) -> Any:
        from app.tools.browser_tool import get_browser_tool

        step_cb = args.get("_step_callback")
        tool = get_browser_tool()
        meeting_id = str(args.get("meeting_id", ""))
        selector = str(args.get("selector", ""))
        await _emit_step(step_cb, "clicking", {"label": f"点击 {selector}", "status": "running", "selector": selector})
        result = await tool.click(meeting_id, selector)
        await _emit_step(step_cb, "clicked", {"label": "点击完成", "status": "completed", "selector": selector})
        return result

    registry.register(
        "browser.click",
        "点击页面上的元素。使用 CSS 选择器定位，如 'a.more', 'button.next', '#load-more'。",
        _browser_click,
        {"meeting_id": "str（会议ID）", "selector": "str（CSS选择器）"},
    )

    async def _browser_scroll(args: dict[str, Any]) -> Any:
        from app.tools.browser_tool import get_browser_tool

        step_cb = args.get("_step_callback")
        tool = get_browser_tool()
        meeting_id = str(args.get("meeting_id", ""))
        amount = int(args.get("amount", 500))
        await _emit_step(step_cb, "scrolling", {"label": f"滚动 {amount}px", "status": "running", "amount": amount})
        result = await tool.scroll(meeting_id, "down", amount)
        await _emit_step(step_cb, "scrolled", {"label": "滚动完成", "status": "completed"})
        return result

    registry.register(
        "browser.scroll",
        "向下滚动页面以加载更多内容（如无限滚动页面）。",
        _browser_scroll,
        {"meeting_id": "str（会议ID）", "amount": "int（滚动像素，默认500）"},
    )

    async def _browser_evaluate(args: dict[str, Any]) -> Any:
        from app.tools.browser_tool import get_browser_tool

        step_cb = args.get("_step_callback")
        tool = get_browser_tool()
        meeting_id = str(args.get("meeting_id", ""))
        expression = str(args.get("expression", "document.title"))
        # [Wave 8] JS 表达式安全验证：阻断危险模式（fetch/cookie/eval 等）
        from app.orchestrator.prompt_safety import validate_js_expression

        is_safe, reason = validate_js_expression(expression)
        if not is_safe:
            log_bus.warning(
                f"browser.evaluate 被安全策略阻断: {reason}",
                logger="orchestrator.react_loop",
                extra={"expression_preview": expression[:100], "reason": reason},
            )
            await _emit_step(step_cb, "error", {"label": f"脚本被阻断：{reason}", "status": "failed", "reason": reason})
            return {"status": "blocked", "reason": reason, "expression": expression[:200]}
        await _emit_step(step_cb, "evaluating", {"label": "执行脚本", "status": "running"})
        result = await tool.evaluate(meeting_id, expression)
        await _emit_step(step_cb, "evaluated", {"label": "脚本执行完成", "status": "completed"})
        return result

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

        logging.getLogger("orchestrator.react_loop").warning("工作区工具注册失败: %s", str(e)[:200])

    # ========== 代码检索工具（ADR-016 Phase C，[P1 修复] 接入 Agent 工作流）==========
    # meeting_id 由 ReactLoop 强制注入（跨会议注入防护），检索范围天然限定本会议。
    # 会议未摄入代码时优雅降级为空结果，不报错。

    async def _code_retrieve(args: dict[str, Any]) -> Any:
        from app.rag.retriever import retrieve_code

        step_cb = args.get("_step_callback")
        meeting_id = str(args.get("meeting_id", ""))
        query = str(args.get("query", "")).strip()
        if not query:
            return {"status": "error", "error": "query 不能为空"}
        top_k = _clamp_int(args.get("top_k", 5), 5, 1, 50)
        max_hops = _clamp_int(args.get("max_hops", 1), 1, 0, 5)
        await _emit_step(
            step_cb,
            "code_search_started",
            {"label": f"代码检索：{query[:60]}", "status": "running", "query": query},
        )
        results = await retrieve_code(meeting_id, query, top_k=top_k, max_hops=max_hops)
        await _emit_step(
            step_cb,
            "code_search_done",
            {"label": f"命中 {len(results)} 个代码片段", "status": "completed", "count": len(results)},
        )
        return {"status": "ok", "count": len(results), "results": results}

    registry.register(
        "code.retrieve",
        "语义检索本会议已导入的代码仓库（向量召回 + 调用图扩展）。当需要定位与某个需求/缺陷/功能相关的代码实现时使用。"
        "返回相关代码片段列表（含文件路径与内容），图扩展命中的片段带 graph_hit 元数据。"
        "会议未导入代码或未建索引时返回空列表。",
        _code_retrieve,
        {
            "query": "str（检索查询，描述要找的逻辑，如：用户登录校验实现）",
            "top_k": "int（可选，返回条数，默认5，最大50）",
            "max_hops": "int（可选，沿调用图扩展的跳数，默认1，最大5）",
        },
    )

    async def _code_structure(args: dict[str, Any]) -> Any:
        from app.rag.graph_expand import structure_query

        step_cb = args.get("_step_callback")
        meeting_id = str(args.get("meeting_id", ""))
        node_id = str(args.get("node_id", "")).strip()
        if not node_id:
            return {"status": "error", "error": "node_id 不能为空"}
        max_hops = _clamp_int(args.get("max_hops", 1), 1, 0, 5)
        await _emit_step(
            step_cb,
            "structure_query_started",
            {"label": f"结构查询：{node_id[:60]}", "status": "running", "node_id": node_id},
        )
        # structure_query 是同步图遍历，放线程池避免阻塞事件循环（P1 异步纪律）
        result = await asyncio.to_thread(structure_query, meeting_id, node_id, max_hops=max_hops)
        # structure_query 返回 dict[str, object]，用 isinstance 收窄类型（mypy + 防御异常形状）
        callers_raw = result.get("callers")
        deps_raw = result.get("dependencies")
        callers = callers_raw if isinstance(callers_raw, list) else []
        deps = deps_raw if isinstance(deps_raw, list) else []
        await _emit_step(
            step_cb,
            "structure_query_done",
            {
                "label": f"调用方 {len(callers)} 个，依赖 {len(deps)} 个",
                "status": "completed",
                "callers": len(callers),
                "dependencies": len(deps),
            },
        )
        return {"status": "ok", **result}

    registry.register(
        "code.structure",
        "查询代码结构关系：给定符号/文件节点（限定名，如 a.py::ClassA::method_m），返回「谁调用它」（callers）与「它依赖谁」（dependencies）。"
        "用于评估改动影响面、理解调用链。node_id 可从 code.retrieve 的结果中获得。"
        "图索引未建立或节点不存在时返回空列表。",
        _code_structure,
        {
            "node_id": "str（符号/文件节点 ID，限定名格式，如 a.py::A::m）",
            "max_hops": "int（可选，图扩展最大跳数，默认1，最大5）",
        },
    )

    return registry


# ---------- 工具事件辅助函数 ----------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sanitize_args(args: dict[str, Any]) -> dict[str, Any]:
    """清洗工具参数，移除内部字段和敏感内容，截断长文本"""
    safe: dict[str, Any] = {}
    for k, v in args.items():
        if k.startswith("_"):
            continue  # 跳过内部回调等
        if isinstance(v, str) and len(v) > 500:
            safe[k] = v[:500] + "...(truncated)"
        else:
            safe[k] = v
    return safe


def _summarize_result(result: Any, tool_name: str) -> dict[str, Any]:
    """从工具返回值中提取摘要信息（不包含完整数据，用于前端快速展示）"""
    try:
        if result is None:
            return {"type": "empty"}
        if isinstance(result, list):
            # web_search 返回 evidence 列表
            if tool_name in ("web_search",):
                items = []
                for ev in result[:5]:
                    if isinstance(ev, dict):
                        items.append(
                            {
                                "url": ev.get("url", ""),
                                "title": (ev.get("signals") or {}).get("page_title", ""),
                                "source_tier": ev.get("source_tier", ""),
                                "domain": ev.get("domain", ""),
                            }
                        )
                return {"type": "search_results", "count": len(result), "items": items}
            return {"type": "list", "count": len(result)}
        if isinstance(result, dict):
            # 代码工具返回（优先于 browser 分支，避免 status=ok 被误判为浏览器动作）
            if tool_name == "code.retrieve":
                return {"type": "code_results", "count": result.get("count", 0)}
            if tool_name == "code.structure":
                return {
                    "type": "code_structure",
                    "node_id": result.get("node_id", ""),
                    "callers": len(result.get("callers") or []),
                    "dependencies": len(result.get("dependencies") or []),
                }
            status = result.get("status", "")
            if status in ("ok", "error", "captcha", "blocked"):
                # browser 工具返回
                summary: dict[str, Any] = {"type": "browser_action", "status": status}
                url = result.get("url") or (result.get("data") or {}).get("url", "")
                title = (result.get("data") or {}).get("title", "")
                if url:
                    summary["url"] = url
                if title:
                    summary["title"] = title[:100]
                if result.get("error"):
                    summary["error"] = str(result["error"])[:200]
                if result.get("base64"):
                    summary["has_screenshot"] = True
                return summary
            # web_fetch 返回
            if "content" in result or "chunks" in result:
                return {
                    "type": "page_content",
                    "url": result.get("url", ""),
                    "title": (result.get("signals") or {}).get("page_title", ""),
                    "content_length": len(str(result.get("content", ""))),
                }
            return {"type": "dict", "keys": list(result.keys())[:10]}
        return {"type": "value", "preview": str(result)[:200]}
    except Exception:
        return {"type": "unknown"}
