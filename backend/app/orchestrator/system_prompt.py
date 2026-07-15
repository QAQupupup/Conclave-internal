"""Conclave 系统提示词：向 LLM 描述 Conclave 的全部能力、模式和约束。

用于意图分流（classify_intent_async），让 LLM 基于对 Conclave 的完整理解
自主判断最合适的执行模式，而非依赖关键词匹配。

三层提示词架构：
- 系统提示词（此文件）：Conclave 身份、能力、模式、约束
- 用户提示词：用户原始请求（不修改、不截断）
- 修正覆盖：API 显式 flow_plan 或系统级强制覆盖
"""
from __future__ import annotations

from app.config import settings
from app.logging_config import get_logger

logger = get_logger("orchestrator.system_prompt")

# ── 系统提示词模板 ──────────────────────────────────────────
# 用 {key} 标记动态填充的变量，render_system_prompt() 负责填充

SYSTEM_PROMPT_TEMPLATE = """## 身份
你是 Conclave 会议型多智能体系统的流量调度器。你的职责是分析用户请求，
决定使用哪种执行模式来处理该请求。

## Conclave 的全部执行模式

### 模式 1：instant（即时回答）
- 适用场景：纯知识问答、简单计算、翻译、查天气/时间、简短解释概念、
  一句话总结已知内容。单个助手可直接回答，不需要多角色协作。
- 执行方式：单次 LLM 调用，直接生成答案，跳过六阶段管线。
- 耗时：~10-60秒
- 不适用：任何涉及设计、开发、架构、方案制定、需求分析、系统规划的任务。

### 模式 2：standard（标准会议模式 / 完整六阶段管线）
- 适用场景：涉及设计、开发、架构、方案制定、需求分析、系统规划、
  多步骤操作、代码生成、多角色协作、需要做出权衡决策的任务。
- 执行方式：澄清议题 → 队内发言 → 跨队辩论 → 证据对照 → 仲裁裁决 → 产出物
- 耗时：~5-30分钟
- 注意：即使请求很短（如"帮我生成一个物流管理系统"），只要涉及系统级产出，
  就是复杂任务，应走 standard。

### 模式 3：plan（先计划后执行）
- 适用场景：用户明确要求制定计划、分步执行、逐步推进。
  触发词包括但不限于："plan"、"计划"、"逐步"、"分步"、"深度思考"、
  "先规划"、"先设计再实现"、"step by step"。
- 执行方式：先调用 Planner 生成执行计划，再按计划逐步执行。

### 模式 4：simple（简化路由）
- 适用场景：中等复杂度任务，不需要跨队辩论和证据对照。
- 执行方式：澄清 → 队内发言 → 仲裁 → 产出（跳过 cross_team 和 evidence_check）
- 注意：simple 模式在内部映射为 instant 处理。

## 路由决策规则
- 用户说"plan"、"计划"、"逐步"、"深度思考"、"先规划" → plan 模式
- 用户明确要求"快速"、"简单回答"、"即时" → instant
- 用户请求涉及设计/开发/架构/系统 → standard（完整六阶段）
- 用户请求是简单的知识问答/计算/翻译 → instant
- 不确定时 → 偏向 standard（宁可慢，不可错）

## Conclave 当前能力
- 支持多 Agent 角色协作：主持人、产品架构师、工程师
- 支持代码沙箱执行（Docker）
- 支持 RAG 文档检索（Qdrant 向量数据库）
- 支持 Web 搜索（Playwright 无头浏览器）
- 支持结构化产出：PRD、OpenAPI 规范、设计文档、代码分析报告等
- 支持 ReAct 工具调用循环
- 支持代码自修复（Refine 循环）
- 支持动态角色借调
- 支持用户实时介入

## 当前系统状态
- 默认 LLM：{default_model}
- 沙箱模式：{sandbox_mode}
- 记忆系统：{memory_status}
- 动态路由：{dynamic_routing_status}

## 硬性约束
- 如果用户请求明确指定了执行模式，优先使用用户指定的模式
- 如果系统级强制覆盖（如 API 显式 flow_plan），必须遵守
- 不允许自行发明不存在的新模式
"""


def render_system_prompt() -> str:
    """渲染系统提示词，填充动态变量。

    从 config.py 读取当前系统状态，填充模板中的 {key} 占位符。

    Returns:
        渲染后的完整系统提示词字符串
    """
    return SYSTEM_PROMPT_TEMPLATE.format(
        default_model=settings.llm_model,
        sandbox_mode=_get_sandbox_mode(),
        memory_status=_get_memory_status(),
        dynamic_routing_status="开启" if _get_dynamic_routing() else "关闭",
    )


def build_classification_prompt(
    user_query: str,
    override_mode: str | None = None,
) -> tuple[str, str]:
    """构建意图分流提示词。

    将系统提示词和用户提示词明确分离，不混合。

    Args:
        user_query: 用户原始请求（不修改、不截断）
        override_mode: API 显式指定的 flow_plan（如 "fast"），为空时无覆盖

    Returns:
        (system_prompt, user_prompt) 元组——两者明确分离，不拼接
    """
    system_prompt = render_system_prompt()

    user_prompt = f"请分析以下用户请求，返回最适合的执行模式：\n\n用户请求：{user_query}"

    if override_mode:
        # API 显式覆盖：追加到用户提示词末尾，但标记为系统覆盖
        user_prompt += (
            f"\n\n[系统覆盖] 外部已指定 flow_plan = \"{override_mode}\"，"
            f"但如果此模式与请求不匹配，请在 reason 中说明。"
        )

    return system_prompt, user_prompt


def parse_classification_result(result_text: str) -> dict:
    """解析 LLM 返回的模式分类结果。

    预期 LLM 返回 JSON 格式：
    {"mode": "instant|standard|plan|simple", "reason": "..."}

    兼容旧名称：fast_path→instant, deep_think→standard, fast→instant, quick→instant, full→standard

    Args:
        result_text: LLM 返回的原始文本

    Returns:
        {"mode": str, "reason": str} 或 {"mode": "standard", "reason": "parse error"}
    """
    import json
    from app.orchestrator.instant import normalize_mode, FLOW_STANDARD, FLOW_INSTANT, FLOW_PLAN, FLOW_SIMPLE

    text = result_text.strip()

    _valid_modes = {FLOW_INSTANT, FLOW_STANDARD, FLOW_PLAN, FLOW_SIMPLE}

    # 尝试直接解析 JSON
    try:
        data = json.loads(text)
        mode = normalize_mode(data.get("mode", ""))
        reason = data.get("reason", "")
        if mode in _valid_modes:
            return {"mode": mode, "reason": reason}
        logger.warning("LLM 返回未知模式: %s", mode)
    except json.JSONDecodeError:
        # 尝试从文本中提取 JSON（LLM 可能在 JSON 前后加了说明文字）
        import re
        match = re.search(r'\{[^}]+\}', text)
        if match:
            try:
                data = json.loads(match.group())
                mode = normalize_mode(data.get("mode", ""))
                reason = data.get("reason", "")
                if mode in _valid_modes:
                    return {"mode": mode, "reason": reason}
            except json.JSONDecodeError:
                pass

    # 回退：默认 standard（保守策略）
    logger.warning("无法解析 LLM 分类结果，回退到 standard: %s", result_text[:100])
    return {"mode": FLOW_STANDARD, "reason": "parse error, fallback to standard"}


# ── 辅助函数 ──────────────────────────────────────────────


def _get_sandbox_mode() -> str:
    """获取沙箱模式描述"""
    mode = settings.sandbox_mode if hasattr(settings, 'sandbox_mode') else "auto"
    docker_available = getattr(settings, 'sandbox_docker_available', True)
    if mode == "auto":
        return "Docker（auto 模式）" if docker_available else "subprocess（无 Docker）"
    return mode


def _get_memory_status() -> str:
    """获取记忆系统状态"""
    disabled = settings.memory_disabled if hasattr(settings, 'memory_disabled') else False
    return "关闭" if disabled else "开启（三层记忆）"


def _get_dynamic_routing() -> bool:
    """获取动态路由开关状态"""
    return getattr(settings, 'dynamic_routing_enabled', True)