"""Pass@k metrics and stability calculations."""

from __future__ import annotations

from collections import defaultdict

from eval_v2.models.result import CaseRunResult


def compute_pass_at_k(results: list[CaseRunResult], k: int = 1) -> float:
    """计算 Pass@k：每个用例运行 k 次，至少 1 次通过的比例。"""
    if not results:
        return 0.0

    by_case: dict[str, list[CaseRunResult]] = defaultdict(list)
    for r in results:
        by_case[r.case_id].append(r)

    passed = 0
    total = 0
    for case_id, runs in by_case.items():
        total += 1
        # 取前 k 次运行
        runs_k = runs[:k]
        if any(r.passed for r in runs_k):
            passed += 1

    return passed / total if total > 0 else 0.0


def compute_stable_pass_at_k(results: list[CaseRunResult], k: int = 3, threshold: float = 0.67) -> float:
    """Stable Pass@k：每个用例运行 k 次，≥threshold 比例通过才算稳定通过。

    默认 threshold=2/3，即 3次运行至少 2 次通过。
    """
    if not results:
        return 0.0

    by_case: dict[str, list[CaseRunResult]] = defaultdict(list)
    for r in results:
        by_case[r.case_id].append(r)

    stable_passed = 0
    total = 0
    for case_id, runs in by_case.items():
        total += 1
        runs_k = runs[:k]
        pass_count = sum(1 for r in runs_k if r.passed)
        pass_rate = pass_count / len(runs_k) if runs_k else 0
        if pass_rate >= threshold:
            stable_passed += 1

    return stable_passed / total if total > 0 else 0.0


def compute_case_stability(results: list[CaseRunResult]) -> dict[str, bool]:
    """计算每个用例是否稳定（标记 is_stable）。"""
    by_case: dict[str, list[CaseRunResult]] = defaultdict(list)
    for r in results:
        by_case[r.case_id].append(r)

    stability = {}
    for case_id, runs in by_case.items():
        pass_count = sum(1 for r in runs if r.passed)
        pass_rate = pass_count / len(runs) if runs else 0
        stability[case_id] = pass_rate >= 0.67

    return stability


def mark_stability(results: list[CaseRunResult]) -> None:
    """为每个 CaseRunResult 标记 is_stable。"""
    stability = compute_case_stability(results)
    for r in results:
        r.is_stable = stability.get(r.case_id, True)
