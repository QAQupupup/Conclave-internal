"""M1.2: 证据事实核查状态测试

验证：
- EvidenceAssessmentItem schema 包含 fact_check_status 字段，默认 unverifiable
- _preliminary_fact_check_status 根据来源类型返回正确状态
- _make_common_knowledge_evidence 附带 fact_check_status=unverifiable
- StubLLM evidence_check 响应包含 fact_check_status
- Schema 校验接受 fact_check_status 字段
"""

from __future__ import annotations

import pytest

from app.agents.llm import StubLLM
from app.agents.schemas import EvidenceAssessmentItem, EvidenceCheckResult
from app.orchestrator.evidence_helpers import (
    _make_common_knowledge_evidence,
    _preliminary_fact_check_status,
)


# ── Schema 字段测试 ─────────────────────────────────────────


class TestSchemaField:
    """测试 EvidenceAssessmentItem 的 fact_check_status 字段"""

    def test_default_value(self):
        """新创建的 item 默认 fact_check_status=unverifiable。"""
        item = EvidenceAssessmentItem(evidence_id="ev-0")
        assert item.fact_check_status == "unverifiable"

    def test_verified_value(self):
        """可以设置 fact_check_status=verified。"""
        item = EvidenceAssessmentItem(evidence_id="ev-0", fact_check_status="verified")
        assert item.fact_check_status == "verified"

    def test_contradicted_value(self):
        """可以设置 fact_check_status=contradicted。"""
        item = EvidenceAssessmentItem(evidence_id="ev-0", fact_check_status="contradicted")
        assert item.fact_check_status == "contradicted"

    def test_disputed_value(self):
        """可以设置 fact_check_status=disputed。"""
        item = EvidenceAssessmentItem(evidence_id="ev-0", fact_check_status="disputed")
        assert item.fact_check_status == "disputed"

    def test_full_assessment_with_fact_check(self):
        """完整评估项包含 fact_check_status。"""
        item = EvidenceAssessmentItem(
            evidence_id="ev-0",
            quote="系统应支持异步任务处理",
            source="doc:架构",
            supports="a",
            strength="strong",
            fact_check_status="verified",
        )
        assert item.fact_check_status == "verified"

    def test_evidence_check_result_contains_fact_check(self):
        """EvidenceCheckResult 的 evidence_assessments 包含 fact_check_status。"""
        result = EvidenceCheckResult(
            conflict_id="c1",
            evidence_assessments=[
                EvidenceAssessmentItem(
                    evidence_id="ev-0",
                    source="doc:架构",
                    fact_check_status="verified",
                ),
            ],
        )
        assert result.evidence_assessments[0].fact_check_status == "verified"

    def test_schema_accepts_extra_fields(self):
        """schema 配置 extra=ignore，LLM 返回多余字段不报错。"""
        item = EvidenceAssessmentItem(
            evidence_id="ev-0",
            fact_check_status="verified",
            some_extra_field="ignored",  # type: ignore
        )
        assert item.fact_check_status == "verified"


# ── _preliminary_fact_check_status 测试 ────────────────────


class TestPreliminaryFactCheck:
    """测试 _preliminary_fact_check_status 函数"""

    def test_doc_source_verified(self):
        """doc: 开头的来源返回 verified。"""
        assert _preliminary_fact_check_status("doc:架构") == "verified"
        assert _preliminary_fact_check_status("doc:user_upload.pdf") == "verified"
        assert _preliminary_fact_check_status("doc:unknown") == "verified"

    def test_web_source_unverifiable(self):
        """web: 开头的来源返回 unverifiable。"""
        assert _preliminary_fact_check_status("web:unknown") == "unverifiable"
        assert _preliminary_fact_check_status("web:https://example.com") == "unverifiable"

    def test_common_knowledge_unverifiable(self):
        """common_knowledge: 开头的来源返回 unverifiable。"""
        assert _preliminary_fact_check_status("common_knowledge:side_a") == "unverifiable"
        assert _preliminary_fact_check_status("common_knowledge:side_b") == "unverifiable"

    def test_empty_source_unverifiable(self):
        """空来源返回 unverifiable。"""
        assert _preliminary_fact_check_status("") == "unverifiable"

    def test_unknown_source_unverifiable(self):
        """未知前缀的来源返回 unverifiable。"""
        assert _preliminary_fact_check_status("unknown:type") == "unverifiable"
        assert _preliminary_fact_check_status("random_source") == "unverifiable"


# ── _make_common_knowledge_evidence 测试 ───────────────────


class TestCommonKnowledgeEvidence:
    """测试通用知识降级证据包含 fact_check_status"""

    def test_common_knowledge_has_fact_check_status(self):
        """通用知识证据附带 fact_check_status=unverifiable。"""
        conflict = {
            "id": "c1",
            "summary": "测试冲突",
            "side_a": "方案 A",
            "side_b": "方案 B",
        }
        evidence = _make_common_knowledge_evidence(conflict)
        assert len(evidence) == 2
        for ev in evidence:
            assert "fact_check_status" in ev
            assert ev["fact_check_status"] == "unverifiable"

    def test_common_knowledge_has_strength_weak(self):
        """通用知识证据 strength=weak。"""
        conflict = {"summary": "测试", "side_a": "A", "side_b": "B"}
        evidence = _make_common_knowledge_evidence(conflict)
        for ev in evidence:
            assert ev["strength"] == "weak"


# ── StubLLM 测试 ──────────────────────────────────────────


class TestStubLLMFactCheck:
    """测试 StubLLM 的 evidence_check 响应包含 fact_check_status"""

    @pytest.mark.asyncio
    async def test_stub_evidence_check_has_fact_check(self):
        """StubLLM evidence_check 响应包含 fact_check_status。"""
        stub = StubLLM()
        result = await stub.complete("EvidenceCheck test", schema_hint="evidence_check")
        assessments = result.get("evidence_assessments", [])
        assert len(assessments) >= 1
        for assessment in assessments:
            assert "fact_check_status" in assessment
            assert assessment["fact_check_status"] in ("verified", "contradicted", "unverifiable", "disputed")

    @pytest.mark.asyncio
    async def test_stub_evidence_check_doc_sources_verified(self):
        """StubLLM evidence_check 中 doc: 来源标为 verified。"""
        stub = StubLLM()
        result = await stub.complete("EvidenceCheck test", schema_hint="evidence_check")
        assessments = result.get("evidence_assessments", [])
        for assessment in assessments:
            source = assessment.get("source", "")
            if source.startswith("doc:"):
                assert assessment["fact_check_status"] == "verified"
