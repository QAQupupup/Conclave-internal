# 评估框架入口脚本
#
# 用法：
#   python -m eval.run --tier 1 --pass-k 1
#   python -m eval.run --tier 1 --pass-k 3 --config path/to/config.yaml --output report.json
#   python -m eval.run --service-check
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import yaml

from eval.runners.suite_runner import SuiteRunner

EVAL_ROOT = Path(__file__).resolve().parent
DATASET_DIR = EVAL_ROOT / "dataset"
REPORTS_DIR = EVAL_ROOT / "reports"
DEFAULT_CONFIG = EVAL_ROOT / "config.yaml"


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_cases(tier: int) -> list[dict]:
    """加载指定 tier 的测试用例（dataset/tier{N}/*.json）。"""
    tier_dir = DATASET_DIR / f"tier{tier}"
    if not tier_dir.exists():
        return []
    cases: list[dict] = []
    for fp in sorted(tier_dir.glob("*.json")):
        with open(fp, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    item.setdefault("tier", tier)
                    cases.append(item)
        elif isinstance(data, dict):
            data.setdefault("tier", tier)
            cases.append(data)
    return cases


async def service_check(config: dict) -> int:
    """服务就绪检查：探测 /health、/auth/login、/docs 端点。"""
    service = config.get("service", {}) or {}
    base = service.get("base_url", "http://localhost:8000")
    username = service.get("admin_username", "admin")
    password = service.get("admin_password", "admin123")
    ok = True

    print("=" * 50)
    print("Service Readiness Check")
    print("=" * 50)

    async with httpx.AsyncClient(timeout=10.0, trust_env=False) as client:
        # GET /health
        try:
            resp = await client.get(f"{base}/health")
            print(f"GET  /health       -> {resp.status_code}")
            if resp.status_code >= 400:
                ok = False
        except Exception as exc:
            print(f"GET  /health       -> ERROR: {exc}")
            ok = False

        # POST /auth/login
        try:
            resp = await client.post(
                f"{base}/auth/login",
                json={"username": username, "password": password},
            )
            print(f"POST /auth/login   -> {resp.status_code}")
            if resp.status_code >= 400:
                ok = False
            else:
                token = resp.json().get("access_token", "")
                print(f"     token acquired: {bool(token)}")
        except Exception as exc:
            print(f"POST /auth/login   -> ERROR: {exc}")
            ok = False

        # GET /docs
        try:
            resp = await client.get(f"{base}/docs")
            print(f"GET  /docs         -> {resp.status_code}")
            if resp.status_code >= 400:
                ok = False
        except Exception as exc:
            print(f"GET  /docs         -> ERROR: {exc}")
            ok = False

    print("=" * 50)
    print(f"Result: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


def suite_result_to_dict(result: Any) -> dict:
    """将 SuiteResult 转为可 JSON 序列化的 dict（tuple -> list）。"""
    return asdict(result)


def print_summary(report: dict, out_path: Path) -> None:
    print("=" * 60)
    print("Evaluation Summary")
    print("=" * 60)
    # 模型信息
    model_info = report.get("model_info", {}) or {}
    target_info = model_info.get("target", {}) or {}
    judge_info = model_info.get("judge", {}) or {}
    if target_info:
        print(f"Target Model:     {target_info.get('vendor', '?')} / {target_info.get('model', '?')}")
        print(f"  Embedding:      {target_info.get('embedding_model', '?')}")
        print(f"  Reranker:       {target_info.get('reranker_model', '?')}")
    if judge_info:
        print(f"Judge Model:      {judge_info.get('vendor', '?')} / {judge_info.get('model', '?')}")
        print(f"  Judge runs:     {judge_info.get('judge_runs', 1)}")
    print("-" * 60)
    print(f"Total cases:      {report.get('total_cases', 0)}")
    print(f"Pass@1:           {report.get('pass1', 0.0):.3f}")
    ci = report.get("pass1_ci") or [0.0, 0.0]
    print(f"Pass@1 CI (95%):  [{ci[0]:.3f}, {ci[1]:.3f}]")
    print(f"Pass@3:           {report.get('pass3', 0.0):.3f}")
    print(f"Avg score:        {report.get('avg_score', 0.0):.3f}")
    print(f"Total tokens:     {report.get('total_tokens', 0)}")
    print(f"P50 latency (ms): {report.get('p50_latency_ms', 0.0):.0f}")
    print(f"P95 latency (ms): {report.get('p95_latency_ms', 0.0):.0f}")
    print(f"Unstable cases:   {len(report.get('unstable_cases', []))}")
    # 中间阶段退化告警统计
    total_degradation = 0
    high_severity_degradation = 0
    for case in report.get("per_case_results", []):
        audit = case.get("audit_data", {}) or {}
        meeting_data = audit.get("meeting", {}) or {}
        warnings = meeting_data.get("degradation_warnings", []) or []
        total_degradation += len(warnings)
        high_severity_degradation += sum(1 for w in warnings if w.get("severity") == "high")
    if total_degradation > 0:
        print(f"Degradation warns: {total_degradation} (high: {high_severity_degradation})")
    breakdown = report.get("stage_breakdown", {}) or {}
    if breakdown:
        print("Stage pass rate:")
        for stage, rate in breakdown.items():
            print(f"  {stage:<16} {rate:.3f}")
    print(f"Report saved to:  {out_path}")
    print("=" * 60)


async def run_eval(args: argparse.Namespace) -> int:
    config_path = Path(args.config) if args.config else DEFAULT_CONFIG
    if not config_path.exists():
        print(f"Config not found: {config_path}")
        return 1
    config = load_config(config_path)

    cases = load_cases(args.tier)
    if not cases:
        print(f"No cases found for tier {args.tier} in {DATASET_DIR / f'tier{args.tier}'}")
        return 1

    print(f"Loaded {len(cases)} cases for tier {args.tier} (pass_k={args.pass_k})")

    runner = SuiteRunner(config)
    result = await runner.run_suite(cases, pass_k=args.pass_k)
    report = suite_result_to_dict(result)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output) if args.output else REPORTS_DIR / f"tier{args.tier}_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print_summary(report, out_path)

    # Vault 导出
    vault_run_dir: Path | None = None
    if args.vault_export:
        from eval.vault_export import export_to_vault

        vault_run_dir = export_to_vault(report, config, run_label=args.run_label)
        print(f"\nVault export: {vault_run_dir}")

    # 回归对比
    if args.compare:
        await run_regression_compare(args.compare, report, config, vault_run_dir, args.tier)

    return 0


async def run_regression_compare(
    compare_path: str,
    new_report: dict,
    config: dict,
    vault_run_dir: Path | None,
    tier: int,
) -> None:
    """执行回归对比：加载旧报告，与当前报告对比

    compare_path 可以是：
    - "latest"：自动查找 vault 中同 tier 的最新运行
    - "vault"：同 "latest"
    - 文件路径：加载指定 JSON 报告文件
    - vault 运行目录路径：加载 summary.json
    """
    from eval.stats.regression import RegressionJudge
    from eval.vault_export import find_latest_vault_run, load_vault_run

    old_report: dict | None = None

    if compare_path in ("latest", "vault"):
        old_run_dir = find_latest_vault_run(tier=tier)
        if old_run_dir is None:
            print("\n[Regression] No previous vault run found for comparison")
            return
        if vault_run_dir and old_run_dir == vault_run_dir:
            # 当前运行刚写入 vault，取倒数第二条
            from eval.vault_export import _get_eval_runs_dir, _get_vault_root

            index_path = _get_eval_runs_dir() / "index.json"
            if index_path.exists():
                with open(index_path, encoding="utf-8") as f:
                    index_data = json.load(f)
                runs = [r for r in index_data.get("runs", []) if r.get("tier") == tier]
                if len(runs) >= 2:
                    prev = runs[-2]
                    old_run_dir = _get_vault_root() / prev["run_dir"]
                else:
                    print("\n[Regression] Only one run in vault, no previous to compare")
                    return
        print(f"\n[Regression] Comparing with vault run: {old_run_dir}")
        old_data = load_vault_run(old_run_dir)
        old_report = old_data.get("report", {})
    elif Path(compare_path).is_dir():
        # vault 运行目录
        old_data = load_vault_run(Path(compare_path))
        old_report = old_data.get("report", {})
    else:
        # JSON 文件路径
        old_path = Path(compare_path)
        if not old_path.exists():
            print(f"\n[Regression] Compare file not found: {old_path}")
            return
        with open(old_path, encoding="utf-8") as f:
            old_report = json.load(f)

    if not old_report:
        print("\n[Regression] Old report is empty, cannot compare")
        return

    judge = RegressionJudge()
    reg_result = judge.judge(old_report, new_report, config)

    print("\n" + "=" * 60)
    print("Regression Analysis")
    print("=" * 60)
    print(f"Is regression: {reg_result.is_regression}")
    print(f"Severity:      {reg_result.severity}")
    if reg_result.reasons:
        print("Reasons:")
        for r in reg_result.reasons:
            print(f"  - {r}")
    else:
        print("No regression detected.")
    print("=" * 60)

    # 如果有 vault 导出，将回归结果写入运行目录
    if vault_run_dir:
        reg_path = vault_run_dir / "regression.json"
        with open(reg_path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "is_regression": reg_result.is_regression,
                    "reasons": reg_result.reasons,
                    "severity": reg_result.severity,
                    "compared_with": str(old_run_dir) if compare_path in ("latest", "vault") else compare_path,
                },
                f,
                indent=2,
                ensure_ascii=False,
            )
        print(f"Regression result saved to: {reg_path}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Conclave evaluation framework runner",
        prog="python -m eval.run",
    )
    parser.add_argument("--tier", type=int, default=1, help="test tier to run (1/2/3)")
    parser.add_argument("--pass-k", type=int, default=1, help="pass@k repetitions per case")
    parser.add_argument("--config", type=str, default="", help="path to config.yaml")
    parser.add_argument("--output", type=str, default="", help="output report JSON path")
    parser.add_argument(
        "--service-check",
        action="store_true",
        help="run service readiness check only (health/auth/docs)",
    )
    parser.add_argument(
        "--vault-export",
        action="store_true",
        help="export results to Obsidian knowledge vault (D:\\conclave-knowledge-vault\\eval-runs\\)",
    )
    parser.add_argument(
        "--run-label",
        type=str,
        default="",
        help="label for this run (e.g. 'baseline', 'after-refactor')",
    )
    parser.add_argument(
        "--compare",
        type=str,
        default="",
        help="regression comparison: 'latest' to auto-find previous vault run, "
        "or path to old report JSON / vault run directory",
    )
    return parser.parse_args(argv)


async def main() -> int:
    args = parse_args()
    if args.service_check:
        config_path = Path(args.config) if args.config else DEFAULT_CONFIG
        config = load_config(config_path) if config_path.exists() else {}
        return await service_check(config)
    return await run_eval(args)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
