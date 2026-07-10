# 回归分析基础设施：基线记录、列出、对比
# 用于捕获会议运行质量的快照，支持版本间回归对比
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.orchestrator.runner import get_state

router = APIRouter(prefix="/regression", tags=["regression"])

# 基线数据存储目录：backend/data/regression/
_REGRESSION_DIR: Path = Path(__file__).resolve().parents[2] / "data" / "regression"

# [UNIQ-01 修复] baseline_id 合法字符白名单
# 旧版 _load_baseline 用 Path / f"{baseline_id}.json"，若 baseline_id 含 "../"
# 可逃出 _REGRESSION_DIR 目录读取任意 JSON（如其他用户的数据）。
# 限定 baseline_id 仅由 [a-zA-Z0-9-_] 构成，与创建时的 uuid4().hex[:8] 前缀一致。
import re as _re
_BASELINE_ID_PATTERN = _re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


# ---------- 请求/响应模型 ----------

class BaselineRequest(BaseModel):
    """创建基线请求"""
    meeting_id: str = Field(..., description="会议 ID")


class BaselineSummary(BaseModel):
    """基线摘要（列表项）"""
    baseline_id: str
    created_at: str
    meeting_id: str
    topic: str
    stages_completed: int
    claims_count: int
    confidence_all_high: bool


# ---------- 指标提取 ----------

def _extract_metrics(state: Any) -> dict[str, Any]:
    """从会议状态提取完整指标集

    汇总 stats + trace + claims + artifacts 的质量评分。
    """
    trace_summary = state.llm_trace.summary()
    drift_count = sum(1 for d in state.drift_log if d.get("is_drift"))

    # 置信度：所有阶段是否全为 high
    confidence_values = list(state.confidence_flags.values())
    confidence_all_high = all(v == "high" for v in confidence_values) if confidence_values else False

    # fallback 统计
    fallback_count = trace_summary.get("fallback_calls", 0)

    # stages completed（通过 conclusion_chain 锁定数判断）
    stages_completed = len(state.conclusion_chain.conclusions)

    # artifact 指标
    artifact = state.artifact or {}
    prd = artifact.get("prd", {}) if isinstance(artifact, dict) else {}
    openapi = artifact.get("openapi", "") if isinstance(artifact, dict) else ""
    api_endpoints = prd.get("api_endpoints", []) if isinstance(prd, dict) else []

    # adopted_claims
    decision_record = state.decision_record or {}
    adopted_claims = decision_record.get("adopted_claims", []) if isinstance(decision_record, dict) else []

    # 总耗时：trace 中所有调用的延迟之和（stub 模式下为 0）
    total_duration_ms = sum(c.latency_ms for c in state.llm_trace.calls)

    # trace stage_stats 用于阶段级指标
    stage_stats = trace_summary.get("stage_stats", {})

    metrics = {
        "total_duration_ms": total_duration_ms,
        "llm_calls": trace_summary.get("total_calls", 0),
        "confidence_all_high": confidence_all_high,
        "stages_completed": stages_completed,
        "claims_count": len(state.claims),
        "conflicts_count": len(state.conflicts),
        "evidence_count": sum(
            len(es.get("assessments", [])) for es in state.evidence_set
        ),
        "adopted_claims_count": len(adopted_claims),
        "api_endpoints_count": len(api_endpoints),
        "openapi_length": len(openapi),
        "fallback_count": fallback_count,
        "drift_count": drift_count,
    }

    # 阶段级指标
    stage_metrics: dict[str, dict[str, Any]] = {}
    for stage_name in ["clarify", "intra_team", "cross_team", "evidence_check", "arbitrate", "produce"]:
        ss = stage_stats.get(stage_name, {})
        stage_metrics[stage_name] = {
            "calls": ss.get("calls", 0),
            "valid": ss.get("valid", 0),
            "fallback": ss.get("fallback", 0),
            "avg_latency_ms": ss.get("avg_latency_ms", 0),
            "confidence": state.confidence_flags.get(stage_name, "unknown"),
        }

    return {
        "metrics": metrics,
        "stage_metrics": stage_metrics,
    }


# ---------- 存储操作 ----------

def _ensure_dir() -> None:
    """确保基线数据目录存在"""
    _REGRESSION_DIR.mkdir(parents=True, exist_ok=True)


def _save_baseline(baseline: dict[str, Any]) -> None:
    """保存基线到 JSON 文件"""
    _ensure_dir()
    # [UNIQ-01 修复] 防御性检查（虽然 baseline_id 来自 uuid4().hex 但接口应稳健）
    if not _BASELINE_ID_PATTERN.match(baseline.get("baseline_id", "")):
        raise ValueError(f"非法 baseline_id: {baseline.get('baseline_id')!r}")
    filepath = (_REGRESSION_DIR / f"{baseline['baseline_id']}.json").resolve()
    # 再次检查：解析后仍在 _REGRESSION_DIR 内
    if _REGRESSION_DIR.resolve() not in filepath.parents:
        raise ValueError("baseline_id 解析后跳出存储目录")
    filepath.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _load_baseline(baseline_id: str) -> dict[str, Any] | None:
    """加载单个基线

    [UNIQ-01 修复] 强校验 baseline_id 字符集，防止路径穿越。
    """
    if not _BASELINE_ID_PATTERN.match(baseline_id):
        raise HTTPException(status_code=400, detail=f"非法 baseline_id: {baseline_id!r}")
    filepath = (_REGRESSION_DIR / f"{baseline_id}.json").resolve()
    # 二次防御：解析后必须仍在 _REGRESSION_DIR 内
    if _REGRESSION_DIR.resolve() not in filepath.parents:
        raise HTTPException(status_code=400, detail="baseline_id 越界")
    if not filepath.exists():
        return None
    return json.loads(filepath.read_text(encoding="utf-8"))


def _list_baseline_files() -> list[Path]:
    """列出所有基线文件（按创建时间排序）"""
    if not _REGRESSION_DIR.exists():
        return []
    files = sorted(
        _REGRESSION_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
    )
    return files


# ---------- 端点 ----------

@router.post("/baseline")
async def create_baseline(req: BaselineRequest) -> dict[str, Any]:
    """记录当前会议的基线数据

    提取会议 stats + trace + claims + artifacts 质量评分，
    保存为 JSON 文件供后续回归对比。
    """
    state = get_state(req.meeting_id)
    if state is None:
        raise HTTPException(status_code=404, detail="会议不存在或未在内存中")

    extracted = _extract_metrics(state)

    baseline = {
        "baseline_id": f"bl-{uuid.uuid4().hex[:8]}",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "meeting_id": req.meeting_id,
        "topic": state.topic,
        "metrics": extracted["metrics"],
        "stage_metrics": extracted["stage_metrics"],
    }

    _save_baseline(baseline)
    return baseline


@router.get("/baselines")
async def list_baselines() -> list[dict[str, Any]]:
    """列出所有基线"""
    baselines: list[dict[str, Any]] = []
    for filepath in _list_baseline_files():
        try:
            data = json.loads(filepath.read_text(encoding="utf-8"))
            baselines.append({
                "baseline_id": data["baseline_id"],
                "created_at": data["created_at"],
                "meeting_id": data["meeting_id"],
                "topic": data.get("topic", ""),
                "stages_completed": data.get("metrics", {}).get("stages_completed", 0),
                "claims_count": data.get("metrics", {}).get("claims_count", 0),
                "confidence_all_high": data.get("metrics", {}).get("confidence_all_high", False),
            })
        except (json.JSONDecodeError, KeyError):
            continue
    return baselines


@router.get("/compare/{baseline_id}")
async def compare_baseline(baseline_id: str) -> dict[str, Any]:
    """对比指定基线与当前数据的差异

    加载基线，获取同一会议的当前指标，逐项对比并计算差值。
    """
    baseline = _load_baseline(baseline_id)
    if baseline is None:
        raise HTTPException(status_code=404, detail=f"基线 {baseline_id} 不存在")

    meeting_id = baseline.get("meeting_id", "")
    state = get_state(meeting_id)

    if state is None:
        return {
            "baseline_id": baseline_id,
            "meeting_id": meeting_id,
            "status": "unavailable",
            "message": "会议当前不在内存中，无法获取当前数据进行对比",
            "baseline": baseline,
            "current": None,
            "diff": None,
        }

    current = _extract_metrics(state)
    baseline_metrics = baseline.get("metrics", {})
    current_metrics = current["metrics"]
    baseline_stage = baseline.get("stage_metrics", {})
    current_stage = current["stage_metrics"]

    # 逐项计算差值
    metric_diffs: dict[str, dict[str, Any]] = {}
    for key in baseline_metrics:
        old_val = baseline_metrics.get(key)
        new_val = current_metrics.get(key)
        diff = None
        if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
            diff = new_val - old_val
        metric_diffs[key] = {
            "baseline": old_val,
            "current": new_val,
            "diff": diff,
        }

    stage_diffs: dict[str, dict[str, Any]] = {}
    for stage_name in baseline_stage:
        old_s = baseline_stage.get(stage_name, {})
        new_s = current_stage.get(stage_name, {})
        stage_diffs[stage_name] = {
            "confidence_baseline": old_s.get("confidence"),
            "confidence_current": new_s.get("confidence"),
            "calls_baseline": old_s.get("calls", 0),
            "calls_current": new_s.get("calls", 0),
            "avg_latency_diff": (
                new_s.get("avg_latency_ms", 0) - old_s.get("avg_latency_ms", 0)
                if isinstance(old_s.get("avg_latency_ms"), (int, float))
                and isinstance(new_s.get("avg_latency_ms"), (int, float))
                else None
            ),
        }

    return {
        "baseline_id": baseline_id,
        "meeting_id": meeting_id,
        "status": "compared",
        "baseline": baseline,
        "current": current,
        "diff": {
            "metrics": metric_diffs,
            "stage_metrics": stage_diffs,
        },
    }
