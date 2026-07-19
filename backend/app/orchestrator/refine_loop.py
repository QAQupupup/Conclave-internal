# RefineLoop：代码自修复循环（受控 Re-Execution 模式）
# 设计原则：
# - LLM 只做"给定报错修正代码"，不做"决策下一步"
# - 每轮上下文 O(1)：只带上一轮最终代码 + 报错，不带完整历史
# - max_rounds 硬上限作为物理兜底
# - 重复检测：连续两轮生成相同代码 → 判定卡死，终止
# - 目标锚定：每轮 prompt 带原始任务 + 当前状态
from __future__ import annotations

from typing import Any

from app.agents.llm import get_llm
from app.logging_config import get_logger
from app.observability.log_bus import log_bus

logger = get_logger("orchestrator.refine_loop")

# Refine prompt 模板：只让 LLM 修正，不重写
REFINE_PROMPT = """[阶段: CodeRefine]
任务锚点：{task_summary}
当前代码（执行失败）：
```python
{current_code}
```
执行报错：
```
{error_output}
```
要求：只修改导致报错的部分，不要重写整个文件。保持其他逻辑不变。
输出 JSON: {{"code": "修正后的完整代码"}}"""


def _summarize_task(deliverable_type: str, result: dict[str, Any]) -> str:
    """生成任务锚点摘要（三句话：任务是什么 + 已完成什么 + 当前问题）"""
    if deliverable_type == "code_analysis":
        desc = (result.get("code_analysis") or {}).get("description", "")
        return f"数据分析任务：{desc}。生成代码执行失败，需要修正。"
    elif deliverable_type == "tested_system":
        desc = (result.get("tested_system") or {}).get("description", "")
        return f"测试系统任务：{desc}。测试执行失败，需要修正代码。"
    return "代码执行任务。执行失败，需要修正。"


async def refine_python_code(
    initial_code: str,
    task_summary: str,
    run_fn,
    max_rounds: int = 5,
    meeting_id: str = "",
    stage: str = "produce",
    detected_level: str = "L1",
) -> dict[str, Any]:
    """代码自修复循环

    参数:
        initial_code: 初始代码
        task_summary: 任务锚点摘要
        run_fn: async def(code) -> {exit_code, stdout, stderr}
        max_rounds: 最大修复轮次
        meeting_id: 会议 ID（用于网络授权申请）
        stage: 当前阶段
        detected_level: 当前检测到的网络级别

    返回:
        {code, execution, rounds_used, success, net_auth?: dict}
    """
    current_code = initial_code
    last_result = None
    llm = get_llm()
    current_net_level = detected_level
    net_auth_info = None

    log_bus.info(
        "RefineLoop 开始",
        logger="orchestrator.refine_loop",
        extra={"max_rounds": max_rounds, "task_summary": task_summary[:100]},
    )

    for round_idx in range(1, max_rounds + 1):
        # 执行当前代码
        last_result = await run_fn(current_code)
        exit_code = last_result.get("exit_code", -1)
        stdout = last_result.get("stdout", "")
        stderr = last_result.get("stderr", "")

        logger.info("RefineLoop round=%d exit_code=%d", round_idx, exit_code)

        # 成功条件：exit_code==0 且有输出
        if exit_code == 0 and stdout:
            log_bus.info(
                f"RefineLoop 成功 round={round_idx}",
                logger="orchestrator.refine_loop",
                extra={"rounds_used": round_idx, "exit_code": exit_code},
            )
            return {
                "code": current_code,
                "execution": last_result,
                "rounds_used": round_idx,
                "success": True,
                **({"net_auth": net_auth_info} if net_auth_info else {}),
            }

        # ---- 网络授权检测 ----
        # 失败时先检测是否是网络限制导致
        if meeting_id and current_net_level == "L1":
            try:
                from app.net_auth_manager import detect_network_failure, request_network_access

                net_reason = detect_network_failure(stderr, exit_code, current_code)
                if net_reason:
                    log_bus.info(
                        f"RefineLoop 检测到网络限制，发起授权申请: {net_reason}",
                        logger="orchestrator.refine_loop",
                    )
                    auth_result = await request_network_access(
                        meeting_id=meeting_id,
                        stage=stage,
                        code=current_code,
                        detected_level=current_net_level,
                        failure_reason=net_reason,
                        stderr=stderr,
                    )
                    net_auth_info = auth_result

                    if auth_result.get("approved"):
                        # 获批：用新网络级别重新执行（不消耗 round）
                        approved_level = auth_result["level"]
                        log_bus.info(
                            f"网络授权获批 level={approved_level}，重新执行",
                            logger="orchestrator.refine_loop",
                        )
                        # 通过闭包更新 run_fn 的网络级别
                        # run_fn 是 produce_node 传入的闭包，无法直接改网络级别
                        # 所以这里直接返回，让 produce_node 用新级别重试
                        return {
                            "code": current_code,
                            "execution": last_result,
                            "rounds_used": round_idx,
                            "success": False,
                            "net_auth": auth_result,
                            "need_retry_with_level": approved_level,
                        }
                    else:
                        # 未获批：继续走 LLM 修正（可能改代码去掉网络依赖）
                        log_bus.warning(
                            "网络授权未获批，继续修正代码",
                            logger="orchestrator.refine_loop",
                        )
            except Exception as e:
                logger.warning("网络授权检测异常: %s", e)

        # 最后一轮不调 LLM（没机会改了）
        if round_idx >= max_rounds:
            break

        # 失败：把报错喂给 LLM 修正
        error_output = stderr or stdout or f"exit_code={exit_code}, 无错误输出"
        prompt = REFINE_PROMPT.format(
            task_summary=task_summary,
            current_code=current_code,
            error_output=error_output[:2000],  # 截断超长报错
        )

        try:
            result = await llm.complete(prompt, schema_hint="")
            refined_code = result.get("code", "")
            if not refined_code:
                logger.warning("RefineLoop round=%d LLM 未返回代码", round_idx)
                break

            # 重复检测：连续两轮相同代码 → 卡死
            if refined_code.strip() == current_code.strip():
                logger.warning("RefineLoop round=%d 代码未变化，终止", round_idx)
                log_bus.info(
                    f"RefineLoop 重复检测终止 round={round_idx}",
                    logger="orchestrator.refine_loop",
                )
                break

            current_code = refined_code
            log_bus.info(
                f"RefineLoop 修正完成 round={round_idx}",
                logger="orchestrator.refine_loop",
                extra={"round": round_idx, "code_len": len(current_code)},
            )
        except Exception as e:
            logger.error("RefineLoop round=%d LLM 调用失败: %s", round_idx, e)
            log_bus.error(
                f"RefineLoop LLM 失败 round={round_idx}: {e}",
                logger="orchestrator.refine_loop",
            )
            break

    # 所有轮次用完或提前终止
    final_rounds = round_idx  # 记录实际使用的轮次
    log_bus.info(
        f"RefineLoop 结束（未成功）rounds_used={final_rounds}",
        logger="orchestrator.refine_loop",
    )
    return {
        "code": current_code,
        "execution": last_result or {"exit_code": -1, "error": "未执行"},
        "rounds_used": final_rounds,
        "success": False,
        **({"net_auth": net_auth_info} if net_auth_info else {}),
    }
