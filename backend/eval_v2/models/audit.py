"""Audit snapshot models - typed wrappers around SUT audit endpoint data."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class StageCompletion(BaseModel):
    """阶段完成情况。"""

    stage: str
    completed: bool
    iterations: int = 0
    duration_ms: float = 0.0


class TraceEvent(BaseModel):
    """LLM trace event (provider_switch/stub_fallback/circuit_breaker)."""

    event_type: str
    timestamp: str | None = None
    detail: str = ""
    provider: str | None = None
    model: str | None = None


class LLMTraceCall(BaseModel):
    """单次 LLM 调用记录。"""

    node: str = ""
    role: str = ""
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: float = 0.0
    status: str = "ok"


class TraceSnapshot(BaseModel):
    """LLM 调用追踪快照。"""

    calls: list[LLMTraceCall] = Field(default_factory=list)
    trace_events: list[TraceEvent] = Field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    total_calls: int = 0
    provider_switches: int = 0
    stub_fallbacks: int = 0
    circuit_breaker_trips: int = 0

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> TraceSnapshot:
        """从 audit 端点原始数据构建。"""
        calls_raw = raw.get("calls", [])
        events_raw = raw.get("trace_events", [])

        calls = []
        for c in calls_raw:
            calls.append(
                LLMTraceCall(
                    node=c.get("node", ""),
                    role=c.get("agent_role", c.get("role", "")),
                    provider=c.get("provider", ""),
                    model=c.get("model", ""),
                    input_tokens=c.get("input_tokens", 0),
                    output_tokens=c.get("output_tokens", 0),
                    total_tokens=c.get("total_tokens", 0),
                    cost_usd=c.get("cost_usd", 0.0),
                    latency_ms=c.get("latency_ms", 0.0),
                    status=c.get("status", "ok"),
                )
            )

        events = []
        provider_switches = 0
        stub_fallbacks = 0
        circuit_breaker_trips = 0
        for e in events_raw:
            etype = e.get("event_type", "")
            events.append(
                TraceEvent(
                    event_type=etype,
                    timestamp=e.get("timestamp"),
                    detail=e.get("detail", ""),
                    provider=e.get("provider"),
                    model=e.get("model"),
                )
            )
            if etype == "provider_switch":
                provider_switches += 1
            elif etype == "stub_fallback":
                stub_fallbacks += 1
            elif etype == "circuit_breaker_trip":
                circuit_breaker_trips += 1

        total_in = sum(c.input_tokens for c in calls)
        total_out = sum(c.output_tokens for c in calls)
        total_cost = sum(c.cost_usd for c in calls)

        return cls(
            calls=calls,
            trace_events=events,
            total_calls=len(calls),
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_tokens=total_in + total_out,
            total_cost_usd=total_cost,
            provider_switches=provider_switches,
            stub_fallbacks=stub_fallbacks,
            circuit_breaker_trips=circuit_breaker_trips,
        )


class MeetingSnapshot(BaseModel):
    """会议状态快照。"""

    meeting_id: str
    topic: str
    clarified_topic: str = ""
    status: str
    stage: str
    deliverable_type: str = "prd_openapi"
    flow_plan: str = "standard"
    workflow_template: str = "standard"
    debate_depth: str = "standard"
    quality_score: float = 0.0
    """SUT 内部质量评分 0-100。"""
    iteration_count: int = 0
    max_iterations: int = 2
    conflicts_count: int = 0
    decisions_count: int = 0
    claims_count: int = 0
    drift_detected: int = 0
    total_checks: int = 0
    hard_failures: list[str] = Field(default_factory=list)
    degradation_warnings: list[dict[str, Any]] = Field(default_factory=list)
    confidence_flags: dict[str, str] = Field(default_factory=dict)
    completed_stages: list[str] = Field(default_factory=list)
    artifact_available: bool = False
    artifact_length: int = 0
    error_detail: str = ""
    created_at: str = ""
    completed_at: str = ""
    duration_ms: float = 0.0

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> MeetingSnapshot:
        """从 audit 端点原始数据构建。"""
        meeting = raw.get("meeting", {})
        quality_eval = raw.get("quality_evaluation", {})
        observ = raw.get("observability", {})

        # 计算 artifact 长度
        artifact = meeting.get("artifact")
        artifact_len = 0
        artifact_avail = False
        if artifact:
            artifact_avail = True
            # 估算 artifact 文本长度
            import json

            artifact_len = len(json.dumps(artifact, ensure_ascii=False))

        # 计算漂移
        drift = observ.get("drift", {})
        drift_detected = drift.get("drift_detected", 0) if isinstance(drift, dict) else 0
        total_checks = drift.get("total_checks", 0) if isinstance(drift, dict) else 0

        # 阶段完成情况
        gate_history = quality_eval.get("gate_history", [])
        completed_stages = []
        for g in gate_history:
            if g.get("passed"):
                completed_stages.append(g.get("stage", ""))

        # 退化告警
        deg_warnings = observ.get("degradation_warnings", [])
        if not isinstance(deg_warnings, list):
            deg_warnings = []

        # confidence flags
        conf_flags = observ.get("confidence_flags", {})
        if not isinstance(conf_flags, dict):
            conf_flags = {}

        # 时长
        created = meeting.get("created_at", "")
        completed = meeting.get("completed_at", "")
        duration = 0.0
        try:
            if created and completed:
                c_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
                e_dt = datetime.fromisoformat(completed.replace("Z", "+00:00"))
                duration = (e_dt - c_dt).total_seconds() * 1000
        except (ValueError, TypeError):
            pass

        return cls(
            meeting_id=meeting.get("id", ""),
            topic=meeting.get("topic", ""),
            clarified_topic=meeting.get("clarified_topic", ""),
            status=meeting.get("status", ""),
            stage=meeting.get("stage", ""),
            deliverable_type=meeting.get("deliverable_type", "prd_openapi"),
            flow_plan=meeting.get("flow_plan", "standard"),
            workflow_template=meeting.get("workflow_template", "standard"),
            debate_depth=meeting.get("debate_depth", "standard"),
            quality_score=quality_eval.get("score", meeting.get("quality_score", 0.0)),
            iteration_count=meeting.get("iteration_count", 0),
            max_iterations=meeting.get("max_iterations", 2),
            conflicts_count=len(meeting.get("conflicts", []) or []),
            decisions_count=len(
                meeting.get("decision_record", {}).get("decisions", [])
                if isinstance(meeting.get("decision_record"), dict)
                else []
            ),
            claims_count=len(meeting.get("claims", []) or []),
            drift_detected=drift_detected,
            total_checks=total_checks,
            hard_failures=quality_eval.get("hard_failures", []),
            degradation_warnings=deg_warnings,
            confidence_flags=conf_flags,
            completed_stages=completed_stages,
            artifact_available=artifact_avail,
            artifact_length=artifact_len,
            error_detail=meeting.get("error_detail", ""),
            created_at=created,
            completed_at=completed,
            duration_ms=duration,
        )


class CostSnapshot(BaseModel):
    """成本快照。"""

    cost_records: list[dict[str, Any]] = Field(default_factory=list)
    total_cost_usd: float = 0.0
    """从 cost_records 汇总的真实总成本。"""
    per_stage_cost: dict[str, float] = Field(default_factory=dict)
    per_provider_cost: dict[str, float] = Field(default_factory=dict)

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> CostSnapshot:
        """从 audit 端点原始数据构建。"""
        records = raw.get("cost_records", raw.get("costs", []))
        if not isinstance(records, list):
            records = []

        total = 0.0
        per_stage: dict[str, float] = {}
        per_provider: dict[str, float] = {}

        for r in records:
            cost = r.get("cost_usd", 0.0)
            if not isinstance(cost, (int, float)):
                cost = 0.0
            total += cost
            node = r.get("node", r.get("agent_role", "unknown"))
            provider = r.get("provider", "unknown")
            per_stage[node] = per_stage.get(node, 0.0) + cost
            per_provider[provider] = per_provider.get(provider, 0.0) + cost

        return cls(
            cost_records=records,
            total_cost_usd=total,
            per_stage_cost=per_stage,
            per_provider_cost=per_provider,
        )


class DegradationSummary(BaseModel):
    """退化告警汇总。"""

    total_warnings: int = 0
    high_severity: int = 0
    medium_severity: int = 0
    low_severity: int = 0
    has_critical_degradation: bool = False
    warning_types: dict[str, int] = Field(default_factory=dict)

    @classmethod
    def from_warnings(cls, warnings: list[dict[str, Any]]) -> DegradationSummary:
        """从退化告警列表构建。"""
        high = medium = low = 0
        types: dict[str, int] = {}
        has_critical = False

        for w in warnings:
            severity = w.get("severity", w.get("level", "medium"))
            wtype = w.get("type", w.get("warning_type", "unknown"))
            types[wtype] = types.get(wtype, 0) + 1
            if severity == "high" or severity == "critical":
                high += 1
                has_critical = True
            elif severity == "medium":
                medium += 1
            else:
                low += 1

        return cls(
            total_warnings=len(warnings),
            high_severity=high,
            medium_severity=medium,
            low_severity=low,
            has_critical_degradation=has_critical,
            warning_types=types,
        )


class AuditSnapshot(BaseModel):
    """完整的审计快照，封装 SUT /meetings/{id}/audit 返回的所有数据。"""

    meeting: MeetingSnapshot
    trace: TraceSnapshot
    cost: CostSnapshot
    degradation: DegradationSummary
    raw_artifact: dict[str, Any] | None = None
    """原始 artifact 数据（用于 L3 Judge 评分）。"""
    raw_audit: dict[str, Any] = Field(default_factory=dict)
    """完整原始 audit JSON（用于调试和扩展）。"""

    @classmethod
    def from_raw(cls, raw: dict[str, Any]) -> AuditSnapshot:
        """从 audit 端点原始 JSON 构建。"""
        meeting = MeetingSnapshot.from_raw(raw)
        trace_raw = raw.get("llm_trace", raw.get("trace", {}))
        if not isinstance(trace_raw, dict):
            trace_raw = {}
        trace = TraceSnapshot.from_raw(trace_raw)
        cost = CostSnapshot.from_raw(raw)
        deg = DegradationSummary.from_warnings(meeting.degradation_warnings)

        artifact = raw.get("meeting", {}).get("artifact")

        return cls(
            meeting=meeting,
            trace=trace,
            cost=cost,
            degradation=deg,
            raw_artifact=artifact,
            raw_audit=raw,
        )

    def get_artifact_text(self) -> str:
        """提取 artifact 的文本表示，供 LLM Judge 使用。"""
        import json

        if not self.raw_artifact:
            return ""
        return json.dumps(self.raw_artifact, ensure_ascii=False, indent=2)
