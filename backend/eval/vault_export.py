# Vault 导出模块：将评估结果导出到 Obsidian knowledge vault
#
# 目录结构：
#   D:\conclave-knowledge-vault\eval-runs\
#   ├── index.json                           # 全局索引：所有运行记录的元数据
#   └── {YYYY-MM-DD}/                        # 按日期分目录
#       └── {YYYYMMDD-HHMMSS}/               # 单次运行
#           ├── summary.json                 # SuiteResult + 运行配置
#           ├── regression.json              # 回归对比结果（如有）
#           └── cases/                       # 每个用例的完整审计数据
#               ├── {case_id}.json           # CaseResult + 完整 audit 响应
#               └── ...
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# vault 根目录（与 session-checkpoint 共用同一个 vault）
_DEFAULT_VAULT_ROOT = r"D:\conclave-knowledge-vault"
EVAL_RUNS_DIRNAME = "eval-runs"


def _get_vault_root() -> Path:
    """获取 vault 根目录，支持环境变量覆盖"""
    return Path(os.environ.get("CONCLAVE_VAULT_ROOT", _DEFAULT_VAULT_ROOT))


def _get_eval_runs_dir() -> Path:
    """获取 eval-runs 目录路径"""
    return _get_vault_root() / EVAL_RUNS_DIRNAME


def export_to_vault(
    report: dict[str, Any],
    config: dict[str, Any],
    run_label: str = "",
) -> Path:
    """将评估报告导出到 vault

    Args:
        report: SuiteResult 的 dict 形式（来自 asdict()）
        config: 运行配置（config.yaml 解析后的 dict）
        run_label: 可选的运行标签（如 "baseline" / "after-refactor"）

    Returns:
        导出的运行目录路径
    """
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%Y%m%d-%H%M%S")

    # 创建运行目录
    run_dir = _get_eval_runs_dir() / date_str / time_str
    run_dir.mkdir(parents=True, exist_ok=True)
    cases_dir = run_dir / "cases"
    cases_dir.mkdir(exist_ok=True)

    # 1. 写入 summary.json（报告 + 运行元数据）
    summary: dict[str, Any] = {
        "exported_at": now.isoformat(),
        "run_label": run_label,
        "config": _sanitize_config(config),
        "report": report,
    }
    summary_path = run_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # 2. 写入每个用例的完整审计数据
    per_case_results = report.get("per_case_results", [])
    for case_result in per_case_results:
        case_id = case_result.get("case_id", "unknown")
        audit_data = case_result.get("audit_data", {})
        case_data: dict[str, Any] = {
            "case_id": case_id,
            "tier": case_result.get("tier", 0),
            "passed": case_result.get("passed", False),
            "stage_scores": case_result.get("stage_scores", {}),
            "total_tokens": case_result.get("total_tokens", 0),
            "latency_ms": case_result.get("latency_ms", 0.0),
            "errors": case_result.get("errors", []),
            "run_index": case_result.get("run_index", 0),
            "meeting_id": case_result.get("meeting_id", ""),
            "audit_data": audit_data,
        }
        case_path = cases_dir / f"{case_id}.json"
        with open(case_path, "w", encoding="utf-8") as f:
            json.dump(case_data, f, indent=2, ensure_ascii=False)

    # 3. 更新全局索引
    _update_global_index(now, run_dir, report, run_label)

    return run_dir


def _sanitize_config(config: dict[str, Any]) -> dict[str, Any]:
    """清理配置中的敏感信息（API key 等）"""
    sanitized = json.loads(json.dumps(config, default=str))
    # 移除可能的密码字段
    service = sanitized.get("service", {})
    if "admin_password" in service:
        service["admin_password"] = "***"
    judge = sanitized.get("judge", {})
    if "api_key_env" in judge:
        # 保留环境变量名，但不暴露实际 key 值
        pass
    return sanitized


def _update_global_index(
    timestamp: datetime,
    run_dir: Path,
    report: dict[str, Any],
    run_label: str,
) -> None:
    """更新全局索引文件 eval-runs/index.json"""
    index_path = _get_eval_runs_dir() / "index.json"

    # 读取现有索引
    index_data: dict[str, Any] = {"runs": []}
    if index_path.exists():
        try:
            with open(index_path, encoding="utf-8") as f:
                index_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            index_data = {"runs": []}

    # 追加本次运行记录
    run_entry: dict[str, Any] = {
        "timestamp": timestamp.isoformat(),
        "date": timestamp.strftime("%Y-%m-%d"),
        "time": timestamp.strftime("%H:%M:%S"),
        "run_dir": str(run_dir.relative_to(_get_vault_root())),
        "run_label": run_label,
        "total_cases": report.get("total_cases", 0),
        "pass1": report.get("pass1", 0.0),
        "pass3": report.get("pass3", 0.0),
        "avg_score": report.get("avg_score", 0.0),
        "total_tokens": report.get("total_tokens", 0),
        "tier": _extract_tier_from_config(report),
    }
    index_data["runs"].append(run_entry)
    index_data["last_updated"] = timestamp.isoformat()

    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index_data, f, indent=2, ensure_ascii=False)


def _extract_tier_from_config(report: dict[str, Any]) -> int:
    """从报告中提取 tier 信息（per_case_results 中取第一个用例的 tier）"""
    per_case = report.get("per_case_results", [])
    if per_case:
        return int(per_case[0].get("tier", 0))
    return 0


def load_vault_run(run_dir: Path) -> dict[str, Any]:
    """从 vault 加载一次运行的完整数据

    Args:
        run_dir: 运行目录路径（export_to_vault 返回的路径）

    Returns:
        包含 summary + cases 的完整 dict
    """
    summary_path = run_dir / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(f"summary.json not found in {run_dir}")

    with open(summary_path, encoding="utf-8") as f:
        data = json.load(f)

    # 加载每个用例的完整数据
    cases_dir = run_dir / "cases"
    if cases_dir.exists():
        cases: list[dict[str, Any]] = []
        for case_file in sorted(cases_dir.glob("*.json")):
            with open(case_file, encoding="utf-8") as f:
                cases.append(json.load(f))
        data["cases_full"] = cases

    return data


def find_latest_vault_run(tier: int | None = None) -> Path | None:
    """查找 vault 中最新的运行目录

    Args:
        tier: 可选，按 tier 过滤

    Returns:
        最新的运行目录路径，如果不存在返回 None
    """
    index_path = _get_eval_runs_dir() / "index.json"
    if not index_path.exists():
        return None

    with open(index_path, encoding="utf-8") as f:
        index_data = json.load(f)

    runs = index_data.get("runs", [])
    # 按 tier 过滤
    if tier is not None:
        runs = [r for r in runs if r.get("tier") == tier]

    if not runs:
        return None

    # 取最后一条（最新）
    latest = runs[-1]
    run_dir = _get_vault_root() / latest["run_dir"]
    if run_dir.exists():
        return run_dir
    return None
