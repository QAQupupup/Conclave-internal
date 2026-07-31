"""Evaluation models and data structures."""

from eval_v2.models.audit import (
    AuditSnapshot,
    CostSnapshot,
    DegradationSummary,
    MeetingSnapshot,
    StageCompletion,
    TraceSnapshot,
)
from eval_v2.models.case import CaseConfig, EvalCase, TerminalExpectation, UploadedDoc
from eval_v2.models.enums import (
    CaseCategory,
    ConfidenceLevel,
    DeliverableType,
    FailureClass,
    JudgeScale,
    Level,
)
from eval_v2.models.judgment import CoTJudgment, KappaResult, PairwiseJudgment
from eval_v2.models.result import (
    AblationComparison,
    CaseRunResult,
    CheckResult,
    CostBreakdown,
    DimensionScore,
    FailureRecord,
    LayerResult,
    ModelInfo,
    RegressionSummary,
    SuiteResult,
    TokenBreakdown,
)

__all__ = [
    "AblationComparison",
    "AuditSnapshot",
    "CaseCategory",
    "CaseConfig",
    "CaseRunResult",
    "CheckResult",
    "CoTJudgment",
    "ConfidenceLevel",
    "CostBreakdown",
    "CostSnapshot",
    "DegradationSummary",
    "DeliverableType",
    "DimensionScore",
    "EvalCase",
    "FailureClass",
    "FailureRecord",
    "JudgeScale",
    "KappaResult",
    "LayerResult",
    "Level",
    "MeetingSnapshot",
    "ModelInfo",
    "PairwiseJudgment",
    "RegressionSummary",
    "StageCompletion",
    "SuiteResult",
    "TerminalExpectation",
    "TokenBreakdown",
    "TraceSnapshot",
    "UploadedDoc",
]
