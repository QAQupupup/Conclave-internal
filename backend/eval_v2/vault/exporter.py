"""Vault exporter for Obsidian knowledge vault integration.

Exports evaluation results to D:\\conclave-knowledge-vault\\eval-history\\
as Markdown files, following ADR-012 session checkpoint conventions.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from eval_v2.models.result import SuiteResult

DEFAULT_VAULT_ROOT = Path(r"D:\conclave-knowledge-vault")
EVAL_DIR_NAME = "eval-history"


def _get_eval_dir(config: dict[str, Any]) -> Path:
    vault_root = Path(config.get("vault", {}).get("root_path", str(DEFAULT_VAULT_ROOT)))
    eval_dir = vault_root / config.get("vault", {}).get("eval_dir", EVAL_DIR_NAME)
    eval_dir.mkdir(parents=True, exist_ok=True)
    return eval_dir


def export_to_vault(result: SuiteResult, config: dict[str, Any]) -> str:
    """导出评估结果到 Obsidian Vault，返回导出的 Markdown 文件路径。"""
    eval_dir = _get_eval_dir(config)

    md_path = eval_dir / f"eval-{result.suite_id}.md"
    json_path = eval_dir / f"eval-{result.suite_id}.json"

    # Write full JSON data
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.model_dump(mode="json"), f, ensure_ascii=False, indent=2, default=str)

    # Write Markdown summary
    md_content = _build_markdown_summary(result, json_path)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    # Update monthly index
    _update_index(eval_dir, result, md_path)

    return str(md_path)


def _build_markdown_summary(result: SuiteResult, json_path: Path) -> str:
    ci = result.pass_at_1_ci
    mi = result.model_info

    lines = [
        f"# Eval V2 Report - {result.suite_id}",
        "",
        f"- **Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Mode**: {result.mode}",
        f"- **Target Model**: {mi.model or 'unknown'} @ {mi.provider or 'unknown'}",
        f"- **Judge Model**: {mi.judge_model or 'unknown'}",
        f"- **Same Family Warning**: {'YES' if mi.is_same_family else 'NO'}",
        f"- **Duration**: {result.duration_seconds:.0f}s",
        f"- **Cases**: {result.n_cases} x {result.n_runs_per_case} runs",
        "",
        "## Key Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Pass@1 | {result.pass_at_1:.1%} [{ci[0]:.1%} - {ci[1]:.1%}] |",
        f"| Pass@3 | {result.pass_at_3:.1%} |",
        f"| Stable Pass@3 | {result.pass_at_3_stable:.1%} |",
        f"| Avg Score | {result.avg_aggregate_score:.1f}/100 |",
        f"| Total Cost | ${result.total_cost_usd:.4f} |",
        f"| Cost/Pass | ${result.cost_per_pass:.4f} |",
        f"| Total Tokens | {result.total_tokens:,} |",
        f"| Latency p50 | {result.latency_p50_ms / 1000:.1f}s |",
        f"| Latency p95 | {result.latency_p95_ms / 1000:.1f}s |",
        "",
        "## Layer Pass Rates",
        "",
        "| Layer | Pass Rate |",
        "|-------|-----------|",
    ]

    labels = {
        "l0_health": "L0 Health",
        "l1_process": "L1 Process Integrity",
        "l2_internal": "L2 Internal Quality",
        "l3_semantic": "L3 Semantic Quality",
        "l4_comparative": "L4 Comparative",
    }
    for k, v in result.layer_pass_rates.items():
        label = labels.get(k, k)
        lines.append(f"| {label} | {v:.1%} |")

    if result.dimension_scores:
        lines.extend(
            [
                "",
                "## L3 Semantic Dimensions",
                "",
                "| Dimension | Score |",
                "|-----------|-------|",
            ]
        )
        for dim, score in sorted(result.dimension_scores.items()):
            lines.append(f"| {dim} | {score * 100:.1f} |")

    lines.extend(
        [
            "",
            "## Failure Breakdown",
            "",
            f"- Infrastructure: {result.n_infrastructure_failures}",
            f"- Model/System: {result.n_model_failures}",
            f"- Test Bug: {result.n_test_bugs}",
        ]
    )

    if result.ablation and result.ablation.pairwise_win_rate > 0:
        ab = result.ablation
        lines.extend(
            [
                "",
                "## Ablation: Multi-Agent vs Direct LLM",
                "",
                f"- Multi-Agent Score: {ab.multi_agent_score * 100:.1f}",
                f"- Direct LLM Score: {ab.direct_llm_score * 100:.1f}",
                f"- Uplift: {ab.uplift * 100:+.1f}pp",
                f"- Pairwise Win Rate: {ab.pairwise_win_rate:.1%} ({ab.pairwise_wins}W/{ab.pairwise_losses}L/{ab.pairwise_ties}T)",
                f"- p-value: {ab.p_value:.4f}",
                f"- Significant: {'YES' if ab.is_significant else 'NO'}",
                f"- Cost Ratio: {ab.cost_ratio:.1f}x",
            ]
        )

    if result.prompt_snapshot_id:
        lines.extend(
            [
                "",
                "## Prompt Snapshot (ADR-015)",
                "",
                f"- Snapshot ID: `{result.prompt_snapshot_id}`",
                f"- Git Commit: {result.git_commit or 'unknown'}",
                f"- Git Dirty: {'YES' if result.git_dirty else 'NO'}",
                f"- Prompt Files: {len(result.prompt_snapshot)}",
            ]
        )

    lines.extend(
        [
            "",
            "## Failed Cases",
            "",
        ]
    )
    failed = [r for r in result.per_case_results if r.run_index == 0 and not r.passed]
    if failed:
        for r in failed:
            fc = r.failure_class.value if r.failure_class else "unknown"
            lines.append(f"- `{r.case_id}`: score={r.aggregate_score:.1f}, class={fc}")
    else:
        lines.append("None! All cases passed.")

    lines.extend(
        [
            "",
            "---",
            f"Full data: [[{json_path.name}]]",
        ]
    )

    return "\n".join(lines)


def _update_index(eval_dir: Path, result: SuiteResult, md_path: Path) -> None:
    """更新月度索引文件。"""
    month = datetime.now().strftime("%Y-%m")
    index_path = eval_dir / f"index-{month}.md"

    entry = f"- [[{md_path.name}]] | {result.suite_id} | Pass@1={result.pass_at_1:.1%} | Score={result.avg_aggregate_score:.1f} | ${result.total_cost_usd:.3f}"

    if index_path.exists():
        with open(index_path, encoding="utf-8") as f:
            content = f.read()
        if entry not in content:
            content += "\n" + entry
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        content = f"# Eval History - {month}\n\n{entry}\n"
        with open(index_path, "w", encoding="utf-8") as f:
            f.write(content)


def load_history(eval_dir: Path | None = None, config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """加载历史评估记录用于趋势分析。"""
    if eval_dir is None and config:
        eval_dir = _get_eval_dir(config)
    elif eval_dir is None:
        eval_dir = DEFAULT_VAULT_ROOT / EVAL_DIR_NAME

    if not eval_dir.exists():
        return []

    records = []
    for json_file in sorted(eval_dir.glob("eval-*.json")):
        try:
            with open(json_file, encoding="utf-8") as f:
                data = json.load(f)
            # Extract key metrics for trend
            records.append(
                {
                    "suite_id": data.get("suite_id"),
                    "timestamp": data.get("timestamp", ""),
                    "pass_at_1": data.get("pass_at_1"),
                    "pass_at_3": data.get("pass_at_3"),
                    "avg_score": data.get("avg_aggregate_score"),
                    "total_cost": data.get("total_cost_usd"),
                    "n_cases": data.get("n_cases"),
                    "model_info": data.get("model_info", {}),
                    # ADR-015 Phase 1：版本绑定字段，供后续逐话题得分矩阵使用
                    "prompt_snapshot_id": data.get("prompt_snapshot_id", ""),
                    "git_commit": data.get("git_commit", ""),
                }
            )
        except (json.JSONDecodeError, KeyError):
            continue
    return records
