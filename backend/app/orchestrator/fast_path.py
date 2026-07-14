"""Fast Path: 简单执行型任务跳过六阶段管线，直接单 Agent 处理。

分流决策核心原则：
- 不用关键词匹配（"简单来讲" ≠ 任务简单，"帮我" ≠ 简单查询）
- 向 LLM 发送 Conclave 完整系统上下文（能力、模式、约束），让 LLM 基于语义理解自主决策
- 系统提示词（Conclave 身份）→ 用户提示词（原始请求）→ 修正覆盖（API 显式指定）
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.logging_config import get_logger
from app.models import MeetingState, MeetingStatus
from app.config import settings
from app.orchestrator.system_prompt import (
    build_classification_prompt,
    parse_classification_result,
)

logger = get_logger("orchestrator.fast_path")


async def classify_intent_async(
    query: str,
    override_mode: str | None = None,
) -> str:
    """异步意图分流：向 LLM 发送 Conclave 完整系统上下文，让 LLM 自主决策。

    与之前的区别：
    - 不再使用关键词匹配或正则匹配
    - 不再使用多角色投票
    - 改为单次 LLM 调用，LLM 收到 Conclave 的完整能力清单后自主判断

    Args:
        query: 用户议题文本（原始，不修改）
        override_mode: API 显式指定的 flow_plan（如 "fast"），为空时无覆盖

    Returns:
        'fast_path'、'deep_think'、'plan' 或 'simple'
    """
    from app.agents.compute import get_compute, ThinkRequest

    # 构建系统提示词 + 用户提示词（明确分离）
    system_prompt, user_prompt = build_classification_prompt(
        user_query=query,
        override_mode=override_mode,
    )

    # 组合为单次 prompt：系统上下文在前，用户请求在后
    full_prompt = (
        f"{system_prompt}\n\n"
        f"─── 用户请求 ───\n"
        f"{user_prompt}\n\n"
        f"─── 输出格式要求 ───\n"
        f"请仅输出一个 JSON 对象，不要输出其他文字：\n"
        f'{{"mode": "fast_path|deep_think|plan|simple", "reason": "简短说明选择此模式的原因"}}'
    )

    try:
        compute = get_compute()
        resp = await compute.think(ThinkRequest(
            agent_role="moderator",
            stage="classify_intent",
            prompt=full_prompt,
            temperature=0.0,
            seed=settings.llm_seed,
        ))

        if resp.success and resp.result:
            result_text = ""
            if isinstance(resp.result, dict):
                result_text = resp.result.get("result", "")
                if not result_text:
                    result_text = str(resp.result)
            else:
                result_text = str(resp.result)

            parsed = parse_classification_result(result_text)
            mode = parsed["mode"]
            reason = parsed.get("reason", "")
            logger.info(
                "意图分类: mode=%s, reason=%s, query=%s",
                mode, reason, query[:60],
            )
            return mode

    except Exception as e:
        logger.warning("LLM 意图分类失败，默认走 deep_think: %s", e)

    return "deep_think"


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

    # 检测用户输入语言，决定回答语言
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in query)

    prompt = (
        f"请直接回答以下问题或完成以下请求。\n\n"
        f"用户请求：{query}\n\n"
        f"回答要求：\n"
        f"- 直接给出答案，不要询问澄清问题\n"
        f"- 使用与用户输入相同的语言回答{'（中文）' if has_chinese else ''}\n"
        f"- 如果需要，使用列表或分点说明，分点前加序号\n"
        f"- 保持专业、简洁、实用，但内容要足够详细有深度\n"
        f"- 如果用户请求涉及设计/规划/分析，给出结构化的方案\n"
        f"- 输出格式：纯文本或 Markdown"  # 不用 json_object，避免 Qwen 不兼容
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