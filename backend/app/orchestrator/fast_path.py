"""Fast Path: 简单执行型任务跳过六阶段管线，直接单 Agent 处理。

适用场景：
- "帮我查一下 X"
- "总结一下 Y"
- "解释 Z 是什么"
- 单步问答型任务，不需要多 Agent 协商

分流决策由 classify_intent() 完成，使用轻量级 LLM 调用（低 token 成本）。
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.logging_config import get_logger
from app.models import MeetingState, MeetingStatus
from app.config import settings

logger = get_logger("orchestrator.fast_path")

# 关键词表：fast_path 倾向（简单查询/执行型）
_FAST_KEYWORDS = [
    "查一下", "查询", "总结", "概括", "归纳",
    "解释", "是什么", "什么是",
    "帮我", "帮我看", "帮我查",
    "简单", "简要", "直接",
    "告诉我", "列出", "描述",
    "翻译", "定义", "介绍",
    "怎么样", "如何", "请问",
    "谁", "哪个", "多少",
    "search", "find", "look up",
    "summarize", "explain", "what is",
]

# 关键词表：deep_think 倾向（多 Agent 协商型）
_DEEP_KEYWORDS = [
    "设计", "架构", "对比", "方案", "决策",
    "规划", "分析", "评估", "优化",
    "权衡", "取舍", "trade-off",
    "完整", "全面", "系统性",
    "多角色", "多方", "跨团队",
    "深度", "详细", "彻底",
    "design", "architecture", "compare",
    "evaluate", "tradeoff", "plan",
]


def classify_intent(query: str) -> str:
    """对议题进行意图分流，返回 'fast_path' 或 'deep_think'。

    先用关键词匹配做轻量判断（零 token 成本），
    信号不明确时可选用 LLM 做二次分类（低 token 成本）。

    Args:
        query: 会议议题文本

    Returns:
        'fast_path' 表示走快速路径，'deep_think' 表示走完整六阶段管线
    """
    q = query.lower()

    fast_score = sum(1 for kw in _FAST_KEYWORDS if kw in q)
    deep_score = sum(1 for kw in _DEEP_KEYWORDS if kw in q)

    # 有明确信号时直接决策
    if fast_score > 0 and deep_score == 0:
        return "fast_path"
    if deep_score > 0 and fast_score == 0:
        return "deep_think"

    # 双方都有信号时，分差明显则直接判断
    if fast_score > deep_score + 1:
        return "fast_path"
    if deep_score > fast_score + 1:
        return "deep_think"

    # 无任何关键词命中时默认走完整流程（保守策略）
    if fast_score == 0 and deep_score == 0:
        return "deep_think"

    # 信号不明确时，偏向快速路径（有至少一个关键词命中）
    if fast_score >= deep_score:
        return "fast_path"
    return "deep_think"


async def classify_intent_async(query: str) -> str:
    """异步意图分流：先关键词，信号不明确时用 LLM 做二次分类。

    与 classify_intent() 的区别：信号不明确时会调用 LLM（低 token 成本）
    做二次确认。适合在 Runner.run() 的 async 上下文中使用。

    Args:
        query: 会议议题文本

    Returns:
        'fast_path' 或 'deep_think'
    """
    q = query.lower()

    fast_score = sum(1 for kw in _FAST_KEYWORDS if kw in q)
    deep_score = sum(1 for kw in _DEEP_KEYWORDS if kw in q)

    # 有明确信号时直接决策（零 token 成本）
    if fast_score > 0 and deep_score == 0:
        return "fast_path"
    if deep_score > 0 and fast_score == 0:
        return "deep_think"
    if fast_score > deep_score + 1:
        return "fast_path"
    if deep_score > fast_score + 1:
        return "deep_think"

    # 信号不明确：LLM 二次分类
    if fast_score > 0 or deep_score > 0:
        try:
            return await _llm_classify(query)
        except Exception as e:
            logger.warning("LLM 意图分类失败，回退到启发式: %s", e)

    # 无任何关键词命中时默认走完整流程（保守策略）
    if fast_score == 0 and deep_score == 0:
        return "deep_think"

    return "fast_path" if fast_score >= deep_score else "deep_think"


async def _llm_classify(query: str) -> str:
    """用轻量级 LLM 调用做意图二次分类。

    使用极短 prompt + 低 max_tokens，token 成本约 ~100。
    """
    from app.agents.compute import get_compute, ThinkRequest

    prompt = (
        f"请判断以下议题是否需要多角色讨论才能得出好结论。\n\n"
        f"议题：{query[:500]}\n\n"
        f"只需回复一个词：\n"
        f"- 回复 'simple'：简单查询/执行型，单个助手即可回答\n"
        f"- 回复 'complex'：需要多角度分析、多角色协商讨论"
    )

    compute = get_compute()
    resp = await compute.think(ThinkRequest(
        agent_role="moderator",
        stage="classify_intent",
        prompt=prompt,
        temperature=0.0,
        seed=settings.llm_seed,
    ))

    if resp.success and resp.result:
        result_text = str(resp.result.get("result", "")).lower()
        if "complex" in result_text:
            return "deep_think"
        if "simple" in result_text:
            return "fast_path"

    # 默认走快速路径（LLM 无法明确判断时偏向快速）
    return "fast_path"


async def run_fast_path(query: str, state: MeetingState) -> MeetingState:
    """执行快速路径：单次 LLM 调用，以主持人身份直接回答。

    适用于简单查询/执行型任务，跳过六阶段管线。
    结果写入 state.artifact，状态直接置为 DONE。

    Args:
        query: 用户议题文本
        state: 当前会议状态对象（就地修改并返回）

    Returns:
        更新后的 MeetingState（status=DONE 或 FAILED）
    """
    from app.agents.compute import get_compute, ThinkRequest
    from app.events import bus, make_event
    from app.observability.log_bus import log_bus
    import time

    t0 = time.monotonic()

    prompt = (
        f"请直接回答以下问题或完成以下请求。用清晰、结构化的方式回答。\n\n"
        f"用户请求：{query}\n\n"
        f"回答要求：\n"
        f"- 直接给出答案，不要询问澄清问题\n"
        f"- 如果需要，使用列表或分点说明\n"
        f"- 保持专业、简洁、实用\n"
        f"- 输出格式：纯文本或 Markdown"
    )

    try:
        compute = get_compute()
        resp = await compute.think(ThinkRequest(
            agent_role="moderator",
            stage="fast_path",
            prompt=prompt,
            temperature=0.3,
            seed=settings.llm_seed,
        ))

        elapsed = time.monotonic() - t0

        if resp.success:
            # 从 LLM 结果中提取回答文本
            result = resp.result
            if isinstance(result, dict):
                answer = result.get("result", "") or result.get("answer", "")
                if not answer:
                    # 兜底：取第一个字符串类型的值
                    for v in result.values():
                        if isinstance(v, str) and len(v) > 10:
                            answer = v
                            break
            else:
                answer = str(result)

            if not answer:
                answer = "（无法生成回答）"

            # 写入 artifact（快速路径产出）
            state.artifact = {
                "title": f"快速回答：{query[:50]}",
                "answer": answer,
                "flow": "fast_path",
                "latency_ms": int(elapsed * 1000),
            }
            state.status = MeetingStatus.DONE
            state.completed_at = datetime.now(timezone.utc)
            state.flow_plan = "fast"

            # 发布事件通知前端
            await bus.publish(
                make_event(
                    "fast_path.completed",
                    state.meeting_id,
                    {
                        "meeting_id": state.meeting_id,
                        "artifact": state.artifact,
                        "elapsed_ms": int(elapsed * 1000),
                    },
                )
            )

            log_bus.info(
                f"Fast Path 完成: meeting={state.meeting_id}, elapsed={elapsed:.2f}s",
                logger="orchestrator.fast_path",
                extra={
                    "meeting_id": state.meeting_id,
                    "elapsed_s": round(elapsed, 2),
                    "answer_length": len(answer),
                },
            )
            logger.info(
                "Fast Path 完成: meeting=%s, elapsed=%.2fs",
                state.meeting_id, elapsed,
            )
        else:
            # LLM 调用失败
            elapsed = time.monotonic() - t0
            state.status = MeetingStatus.FAILED
            state.error_detail = f"Fast Path LLM 调用失败: {resp.error}"
            state.completed_at = datetime.now(timezone.utc)
            logger.warning(
                "Fast Path LLM 调用失败: meeting=%s, error=%s",
                state.meeting_id, resp.error,
            )
            log_bus.warning(
                f"Fast Path LLM 失败: {resp.error}",
                logger="orchestrator.fast_path",
                extra={"meeting_id": state.meeting_id, "error": resp.error},
            )

    except Exception as e:
        elapsed = time.monotonic() - t0
        state.status = MeetingStatus.FAILED
        state.error_detail = f"Fast Path 执行异常: {str(e)[:2000]}"
        state.completed_at = datetime.now(timezone.utc)
        logger.error(
            "Fast Path 执行异常: meeting=%s, error=%s",
            state.meeting_id, e, exc_info=True,
        )
        log_bus.error(
            f"Fast Path 异常: {e}",
            logger="orchestrator.fast_path",
            extra={"meeting_id": state.meeting_id, "error": str(e)[:500]},
        )

    return state
