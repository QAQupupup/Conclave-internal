# 结论锁定链业务逻辑（从 ConclusionChain Pydantic 模型中拆分出的无状态函数）
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from conclave_core.conclusion_chain import ConclusionChain, ConsistencyResult, LockedConclusion


def lock_conclusion(chain: ConclusionChain, stage: str, content: dict[str, Any]) -> LockedConclusion:
    """锁定一个阶段结论，返回 LockedConclusion

    - content_hash = sha256(json.dumps(content, sort_keys=True))[:12]
    - conclusion_id = f"locked-{stage}-{hash}"
    - 追加到 conclusions
    """
    from conclave_core.conclusion_chain import LockedConclusion

    content_hash = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[
        :12
    ]
    conclusion = LockedConclusion(
        conclusion_id=f"locked-{stage}-{content_hash}",
        stage=stage,
        content=content,
        content_hash=content_hash,
        locked_at=datetime.now(timezone.utc).isoformat(),
    )
    chain.conclusions.append(conclusion)
    return conclusion


def get_locked_context(chain: ConclusionChain, current_stage: str) -> str:
    """生成给当前阶段的'已确认结论'上下文文本，注入 prompt

    把所有已锁定结论格式化为扁平文本：
    【已确认结论 - clarify阶段】
    clarified_topic: ...
    key_questions: ...
    强调：以下结论已锁定，你的输出必须基于这些结论，不得与之矛盾。
    """
    if not chain.conclusions:
        return ""
    lines: list[str] = ["【已确认结论 - 以下结论已锁定，你的输出必须基于这些结论，不得与之矛盾】"]
    for c in chain.conclusions:
        lines.append(f"【已确认结论 - {c.stage}阶段】")
        for key, value in c.content.items():
            lines.append(f"{key}: {value}")
    lines.append("如果你的输出与已确认结论矛盾，将被拒绝。")
    return "\n".join(lines)


def check_consistency(chain: ConclusionChain, new_output: dict[str, Any], current_stage: str) -> ConsistencyResult:
    """检查新输出是否与已锁定结论矛盾

    简化实现：基于关键词和字段存在性，不做语义理解。
    规则：
    1. 如果当前是 cross_team/evidence_check/arbitrate/produce，且 clarify 已锁定
       clarified_topic，检查新输出中是否有字段同时包含否定词和 topic 关键词
    2. 如果当前是 produce，且 arbitrate 已锁定 adopted_claims，
       检查 PRD 是否包含至少一条 claim 的核心内容
    3. 如果当前是 arbitrate，且 intra_team 已锁定 claims，
       检查 decisions 是否直接推翻高风险论点
    """
    from conclave_core.conclusion_chain import ConsistencyResult

    violations: list[str] = []

    # 构建已锁定结论的阶段->内容映射（同阶段取最后一条）
    locked: dict[str, dict[str, Any]] = {}
    for c in chain.conclusions:
        locked[c.stage] = c.content

    # ---------- 规则1：不得否定已确认议题 ----------
    if current_stage in ("cross_team", "evidence_check", "arbitrate", "produce"):
        clarify_content = locked.get("clarify")
        if clarify_content:
            topic = clarify_content.get("clarified_topic", "")
            if topic:
                negation_words = ["不是", "不应", "错误"]
                topic_keywords = _extract_keywords(topic)
                if topic_keywords:
                    # 逐字段检查：同一字段中是否同时出现否定词和 topic 关键词
                    for text in _extract_strings(new_output):
                        has_neg = any(neg in text for neg in negation_words)
                        has_topic = any(kw in text for kw in topic_keywords)
                        if has_neg and has_topic:
                            violations.append(
                                f"输出可能否定了已确认议题「{topic}」（检测到否定词与议题关键词同时出现）"
                            )
                            break

    # ---------- 规则2：PRD 应包含已采纳结论核心内容 ----------
    if current_stage == "produce":
        arbitrate_content = locked.get("arbitrate")
        if arbitrate_content:
            adopted_claims = arbitrate_content.get("adopted_claims", [])
            prd = new_output.get("prd", {})
            prd_text = json.dumps(prd, ensure_ascii=False)
            # 简化检查：至少有一条 adopted claim 的关键词出现在 PRD 中
            if adopted_claims:
                any_match = False
                for claim in adopted_claims:
                    keywords = _extract_keywords(claim)
                    if keywords and any(kw in prd_text for kw in keywords):
                        any_match = True
                        break
                if not any_match:
                    violations.append(f"PRD 未包含任何已采纳结论的核心内容：{adopted_claims}")

    # ---------- 规则3：裁决不得推翻高风险论点 ----------
    if current_stage == "arbitrate":
        intra_content = locked.get("intra_team")
        if intra_content:
            claims = intra_content.get("claims", [])
            decisions = new_output.get("decisions", [])
            negation_words = ["不是", "错误", "推翻"]
            for claim in claims:
                if claim.get("risk_level") != "high":
                    continue
                claim_text = claim.get("claim", "")
                claim_keywords = _extract_keywords(claim_text)
                if not claim_keywords:
                    continue
                for decision in decisions:
                    rationale = decision.get("rationale", "")
                    has_neg = any(neg in rationale for neg in negation_words)
                    has_claim = any(kw in rationale for kw in claim_keywords)
                    if has_neg and has_claim:
                        violations.append(f"裁决可能推翻了高风险论点：{claim_text}")
                        break

    return ConsistencyResult(
        is_consistent=len(violations) == 0,
        violations=violations,
    )


def get_chain_summary(chain: ConclusionChain) -> dict[str, Any]:
    """返回链摘要，用于 trace 和 state 持久化"""
    return {
        "meeting_id": chain.meeting_id,
        "locked_stages": [c.stage for c in chain.conclusions],
        "conclusion_count": len(chain.conclusions),
        "conclusions": [
            {
                "conclusion_id": c.conclusion_id,
                "stage": c.stage,
                "content_hash": c.content_hash,
                "locked_at": c.locked_at,
            }
            for c in chain.conclusions
        ],
    }


# ---------- 内部工具方法 ----------


def _extract_keywords(text: str) -> list[str]:
    """从文本中提取 2-gram 关键词（简单分词，过滤填充字）"""
    if not text:
        return []
    # 过滤的填充字符（中文常见虚词/单字）
    filler_chars = set("的了是这一个那和与及或等在对为地把被将又也都很已还就这那之其而")
    # 去掉非字母数字字符，保留中英文
    cleaned = "".join(ch for ch in text if ch.isalnum())
    if len(cleaned) < 2:
        return [text] if text else []
    keywords: list[str] = []
    seen: set[str] = set()
    for i in range(len(cleaned) - 1):
        gram = cleaned[i : i + 2]
        # 过滤包含填充字的 gram
        if any(c in filler_chars for c in gram):
            continue
        if gram in seen:
            continue
        seen.add(gram)
        keywords.append(gram)
    return keywords[:10]  # 限制关键词数量


def _extract_strings(obj: Any, result: list[str] | None = None) -> list[str]:
    """递归提取 dict 中所有字符串值，用于逐字段一致性检查"""
    if result is None:
        result = []
    if isinstance(obj, str):
        result.append(obj)
    elif isinstance(obj, dict):
        for value in obj.values():
            _extract_strings(value, result)
    elif isinstance(obj, list):
        for item in obj:
            _extract_strings(item, result)
    return result
