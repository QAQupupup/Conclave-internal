"""LLM Judge prompt templates.

Includes:
- CoT + Rubric scoring prompt (with 5-level anchors)
- Binary judgment prompt
- Pairwise comparison prompt (with position randomization)
- Length bias mitigation note
"""

from __future__ import annotations

from eval_v2.llm_judge.rubrics import DimensionSpec

# System prompt for all judge tasks
JUDGE_SYSTEM_PROMPT = """你是一位专业的{role}，负责评估AI多Agent系统生成的{deliverable_name}质量。

评估原则：
1. 严格按照评分标准进行客观评估
2. 先进行详细分析（Chain-of-Thought），再给出评分
3. 不要因为回答更长就给更高分。简洁但完整的回答比冗长但缺乏重点的回答得分更高
4. 如果内容包含占位符/TODO/TBD，应扣减相应分数
5. 如果内容存在事实错误或技术错误，应扣减相应分数
"""

# CoT + Rubric 评分 prompt
COT_RUBRIC_PROMPT = """请评估以下{deliverable_name}在「{dimension_name}」维度上的质量。

## 评估维度说明
{dimension_description}

## 评分标准（5级Likert量表）
{anchors}

## 评分方法
1. 仔细阅读生成内容
2. 分析该内容在「{dimension_name}」维度上的优点和缺点
3. 对照评分标准给出1-5分
4. 给出二元判定：该维度是否达到可接受水平（≥3分）

## 需求（原始输入）
{topic}

## 待评估内容
{artifact_text}

## 输出格式
请严格按以下JSON格式输出（不要输出其他内容）：
```json
{{
  "reasoning": "你的详细分析（分析优点和缺点，200字以内）",
  "likert_score": 1-5的整数,
  "binary_pass": true或false,
  "confidence": "high/medium/low"
}}
```"""

# Pairwise 比较 prompt
PAIRWISE_PROMPT = """你是一位专业的{role}，请对比两份{deliverable_name}的质量，选出更好的一份。

## 对比维度
{dimension_criteria}

## 需求
{topic}

## 候选方案 A
{candidate_a}

## 候选方案 B
{candidate_b}

## 评估原则
1. 仔细对比两份方案的质量
2. 不要因为更长就认为更好
3. 关注准确性、完整性、可操作性
4. 如果两份方案质量相当，选择 "tie"

## 输出格式
请严格按以下JSON格式输出：
```json
{{
  "reasoning": "详细对比分析（200字以内），说明你选择的理由",
  "winner": "A" 或 "B" 或 "tie",
  "confidence": "high/medium/low"
}}
```"""

# 长度偏置缓解注释（附加到每个评分 prompt 末尾）
LENGTH_BIAS_NOTE = """
重要提醒：评分应基于内容质量而非长度。简洁但完整覆盖所有要点的回答应得高分；冗长、重复、缺乏实质内容的回答不应因篇幅长而得高分。"""


def build_cot_rubric_prompt(
    topic: str,
    artifact_text: str,
    dimension: DimensionSpec,
    deliverable_name: str = "PRD和OpenAPI规范",
    role: str = "技术文档评审专家",
) -> str:
    """构建 CoT+Rubric 评分 prompt。"""
    prompt = COT_RUBRIC_PROMPT.format(
        deliverable_name=deliverable_name,
        dimension_name=dimension.name,
        dimension_description=dimension.description,
        anchors=dimension.get_anchor_text(),
        topic=topic,
        artifact_text=_truncate(artifact_text, 40000),
    )
    prompt += LENGTH_BIAS_NOTE
    return prompt


def build_pairwise_prompt(
    topic: str,
    candidate_a: str,
    candidate_b: str,
    dimension_criteria: str = "综合质量（准确性、完整性、可操作性、具体性）",
    deliverable_name: str = "PRD和OpenAPI规范",
    role: str = "技术文档评审专家",
) -> str:
    """构建 Pairwise 比较 prompt。"""
    return PAIRWISE_PROMPT.format(
        role=role,
        deliverable_name=deliverable_name,
        dimension_criteria=dimension_criteria,
        topic=topic,
        candidate_a=_truncate(candidate_a, 20000),
        candidate_b=_truncate(candidate_b, 20000),
    )


def build_judge_system_prompt(deliverable_name: str = "PRD和OpenAPI规范", role: str = "技术文档评审专家") -> str:
    """构建 Judge system prompt。"""
    return JUDGE_SYSTEM_PROMPT.format(role=role, deliverable_name=deliverable_name)


def _truncate(text: str, max_chars: int) -> str:
    """截断过长文本。"""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n...[内容过长，已截断]"
