"""Test case JSON Schema validation."""

from __future__ import annotations

from typing import Any

# JSON Schema for test case files
CASE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["case_id", "category", "topic"],
    "properties": {
        "case_id": {"type": "string", "pattern": "^[a-z0-9][a-z0-9\\-]*$"},
        "category": {
            "type": "string",
            "enum": ["prd_openapi", "design_doc", "research", "business", "edge_adversarial"],
        },
        "tier": {"type": "integer", "minimum": 1, "maximum": 3},
        "topic": {"type": "string", "minLength": 0, "maxLength": 20000},
        "description": {"type": "string"},
        "config": {
            "type": "object",
            "properties": {
                "deliverable_type": {
                    "type": "string",
                    "enum": [
                        "prd_openapi",
                        "design_doc",
                        "research_report",
                        "business_report",
                        "tech_spec",
                        "meeting_summary",
                        "architecture_decision",
                        "general",
                    ],
                },
                "flow_plan": {"type": "string"},
                "workflow_template": {"type": "string"},
                "debate_depth": {"type": "string", "enum": ["light", "standard", "deep"]},
                "dynamic_routing": {"type": "boolean"},
            },
            "additionalProperties": False,
        },
        "uploaded_docs": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["filename"],
                "properties": {
                    "filename": {"type": "string"},
                    "content": {"type": "string"},
                },
            },
        },
        "expected_terminal": {
            "type": "object",
            "properties": {
                "expected_status": {"type": "string"},
                "expected_stage": {"type": "string"},
                "expected_stage_early": {"type": ["string", "null"]},
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
        "rubric_overrides": {"type": "object"},
    },
    "additionalProperties": False,
}


def validate_case_dict(data: dict[str, Any]) -> list[str]:
    """验证用例 dict 是否符合 schema，返回错误列表（空列表=有效）。"""
    errors: list[str] = []

    # Required fields
    for field in ["case_id", "category", "topic"]:
        if field not in data:
            errors.append(f"Missing required field: {field}")

    if not errors:
        # case_id format
        case_id = data.get("case_id", "")
        if not case_id or not case_id.replace("-", "").isalnum():
            errors.append(f"Invalid case_id format: {case_id}")

        # category
        category = data.get("category", "")
        valid_categories = {"prd_openapi", "design_doc", "research", "business", "edge_adversarial"}
        if category not in valid_categories:
            errors.append(f"Invalid category: {category}")

        # topic: empty is allowed (edge case)
        topic = data.get("topic")
        if topic is None:
            errors.append("Missing required field: topic")
        elif len(topic) > 20000:
            errors.append(f"Topic too long: {len(topic)} chars (max 20000)")

        # tier
        tier = data.get("tier", 1)
        if not isinstance(tier, int) or tier < 1 or tier > 3:
            errors.append(f"Invalid tier: {tier}")

    return errors
