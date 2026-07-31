"""Self-validation unit tests for Eval V2 framework.

Tests core components without requiring a running SUT or LLM access.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from eval_v2.cost.efficiency import compute_efficiency_metrics
from eval_v2.cost.tracker import CostTracker
from eval_v2.dataset.loader import load_all
from eval_v2.dataset.schema import validate_case_dict
from eval_v2.llm_judge.rubrics import DimensionSpec, get_dimensions
from eval_v2.models.enums import CaseCategory, FailureClass, Level
from eval_v2.models.result import CaseRunResult, CostBreakdown, DimensionScore, LayerResult, TokenBreakdown
from eval_v2.stats.confidence import wilson_interval
from eval_v2.stats.effect_size import cliffs_delta, cohens_h, interpret_cohens_h
from eval_v2.stats.pass_at_k import compute_pass_at_k, compute_stable_pass_at_k, mark_stability
from eval_v2.stats.significance import fisher_exact_test, mann_whitney_u


class TestSchemaValidation:
    def test_valid_minimal_case(self):
        data = {
            "case_id": "test-001",
            "category": "prd_openapi",
            "tier": 1,
            "topic": "Test topic",
            "config": {"deliverable_type": "prd_openapi"},
        }
        errors = validate_case_dict(data)
        assert len(errors) == 0, f"Unexpected errors: {errors}"

    def test_missing_required_field(self):
        data = {"case_id": "test-001", "category": "prd_openapi"}
        errors = validate_case_dict(data)
        assert len(errors) > 0

    def test_invalid_category(self):
        data = {
            "case_id": "test-001",
            "category": "invalid_cat",
            "tier": 1,
            "topic": "Test",
            "config": {"deliverable_type": "prd_openapi"},
        }
        errors = validate_case_dict(data)
        assert any("category" in e for e in errors)

    def test_invalid_tier(self):
        data = {
            "case_id": "test-001",
            "category": "prd_openapi",
            "tier": 5,
            "topic": "Test",
            "config": {"deliverable_type": "prd_openapi"},
        }
        errors = validate_case_dict(data)
        assert any("tier" in e for e in errors)

    def test_topic_too_long(self):
        data = {
            "case_id": "test-001",
            "category": "prd_openapi",
            "tier": 1,
            "topic": "x" * 20001,
            "config": {"deliverable_type": "prd_openapi"},
        }
        errors = validate_case_dict(data)
        assert any("too long" in e for e in errors)

    def test_empty_topic_allowed_for_edge(self):
        data = {
            "case_id": "edge-001",
            "category": "edge_adversarial",
            "tier": 3,
            "topic": "",
            "config": {"deliverable_type": "prd_openapi", "expect_timeout": True},
        }
        errors = validate_case_dict(data)
        assert len(errors) == 0, f"Empty topic should be allowed: {errors}"


class TestStatsConfidence:
    def test_wilson_basic(self):
        lo, hi = wilson_interval(5, 10)
        assert 0 < lo < 0.5 < hi < 1.0

    def test_wilson_zero_success(self):
        lo, hi = wilson_interval(0, 10)
        assert lo == 0.0
        assert hi > 0

    def test_wilson_all_success(self):
        lo, hi = wilson_interval(10, 10)
        assert lo > 0
        assert hi == 1.0

    def test_wilson_monotonic_with_n(self):
        _, hi1 = wilson_interval(5, 10)
        lo2, hi2 = wilson_interval(50, 100)
        assert (hi2 - lo2) < hi1


class TestStatsPassAtK:
    def _make_result(self, case_id, run_index, passed, score=70.0):
        return CaseRunResult(
            case_id=case_id,
            run_index=run_index,
            aggregate_score=score if passed else 30.0,
            passed=passed,
            cost=CostBreakdown(),
            tokens=TokenBreakdown(),
        )

    def test_pass_at_1_all_pass(self):
        results = [self._make_result("c1", i, True) for i in range(3)]
        assert compute_pass_at_k(results, k=1) == 1.0

    def test_pass_at_1_none_pass(self):
        results = [self._make_result("c1", i, False) for i in range(3)]
        assert compute_pass_at_k(results, k=1) == 0.0

    def test_pass_at_3_mixed(self):
        results = []
        results.extend([self._make_result("c1", i, i < 2) for i in range(3)])
        results.extend([self._make_result("c2", i, False) for i in range(3)])
        results.extend([self._make_result("c3", i, i == 0) for i in range(3)])
        assert compute_pass_at_k(results, k=3) == pytest.approx(2 / 3)

    def test_stable_pass_at_3(self):
        # c1: 3/3 (rate=1.0 >= 0.67) -> stable
        # c2: 2/3 (rate=0.667 ~= 0.67, strictly < 0.67) -> not stable
        # c3: 1/3 (rate=0.33) -> not stable
        # c4: 0/3 -> not stable
        results = []
        results.extend([self._make_result("c1", i, True) for i in range(3)])
        results.extend([self._make_result("c2", i, i < 2) for i in range(3)])
        results.extend([self._make_result("c3", i, i == 0) for i in range(3)])
        results.extend([self._make_result("c4", i, False) for i in range(3)])
        # Only c1 is stable (1.0 >= 0.67)
        assert compute_stable_pass_at_k(results, k=3, threshold=0.67) == pytest.approx(0.25)

    def test_mark_stability(self):
        results = []
        results.extend([self._make_result("c1", i, True) for i in range(3)])
        results.extend([self._make_result("c2", i, i < 2) for i in range(3)])
        mark_stability(results)
        assert all(r.is_stable for r in results if r.case_id == "c1")
        assert not all(r.is_stable for r in results if r.case_id == "c2")


class TestStatsEffectSize:
    def test_cohens_h_zero(self):
        assert cohens_h(0.5, 0.5) == pytest.approx(0.0)

    def test_cohens_h_large(self):
        h = cohens_h(0.9, 0.1)
        assert abs(h) > 1.0

    def test_interpret_cohens_h(self):
        assert interpret_cohens_h(0.1) == "negligible"
        assert interpret_cohens_h(0.3) == "small"
        assert interpret_cohens_h(0.6) == "medium"
        assert interpret_cohens_h(1.0) == "large"

    def test_cliffs_delta_zero(self):
        assert cliffs_delta([1, 2, 3], [1, 2, 3]) == pytest.approx(0.0)

    def test_cliffs_delta_extreme(self):
        assert cliffs_delta([4, 5, 6], [1, 2, 3]) == pytest.approx(1.0)


class TestStatsSignificance:
    def test_fisher_identical(self):
        p = fisher_exact_test(5, 10, 5, 10)
        assert p > 0.05

    def test_fisher_very_different(self):
        p = fisher_exact_test(9, 10, 1, 10)
        assert p < 0.05

    def test_mann_whitney_identical(self):
        # Same distribution -> high p-value (not significant)
        p = mann_whitney_u([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
        assert p > 0.05

    def test_mann_whitney_different(self):
        # Very different distributions -> low p-value
        p = mann_whitney_u([1, 2, 3, 4, 5], [10, 20, 30, 40, 50])
        assert p < 0.05


class TestCostTracker:
    def test_record_judge_call(self):
        tracker = CostTracker()
        cost = tracker.record_judge_call(input_tokens=1000, output_tokens=500)
        assert cost > 0
        assert tracker.judge_cost_usd > 0
        assert tracker.judge_total_tokens == 1500

    def test_record_multiple(self):
        tracker = CostTracker()
        for _ in range(5):
            tracker.record_judge_call(1000, 500)
        assert tracker.judge_total_tokens == 7500
        assert tracker.judge_cost_usd > 0

    def test_reset(self):
        tracker = CostTracker()
        tracker.record_judge_call(1000, 500)
        tracker.reset()
        assert tracker.judge_cost_usd == 0.0
        assert tracker.judge_total_tokens == 0


class TestRubrics:
    def test_all_dimensions_listed(self):
        dims = get_dimensions("prd_openapi")
        names = [d.name for d in dims]
        assert "completeness" in names
        assert "accuracy" in names
        assert len(dims) >= 5

    def test_rubric_has_required_fields(self):
        for dim in get_dimensions("prd_openapi"):
            assert isinstance(dim, DimensionSpec)
            assert dim.name
            assert len(dim.anchors) == 5
            assert dim.weight > 0
            for score in (1, 2, 3, 4, 5):
                assert score in dim.anchors

    def test_rubric_weights_sum_to_one(self):
        dims = get_dimensions("prd_openapi")
        total = sum(d.weight for d in dims)
        assert total == pytest.approx(1.0, abs=0.01)


class TestEnums:
    def test_level_ordering(self):
        assert Level.L0_HEALTH.value == "l0_health"
        assert Level.L4_COMPARATIVE.value == "l4_comparative"

    def test_failure_classes(self):
        assert FailureClass.INFRASTRUCTURE.value == "infrastructure"
        assert FailureClass.MODEL.value == "model"

    def test_case_categories(self):
        assert CaseCategory.PRD_OPENAPI.value == "prd_openapi"
        assert CaseCategory.EDGE_ADVERSARIAL.value == "edge_adversarial"


class TestLayerResult:
    def test_weighted_score_calculation(self):
        layer = LayerResult(layer=Level.L2_INTERNAL, score=0.8, weight=0.25, passed=True)
        assert layer.score * layer.weight == pytest.approx(0.2)

    def test_skipped_layer_zero_score(self):
        layer = LayerResult(
            layer=Level.L4_COMPARATIVE,
            score=1.0,
            weight=0.15,
            passed=True,
            skipped=True,
            skip_reason="no baseline",
        )
        # When skipped, contribution is 0
        assert 0.0 == 0.0


class TestDatasetLoading:
    def test_load_all_cases(self):
        cases = load_all()
        assert len(cases) >= 20, f"Expected at least 20 cases, got {len(cases)}"

    def test_load_filter_by_tier(self):
        t1 = load_all(tiers=[1])
        t3 = load_all(tiers=[3])
        assert len(t1) > 0
        assert len(t3) > 0
        assert all(c.tier == 1 for c in t1)
        assert all(c.tier == 3 for c in t3)

    def test_load_filter_by_category(self):
        cases = load_all(categories=[CaseCategory.EDGE_ADVERSARIAL])
        assert len(cases) > 0
        assert all(c.category == CaseCategory.EDGE_ADVERSARIAL for c in cases)

    def test_all_cases_have_valid_config(self):
        cases = load_all()
        for case in cases:
            assert case.case_id
            assert case.topic is not None
            assert case.config.deliverable_type is not None
            assert case.tier in (1, 2, 3)


class TestEfficiencyMetrics:
    def _make_result(self, cost_usd, tokens, passed, latency_ms=60000):
        return CaseRunResult(
            case_id="test",
            run_index=0,
            aggregate_score=70.0 if passed else 30.0,
            passed=passed,
            cost=CostBreakdown(total_cost_usd=cost_usd, sut_cost_usd=cost_usd * 0.8, judge_cost_usd=cost_usd * 0.2),
            tokens=TokenBreakdown(total_tokens=tokens, total_input_tokens=tokens // 2, total_output_tokens=tokens // 2),
            latency_ms=latency_ms,
        )

    def test_basic_efficiency(self):
        results = [
            self._make_result(0.01, 5000, True),
            self._make_result(0.02, 8000, True),
            self._make_result(0.015, 6000, False),
        ]
        eff = compute_efficiency_metrics(results)
        assert eff["total_cost_usd"] == pytest.approx(0.045)
        assert eff["total_tokens"] == 19000
        assert eff["n_passed"] == 2
        assert eff["cost_per_pass"] == pytest.approx(0.0225)


class TestDimensionScore:
    def test_dimension_score_basic(self):
        ds = DimensionScore(
            dimension="completeness",
            weight=0.15,
            likert_median=4,
            likert_mean=3.67,
            likert_std=0.3,
            score=0.75,
            binary_pass=True,
            self_consistency=0.9,
            reasonings=["Good completeness"],
        )
        assert ds.dimension == "completeness"
        assert ds.score * ds.weight == pytest.approx(0.1125)
        assert ds.binary_pass is True

    def test_dimension_score_failing(self):
        ds = DimensionScore(
            dimension="accuracy",
            weight=0.15,
            likert_median=2,
            likert_mean=2.1,
            likert_std=0.5,
            score=0.25,
            binary_pass=False,
            self_consistency=0.8,
            reasonings=["Missing details"],
        )
        assert ds.binary_pass is False
        assert ds.score * ds.weight == pytest.approx(0.0375)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
