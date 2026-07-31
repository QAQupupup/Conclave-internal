"""Test case loader - loads and validates cases from JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from eval_v2.dataset.schema import validate_case_dict
from eval_v2.models.case import CaseConfig, EvalCase, TerminalExpectation, UploadedDoc
from eval_v2.models.enums import CaseCategory, DeliverableType

# Dataset root directory
DATASET_ROOT = Path(__file__).parent

CATEGORY_DIRS: dict[CaseCategory, str] = {
    CaseCategory.PRD_OPENAPI: "prd_openapi",
    CaseCategory.DESIGN_DOC: "design_doc",
    CaseCategory.RESEARCH: "research",
    CaseCategory.BUSINESS: "business",
    CaseCategory.EDGE_ADVERSARIAL: "edge_cases",
}


def load_case_from_dict(data: dict[str, Any]) -> EvalCase:
    """从 dict 创建 EvalCase。"""
    errors = validate_case_dict(data)
    if errors:
        raise ValueError(f"Invalid case {data.get('case_id', '?')}: {'; '.join(errors)}")

    config_data = data.get("config", {})
    deliverable_type = DeliverableType(config_data.get("deliverable_type", data.get("category", "prd_openapi")))

    # Map category to default deliverable_type
    category = CaseCategory(data["category"])
    if "deliverable_type" not in config_data:
        _default_deliverable = {
            CaseCategory.PRD_OPENAPI: DeliverableType.PRD_OPENAPI,
            CaseCategory.DESIGN_DOC: DeliverableType.DESIGN_DOC,
            CaseCategory.RESEARCH: DeliverableType.RESEARCH_REPORT,
            CaseCategory.BUSINESS: DeliverableType.BUSINESS_REPORT,
            CaseCategory.EDGE_ADVERSARIAL: DeliverableType.GENERAL,
        }
        deliverable_type = _default_deliverable.get(category, DeliverableType.PRD_OPENAPI)

    config = CaseConfig(
        deliverable_type=deliverable_type,
        flow_plan=config_data.get("flow_plan", "standard"),
        workflow_template=config_data.get("workflow_template", "standard"),
        debate_depth=config_data.get("debate_depth", "standard"),
        dynamic_routing=config_data.get("dynamic_routing", False),
    )

    uploaded_docs = []
    for doc_data in data.get("uploaded_docs", []):
        uploaded_docs.append(
            UploadedDoc(
                filename=doc_data["filename"],
                content=doc_data.get("content"),
            )
        )

    term_data = data.get("expected_terminal", {})
    expected_terminal = TerminalExpectation(
        expected_status=term_data.get("expected_status", "done"),
        expected_stage=term_data.get("expected_stage", "produce"),
        expected_stage_early=term_data.get("expected_stage_early"),
    )

    return EvalCase(
        case_id=data["case_id"],
        category=category,
        tier=data.get("tier", 1),
        topic=data["topic"],
        description=data.get("description", ""),
        config=config,
        uploaded_docs=uploaded_docs,
        expected_terminal=expected_terminal,
        tags=data.get("tags", []),
        notes=data.get("notes", ""),
        rubric_overrides=data.get("rubric_overrides", {}),
    )


def load_case_from_file(filepath: Path) -> EvalCase:
    """从 JSON 文件加载单个用例。"""
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)
    return load_case_from_dict(data)


def load_all(
    categories: list[CaseCategory] | None = None,
    tiers: list[int] | None = None,
    tags: list[str] | None = None,
    max_cases: int | None = None,
) -> list[EvalCase]:
    """加载所有测试用例。

    Args:
        categories: 只加载指定类别
        tiers: 只加载指定层级
        tags: 只加载包含指定标签的用例
        max_cases: 最大用例数
    """
    cases = []
    cats = categories or list(CaseCategory)

    for cat in cats:
        dir_name = CATEGORY_DIRS.get(cat)
        if not dir_name:
            continue
        cat_dir = DATASET_ROOT / dir_name
        if not cat_dir.exists():
            continue

        for json_file in sorted(cat_dir.glob("*.json")):
            try:
                case = load_case_from_file(json_file)
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                print(f"Warning: skipping invalid case {json_file.name}: {e}")
                continue

            # 过滤
            if tiers and case.tier not in tiers:
                continue
            if tags and not any(t in case.tags for t in tags):
                continue

            cases.append(case)
            if max_cases and len(cases) >= max_cases:
                return cases

    return cases


def load_by_id(case_id: str) -> EvalCase | None:
    """按 ID 加载单个用例。"""
    for cat_dir_name in CATEGORY_DIRS.values():
        cat_dir = DATASET_ROOT / cat_dir_name
        if not cat_dir.exists():
            continue
        for json_file in cat_dir.glob("*.json"):
            try:
                case = load_case_from_file(json_file)
                if case.case_id == case_id:
                    return case
            except Exception:
                continue
    return None
