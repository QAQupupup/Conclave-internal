# RefineLoop：代码自修复循环（受控 Re-Execution 模式）
# 设计原则：
# - LLM 只做"给定报错修正代码"，不做"决策下一步"
# - 每轮上下文 O(1)：只带上一轮最终代码 + 报错，不带完整历史
# - max_rounds 硬上限作为物理兜底
# - 重复检测：连续两轮生成相同代码 → 判定卡死，终止
# - 目标锚定：每轮 prompt 带原始任务 + 当前状态
from __future__ import annotations

import json
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
        desc = result.get("code_analysis", {}).get("description", "")
        return f"数据分析任务：{desc}。生成代码执行失败，需要修正。"
    elif deliverable_type == "tested_system":
        desc = result.get("tested_system", {}).get("description", "")
        return f"测试系统任务：{desc}。测试执行失败，需要修正代码。"
    return "代码执行任务。执行失败，需要修正。"


async def refine_python_code(
    initial_code: str,
    task_summary: str,
    run_fn,
    max_rounds: int = 5,
) -> dict[str, Any]:
    """代码自修复循环

    Args:
        initial_code: 初始生成的代码
        task_summary: 任务锚点（三句话摘要）
        run_fn: 异步执行函数 (code) -> {exit_code, stdout, stderr, ...}
        max_rounds: 最大循环次数

    Returns:
        {code, execution, rounds_used, success}
    """
    current_code = initial_code
    last_result = None
    llm = get_llm()

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
            }

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
    log_bus.info(
        f"RefineLoop 结束（未成功）rounds_used={max_rounds}",
        logger="orchestrator.refine_loop",
    )
    return {
        "code": current_code,
        "execution": last_result or {"exit_code": -1, "error": "未执行"},
        "rounds_used": max_rounds,
        "success": False,
    }
