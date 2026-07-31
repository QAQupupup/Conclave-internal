"""Efficiency metrics: cost_per_pass, Pareto frontier."""

from __future__ import annotations

from typing import Any

from eval_v2.models.result import CaseRunResult


def compute_efficiency_metrics(results: list[CaseRunResult]) -> dict[str, Any]:
    """计算效率指标。"""
    if not results:
        return {
            "total_cost_usd": 0.0,
            "cost_per_pass": 0.0,
            "total_tokens": 0,
            "avg_cost_per_case": 0.0,
        }

    total_cost = sum(r.cost.total_cost_usd for r in results)
    total_tokens = sum(r.tokens.total_tokens for r in results)
    n_passed = sum(1 for r in results if r.passed)
    n_cases = len(results)

    cost_per_pass = total_cost / n_passed if n_passed > 0 else float("inf")
    avg_cost = total_cost / n_cases if n_cases > 0 else 0.0

    return {
        "total_cost_usd": total_cost,
        "cost_per_pass": cost_per_pass,
        "total_tokens": total_tokens,
        "avg_cost_per_case": avg_cost,
        "n_passed": n_passed,
        "n_failed": n_cases - n_passed,
    }


def compute_pareto_frontier(results: list[CaseRunResult]) -> list[dict[str, Any]]:
    """计算 Pareto 前沿（质量 vs 成本）。

    返回非支配解：不存在另一个用例同时具有更高分和更低成本。
    """
    # 每个用例取其最佳运行结果（最高 aggregate_score）
    best_by_case: dict[str, CaseRunResult] = {}
    for r in results:
        if r.case_id not in best_by_case or r.aggregate_score > best_by_case[r.case_id].aggregate_score:
            best_by_case[r.case_id] = r

    points = []
    for r in best_by_case.values():
        points.append(
            {
                "case_id": r.case_id,
                "score": r.aggregate_score,
                "cost": r.cost.total_cost_usd,
                "passed": r.passed,
            }
        )

    # 找 Pareto 前沿
    pareto = []
    for i, p in enumerate(points):
        dominated = False
        for j, q in enumerate(points):
            if i == j:
                continue
            # q 支配 p: q.score >= p.score 且 q.cost <= p.cost，且至少一个严格不等
            if q["score"] >= p["score"] and q["cost"] <= p["cost"]:
                if q["score"] > p["score"] or q["cost"] < p["cost"]:
                    dominated = True
                    break
        if not dominated:
            pareto.append(p)

    # 按分数降序排列
    pareto.sort(key=lambda x: (-x["score"], x["cost"]))
    return pareto
