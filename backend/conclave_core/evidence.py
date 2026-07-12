# Produce 阶段证据综合（只读 state，无副作用）
from __future__ import annotations

from typing import Any

from app.models import MeetingState


def _synthesize_evidence_for_produce(state: MeetingState) -> dict[str, Any]:
    """将 evidence_set + decision_record 综合为结构化数据规格，
    供代码生成类 deliverable (code_analysis / data_science) 使用。

    返回空 dict 表示无可用证据（非代码类产出不受影响）。
    """
    if not state.evidence_set:
        return {}

    evidence_sources: list[str] = []
    evidence_quotes: list[dict] = []
    for es in state.evidence_set:
        for a in es.get("assessments", []):
            source = a.get("source", "")
            quote = a.get("quote", "")
            if source and source not in evidence_sources:
                evidence_sources.append(source)
            if quote:
                evidence_quotes.append({
                    "quote": quote[:200],
                    "source": source,
                    "supports": a.get("supports", "neutral"),
                    "conflict_id": es.get("conflict_id", ""),
                })

    decisions = (state.decision_record or {}).get("decisions", [])
    adopted = (state.decision_record or {}).get("adopted_claims", [])

    return {
        "available_data_sources": evidence_sources[:10],
        "evidence_count": len(evidence_quotes),
        "evidence_samples": evidence_quotes[:15],
        "decisions_count": len(decisions),
        "adopted_claims_count": len(adopted),
    }
