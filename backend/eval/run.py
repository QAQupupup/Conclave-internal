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
        except Exception as exc:  # noqa: BLE001
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
        except Exception as exc:  # noqa: BLE001
            print(f"POST /auth/login   -> ERROR: {exc}")
            ok = False

        # GET /docs
        try:
            resp = await client.get(f"{base}/docs")
            print(f"GET  /docs         -> {resp.status_code}")
            if resp.status_code >= 400:
                ok = False
        except Exception as exc:  # noqa: BLE001
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
        print(
            f"No cases found for tier {args.tier} "
            f"in {DATASET_DIR / f'tier{args.tier}'}"
        )
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
    return 0


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
