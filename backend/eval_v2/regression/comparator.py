"""Historical trend analysis and regression comparison.

Compares current evaluation results against a baseline (previous run)
to detect regressions and improvements using statistical significance tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from eval_v2.models.result import SuiteResult
from eval_v2.stats.effect_size import cohens_h
from eval_v2.stats.significance import fisher_exact_test
from eval_v2.vault.exporter import load_history


@dataclass
class RegressionDelta:
    """Single metric regression delta."""

    metric: str
    baseline: float
    current: float
    delta: float
    delta_pct: float
    direction: str  # "improvement", "regression", "unchanged"
    significant: bool = False
    p_value: float | None = None


@dataclass
class RegressionComparison:
    """Full regression comparison result."""

    baseline_suite_id: str = ""
    current_suite_id: str = ""
    is_regression: bool = False
    summary: str = ""
    deltas: list[RegressionDelta] = field(default_factory=list)
    case_regressions: list[dict[str, Any]] = field(default_factory=list)
    case_improvements: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_suite_id": self.baseline_suite_id,
            "current_suite_id": self.current_suite_id,
            "is_regression": self.is_regression,
            "summary": self.summary,
            "deltas": [d.__dict__ for d in self.deltas],
            "case_regressions": self.case_regressions,
            "case_improvements": self.case_improvements,
        }


def compare_with_baseline(
    current: SuiteResult,
    baseline: SuiteResult,
    significance_threshold: float = 0.05,
) -> RegressionComparison:
    """将当前结果与基线进行回归对比。"""
    comp = RegressionComparison(
        baseline_suite_id=baseline.suite_id,
        current_suite_id=current.suite_id,
    )

    # Key metric comparisons
    metrics = [
        ("pass_at_1", baseline.pass_at_1, current.pass_at_1, "higher"),
        ("pass_at_3", baseline.pass_at_3, current.pass_at_3, "higher"),
        ("pass_at_3_stable", baseline.pass_at_3_stable, current.pass_at_3_stable, "higher"),
        ("avg_score", baseline.avg_aggregate_score / 100, current.avg_aggregate_score / 100, "higher"),
        ("total_cost", baseline.total_cost_usd, current.total_cost_usd, "lower"),
        ("latency_p95_ms", baseline.latency_p95_ms / 1000, current.latency_p95_ms / 1000, "lower"),
    ]

    for name, b, c, better_dir in metrics:
        delta = c - b
        delta_pct = (delta / abs(b) * 100) if b != 0 else 0
        direction = "unchanged"
        if abs(delta_pct) < 2:
            direction = "unchanged"
        elif better_dir == "higher":
            direction = "improvement" if delta > 0 else "regression"
        else:
            direction = "improvement" if delta < 0 else "regression"

        # Fisher's exact test for pass rates
        p_val = None
        sig = False
        if name.startswith("pass_at"):
            n_b = baseline.n_cases * baseline.n_runs_per_case
            n_c = current.n_cases * current.n_runs_per_case
            b_passes = int(b * n_b)
            c_passes = int(c * n_c)
            p_val = fisher_exact_test(
                a_successes=b_passes,
                a_total=n_b,
                b_successes=c_passes,
                b_total=n_c,
            )
            sig = p_val < significance_threshold
        elif name == "avg_score":
            # Use Cohen's h for effect size on score differences
            h = cohens_h(b, c)
            sig = abs(h) > 0.3  # small-medium effect threshold

        comp.deltas.append(
            RegressionDelta(
                metric=name,
                baseline=b,
                current=c,
                delta=delta,
                delta_pct=delta_pct,
                direction=direction,
                significant=sig,
                p_value=p_val,
            )
        )

    # Per-case comparison (only for pass@1)
    b_cases = {r.case_id: r for r in baseline.per_case_results if r.run_index == 0}
    c_cases = {r.case_id: r for r in current.per_case_results if r.run_index == 0}

    for cid, c_res in c_cases.items():
        if cid not in b_cases:
            continue
        b_res = b_cases[cid]
        if b_res.passed and not c_res.passed:
            comp.case_regressions.append(
                {
                    "case_id": cid,
                    "baseline_score": b_res.aggregate_score,
                    "current_score": c_res.aggregate_score,
                    "score_delta": c_res.aggregate_score - b_res.aggregate_score,
                    "failure_class": c_res.failure_class.value if c_res.failure_class else "unknown",
                }
            )
        elif not b_res.passed and c_res.passed:
            comp.case_improvements.append(
                {
                    "case_id": cid,
                    "baseline_score": b_res.aggregate_score,
                    "current_score": c_res.aggregate_score,
                    "score_delta": c_res.aggregate_score - b_res.aggregate_score,
                }
            )

    # Determine if overall regression
    regressing_metrics = [d for d in comp.deltas if d.direction == "regression" and d.significant]
    improving_metrics = [d for d in comp.deltas if d.direction == "improvement" and d.significant]

    if regressing_metrics and not improving_metrics:
        comp.is_regression = True
        comp.summary = f"REGRESSION detected: {len(regressing_metrics)} metric(s) significantly regressed."
    elif improving_metrics and not regressing_metrics:
        comp.is_regression = False
        comp.summary = f"IMPROVEMENT: {len(improving_metrics)} metric(s) significantly improved."
    elif regressing_metrics and improving_metrics:
        comp.is_regression = any(d.metric.startswith("pass_at") for d in regressing_metrics)
        comp.summary = f"MIXED: {len(regressing_metrics)} regressions, {len(improving_metrics)} improvements."
    else:
        comp.is_regression = False
        comp.summary = "No significant changes detected."

    return comp


def load_baseline(
    baseline_id: str | None = None,
    reports_dir: Path | None = None,
    vault_dir: Path | None = None,
    config: dict[str, Any] | None = None,
) -> SuiteResult | None:
    """加载基线结果。

    Args:
        baseline_id: "latest" 或具体 suite_id
        reports_dir: JSON reports 目录
        vault_dir: Vault 目录
    """
    candidates: list[Path] = []

    if reports_dir:
        if baseline_id and baseline_id != "latest":
            p = reports_dir / f"eval_report_{baseline_id}.json"
            if p.exists():
                candidates.append(p)
        else:
            candidates.extend(sorted(reports_dir.glob("eval_report_*.json"), reverse=True))

    if not candidates and vault_dir:
        # Try vault
        records = load_history(eval_dir=vault_dir)
        if records:
            # Load most recent record's JSON
            target_id = baseline_id if baseline_id and baseline_id != "latest" else records[-1]["suite_id"]
            p = vault_dir / f"eval-{target_id}.json"
            if p.exists():
                candidates.append(p)

    if not candidates:
        return None

    # Load first candidate (sorted by mtime desc)
    for p in candidates[:1]:
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            return SuiteResult(**data)
        except Exception as e:
            print(f"Warning: could not load baseline {p}: {e}")
            continue

    return None


def format_regression_markdown(comp: RegressionComparison) -> str:
    """格式化回归对比为 Markdown。"""
    lines = [
        f"# Regression Comparison: {comp.current_suite_id} vs {comp.baseline_suite_id}",
        "",
        f"**Verdict**: {comp.summary}",
        "",
        "## Metric Deltas",
        "",
        "| Metric | Baseline | Current | Delta | Direction | Significant |",
        "|--------|----------|---------|-------|-----------|-------------|",
    ]
    for d in comp.deltas:
        arrow = "↑" if d.direction == "improvement" else ("↓" if d.direction == "regression" else "→")
        p_str = f"p={d.p_value:.4f}" if d.p_value is not None else "-"
        lines.append(
            f"| {d.metric} | {d.baseline:.3f} | {d.current:.3f} | {d.delta:+.3f} ({d.delta_pct:+.1f}%) {arrow} | {d.direction} | {'YES ' + p_str if d.significant else 'NO'} |"
        )

    if comp.case_regressions:
        lines.extend(
            [
                "",
                "## Case Regressions",
                "",
            ]
        )
        for cr in comp.case_regressions:
            lines.append(
                f"- `{cr['case_id']}`: {cr['baseline_score']:.1f} → {cr['current_score']:.1f} ({cr['score_delta']:+.1f}), class={cr['failure_class']}"
            )

    if comp.case_improvements:
        lines.extend(
            [
                "",
                "## Case Improvements",
                "",
            ]
        )
        for ci in comp.case_improvements:
            lines.append(
                f"- `{ci['case_id']}`: {ci['baseline_score']:.1f} → {ci['current_score']:.1f} ({ci['score_delta']:+.1f})"
            )

    return "\n".join(lines)
