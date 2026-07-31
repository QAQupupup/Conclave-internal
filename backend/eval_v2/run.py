"""Conclave Eval V2 - CLI entry point.

Usage:
    python -m eval_v2.run --mode standard --pass-k 3
    python -m eval_v2.run --mode full --html-report --vault-export
    python -m eval_v2.run --mode ablation --pass-k 1
    python -m eval_v2.run --service-check
    python -m eval_v2.run --compare <baseline_suite_id>
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import yaml

from eval_v2.dataset.loader import load_all
from eval_v2.models.enums import CaseCategory, RunMode
from eval_v2.runners.ablation_runner import AblationRunner
from eval_v2.runners.suite_runner import SuiteRunner

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).parent / "config.yaml"


def load_config(config_path: Path | None = None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """加载 YAML 配置文件。"""
    path = config_path or DEFAULT_CONFIG_PATH
    if path.exists():
        with open(path, encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
    else:
        config = {}

    if overrides:
        config = _deep_merge(config, overrides)

    return config


def _deep_merge(base: dict, override: dict) -> dict:
    """深度合并两个 dict。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Conclave Eval V2 - Multi-level evaluation framework")
    parser.add_argument(
        "--mode", choices=["standard", "ablation", "full", "service_check"], default="standard", help="Run mode"
    )
    parser.add_argument("--config", type=str, default=None, help="Path to config YAML")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3], default=None, help="Only run cases of this tier")
    parser.add_argument("--pass-k", type=int, default=3, help="Number of runs per case")
    parser.add_argument("--max-cases", type=int, default=None, help="Max number of cases to run")
    parser.add_argument(
        "--category",
        type=str,
        nargs="+",
        default=None,
        choices=["prd_openapi", "design_doc", "research", "business", "edge_adversarial"],
        help="Only run cases of these categories",
    )
    parser.add_argument("--output", type=str, default=None, help="Output JSON report path")
    parser.add_argument("--html-report", action="store_true", help="Generate HTML report")
    parser.add_argument("--vault-export", action="store_true", help="Export results to Obsidian vault")
    parser.add_argument("--compare", type=str, default=None, help="Compare with baseline suite (suite_id or 'latest')")
    parser.add_argument("--base-url", type=str, default=None, help="SUT base URL override")
    parser.add_argument("--judge-model", type=str, default=None, help="Judge model override")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    return parser.parse_args()


async def cmd_service_check(config: dict[str, Any]) -> int:
    """服务健康检查模式。"""
    from eval_v2.runners.sut_client import SUTClient

    print("Conclave Eval V2 - Service Health Check")
    print("=" * 50)

    async with SUTClient(
        base_url=config.get("target", {}).get("base_url", "http://localhost:8000"),
        admin_username=config.get("target", {}).get("admin_username", "admin"),
        admin_password=config.get("target", {}).get("admin_password", "admin"),
    ) as client:
        # Check health
        print(f"Target: {config['target']['base_url']}")
        healthy = await client.health_check()
        print(f"Service reachable: {'YES' if healthy else 'NO'}")
        if not healthy:
            return 1

        # Try login
        try:
            token = await client.login()
            print(f"Auth: {'OK (JWT)' if token or client.dev_token else 'NO TOKEN'}")
        except Exception as e:
            print(f"Auth: FAILED - {e}")
            return 1

        # Try create meeting
        try:
            mid = await client.create_meeting(topic="health-check-test", deliverable_type="prd_openapi")
            print(f"Create meeting: OK (id={mid})")
        except Exception as e:
            print(f"Create meeting: FAILED - {e}")
            return 1

    print("\nService check PASSED!")
    return 0


async def cmd_run(args: argparse.Namespace, config: dict[str, Any]) -> int:
    """标准/完整/消融模式运行。"""
    # 加载用例
    categories = None
    if args.category:
        categories = [CaseCategory(c) for c in args.category]
    tiers = [args.tier] if args.tier else None

    cases = load_all(categories=categories, tiers=tiers, max_cases=args.max_cases)
    if not cases:
        print("ERROR: No test cases found!")
        return 1

    mode = RunMode(args.mode) if args.mode != "service_check" else RunMode.STANDARD
    pass_k = args.pass_k

    print(f"Conclave Eval V2 - {mode.value.upper()} mode")
    print(f"Cases: {len(cases)}, pass@k: {pass_k}, concurrent: {config.get('execution', {}).get('max_concurrent', 2)}")
    print(f"Target: {config['target']['base_url']}")
    print(f"Judge: {config['judge']['model']} @ {config['judge']['base_url']}")
    print("=" * 60)

    async with SuiteRunner(config) as runner:
        # 登录
        if runner.sut_client:
            await runner.sut_client.login()

        # 运行评估
        suite_result = await runner.run_suite(cases, pass_k=pass_k, mode=mode)

        # 消融实验
        if mode in (RunMode.ABLATION, RunMode.FULL):
            print("\nRunning ablation study (Direct LLM baseline)...")
            ablation_runner = AblationRunner(runner, config)
            ablation = await ablation_runner.run_ablation(cases, suite_result.per_case_results)
            suite_result.ablation = ablation

        # 输出终端摘要
        _print_summary(suite_result)

        # 保存 JSON 报告
        output_path = args.output
        if not output_path:
            reports_dir = Path(__file__).parent / "reports" / "output"
            reports_dir.mkdir(parents=True, exist_ok=True)
            output_path = str(reports_dir / f"eval_report_{suite_result.suite_id}.json")

        output_data = suite_result.model_dump(mode="json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nJSON report saved: {output_path}")

        # HTML 报告
        if args.html_report:
            try:
                from eval_v2.reports.html_report import generate_html_report

                html_path = output_path.replace(".json", ".html")
                generate_html_report(suite_result, html_path)
                print(f"HTML report saved: {html_path}")
            except ImportError as e:
                print(f"HTML report generation not available yet: {e}")

        # Vault 导出
        if args.vault_export:
            try:
                from eval_v2.vault.exporter import export_to_vault

                vault_path = export_to_vault(suite_result, config)
                print(f"Vault export: {vault_path}")
            except ImportError as e:
                print(f"Vault export not available yet: {e}")

        # 回归对比
        if args.compare:
            try:
                from eval_v2.regression.comparator import (
                    compare_with_baseline,
                    format_regression_markdown,
                    load_baseline,
                )

                reports_dir = Path(output_path).parent
                baseline = load_baseline(
                    baseline_id=args.compare,
                    reports_dir=reports_dir,
                    config=config,
                )
                if baseline:
                    comp = compare_with_baseline(suite_result, baseline)
                    print("\n" + "=" * 60)
                    print("REGRESSION COMPARISON")
                    print("-" * 60)
                    print(f"Baseline: {comp.baseline_suite_id}")
                    print(f"Verdict: {comp.summary}")
                    for d in comp.deltas:
                        sig_mark = " *" if d.significant else ""
                        print(
                            f"  {d.metric}: {d.baseline:.3f} -> {d.current:.3f} ({d.delta_pct:+.1f}%) {d.direction}{sig_mark}"
                        )
                    if comp.case_regressions:
                        print(f"  Case regressions: {len(comp.case_regressions)}")
                    if comp.case_improvements:
                        print(f"  Case improvements: {len(comp.case_improvements)}")
                    # Save regression markdown
                    reg_md = format_regression_markdown(comp)
                    reg_path = output_path.replace(".json", "_regression.md")
                    with open(reg_path, "w", encoding="utf-8") as f:
                        f.write(reg_md)
                    print(f"Regression report: {reg_path}")
                    if comp.is_regression:
                        print("\nWARNING: Significant regression detected!")
                else:
                    print(f"WARNING: Baseline '{args.compare}' not found, skipping regression comparison")
            except Exception as e:
                import traceback

                print(f"Regression comparison error: {e}")
                traceback.print_exc()

        return 0 if suite_result.n_model_failures < suite_result.n_cases else 1


def _print_summary(result: Any) -> None:
    """打印终端摘要。"""
    print("\n" + "=" * 60)
    print(f"Suite ID: {result.suite_id}")
    print(f"Duration: {result.duration_seconds:.1f}s")
    print(f"Cases: {result.n_cases}, Runs/case: {result.n_runs_per_case}")
    print("-" * 60)

    ci = result.pass_at_1_ci
    ci_width_pct = (ci[1] - ci[0]) * 100
    print(f"Pass@1: {result.pass_at_1:.1%} [{ci[0]:.1%} - {ci[1]:.1%}] (width: {ci_width_pct:.1f}pp)")
    print(f"Pass@3: {result.pass_at_3:.1%}")
    print(f"Stable Pass@3: {result.pass_at_3_stable:.1%}")
    print(f"Avg Score: {result.avg_aggregate_score:.1f}/100")

    print("-" * 60)
    print("Layer pass rates:")
    for layer, rate in result.layer_pass_rates.items():
        print(f"  {layer}: {rate:.1%}")

    if result.dimension_scores:
        print("Dimension scores:")
        for dim, score in sorted(result.dimension_scores.items()):
            print(f"  {dim}: {score * 100:.1f}")

    print("-" * 60)
    print(
        f"Failures: infra={result.n_infrastructure_failures}, model={result.n_model_failures}, test_bug={result.n_test_bugs}"
    )
    print(f"Cost: ${result.total_cost_usd:.4f} (${result.cost_per_pass:.4f}/pass)")
    print(f"Tokens: {result.total_tokens:,}")
    print(f"Latency: p50={result.latency_p50_ms / 1000:.1f}s, p95={result.latency_p95_ms / 1000:.1f}s")

    if result.ablation and result.ablation.pairwise_win_rate > 0:
        print("-" * 60)
        ab = result.ablation
        print(f"Ablation: Multi-Agent win rate = {ab.pairwise_win_rate:.1%}")
        print(f"  wins={ab.pairwise_wins}, losses={ab.pairwise_losses}, ties={ab.pairwise_ties}")
        print(f"  cost ratio: {ab.cost_ratio:.1f}x")
        if ab.is_significant:
            print(f"  Statistically significant (p={ab.p_value:.4f}, h={ab.cohens_h:.2f})")

    if result.length_bias_pearson_r is not None:
        print("-" * 60)
        bias_note = "WARNING: length bias detected!" if abs(result.length_bias_pearson_r) > 0.7 else "OK"
        print(f"Length bias Pearson r: {result.length_bias_pearson_r:.3f} ({bias_note})")

    if result.model_info.is_same_family:
        print("-" * 60)
        print(
            f"WARNING: Judge model ({result.model_info.judge_model}) is same family as target ({result.model_info.model})! Results may have self-evaluation bias."
        )


def main() -> int:
    args = parse_args()
    setup_logging(args.verbose)

    # 配置 overrides
    overrides: dict[str, Any] = {}
    if args.base_url:
        overrides["target"] = {"base_url": args.base_url}
    if args.judge_model:
        overrides["judge"] = {"model": args.judge_model}

    config_path = Path(args.config) if args.config else None
    config = load_config(config_path, overrides)

    if args.mode == "service_check":
        return asyncio.run(cmd_service_check(config))
    else:
        return asyncio.run(cmd_run(args, config))


if __name__ == "__main__":
    sys.exit(main())
