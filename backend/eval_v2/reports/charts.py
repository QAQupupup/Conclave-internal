"""ECharts configuration generators for HTML report visualizations."""

from __future__ import annotations

import json
from typing import Any

BRAND_COLOR = "#335c8e"
ACCENT_COLORS = ["#335c8e", "#5b8db8", "#e07a5f", "#81b29a", "#f2cc8f", "#9d8189", "#6c757d", "#adb5bd"]


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, default=str)


def overview_cards(result: Any) -> str:
    """Generate overview metric cards HTML."""
    ci = result.pass_at_1_ci
    cards = [
        ("Pass@1", f"{result.pass_at_1:.1%}", f"95% CI: [{ci[0]:.1%}, {ci[1]:.1%}]"),
        ("Pass@3", f"{result.pass_at_3:.1%}", f"Stable: {result.pass_at_3_stable:.1%}"),
        ("Avg Score", f"{result.avg_aggregate_score:.1f}", "/100"),
        ("Total Cost", f"${result.total_cost_usd:.3f}", f"${result.cost_per_pass:.3f}/pass"),
        ("Cases", str(result.n_cases), f"{result.n_runs_per_case} runs each"),
        (
            "Duration",
            f"{result.duration_seconds:.0f}s",
            f"p50={result.latency_p50_ms / 1000:.1f}s, p95={result.latency_p95_ms / 1000:.1f}s",
        ),
    ]
    html = '<div class="cards-grid">'
    for title, value, subtitle in cards:
        html += f"""
        <div class="card">
            <div class="card-title">{title}</div>
            <div class="card-value">{value}</div>
            <div class="card-subtitle">{subtitle}</div>
        </div>"""
    html += "</div>"
    return html


def layer_pass_chart(result: Any) -> tuple[str, str]:
    """Layer pass rates bar chart."""
    layers = []
    rates = []
    labels = {
        "l0_health": "L0 Health",
        "l1_process": "L1 Process",
        "l2_internal": "L2 Internal",
        "l3_semantic": "L3 Semantic",
        "l4_comparative": "L4 Comparative",
    }
    for k, v in result.layer_pass_rates.items():
        if k in labels:
            layers.append(labels.get(k, k))
            rates.append(round(v * 100, 1))

    chart_id = "chart-layer-pass"
    option = {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": layers, "axisLabel": {"rotate": 15}},
        "yAxis": {"type": "value", "max": 100, "axisLabel": {"formatter": "{value}%"}},
        "series": [
            {
                "type": "bar",
                "data": [{"value": r, "itemStyle": {"color": BRAND_COLOR if r >= 60 else "#e07a5f"}} for r in rates],
                "label": {"show": True, "position": "top", "formatter": "{c}%"},
            }
        ],
        "grid": {"left": 50, "right": 20, "bottom": 50, "top": 30},
    }
    return chart_id, _json(option)


def dimension_radar(result: Any) -> tuple[str, str]:
    """Dimension score radar chart."""
    dims = list(result.dimension_scores.keys())
    scores = [round(result.dimension_scores.get(d, 0) * 100, 1) for d in dims]

    chart_id = "chart-dim-radar"
    if not dims:
        option = {"title": {"text": "No dimension data", "left": "center"}}
    else:
        option = {
            "tooltip": {},
            "radar": {
                "indicator": [{"name": d, "max": 100} for d in dims],
                "shape": "polygon",
                "splitNumber": 4,
            },
            "series": [
                {
                    "type": "radar",
                    "data": [
                        {
                            "value": scores,
                            "name": "Score",
                            "areaStyle": {"color": "rgba(51,92,142,0.2)"},
                            "lineStyle": {"color": BRAND_COLOR},
                            "itemStyle": {"color": BRAND_COLOR},
                        }
                    ],
                }
            ],
        }
    return chart_id, _json(option)


def failure_pie(result: Any) -> tuple[str, str]:
    """Failure mode pie chart."""
    data = []
    label_map = {
        "infrastructure": "Infrastructure",
        "model": "Model/System",
        "test_bug": "Test Bug",
        "none": "Passed",
    }
    for k, v in result.failure_mode_breakdown.items():
        if v > 0:
            data.append({"name": label_map.get(k, k), "value": v})

    chart_id = "chart-failure-pie"
    color_map = {"Passed": "#81b29a", "Infrastructure": "#e07a5f", "Model/System": "#f2cc8f", "Test Bug": "#9d8189"}
    option = {
        "tooltip": {"trigger": "item", "formatter": "{b}: {c} ({d}%)"},
        "series": [
            {
                "type": "pie",
                "radius": ["40%", "70%"],
                "data": [
                    {
                        "value": d["value"],
                        "name": d["name"],
                        "itemStyle": {"color": color_map.get(d["name"], "#6c757d")},
                    }
                    for d in data
                ],
                "label": {"formatter": "{b}: {c}"},
            }
        ],
    }
    return chart_id, _json(option)


def cost_pareto(result: Any) -> tuple[str, str]:
    """Cost vs Quality Pareto scatter plot."""
    points = []
    for r in result.per_case_results:
        if r.run_index == 0:
            points.append([round(r.cost.total_cost_usd, 4), round(r.aggregate_score, 1), r.case_id, r.passed])

    chart_id = "chart-pareto"
    option = {
        "tooltip": {
            "trigger": "item",
            "formatter": "function(p) { return p.data[2] + '<br/>Cost: $' + p.data[0] + '<br/>Score: ' + p.data[1]; }",
        },
        "xAxis": {"name": "Cost (USD)", "type": "value"},
        "yAxis": {"name": "Score", "type": "value", "min": 0, "max": 100},
        "series": [
            {
                "type": "scatter",
                "symbolSize": 12,
                "data": points,
                "itemStyle": {
                    "color": "function(params) { return params.data[3] ? '#81b29a' : '#e07a5f'; }",
                },
            }
        ],
        "grid": {"left": 60, "right": 20, "bottom": 50, "top": 30},
    }
    return chart_id, _json(option)


def ablation_bar(result: Any) -> tuple[str, str]:
    """Ablation comparison bar chart."""
    chart_id = "chart-ablation"
    if not result.ablation:
        option = {"title": {"text": "No ablation data", "left": "center"}}
    else:
        ab = result.ablation
        option = {
            "tooltip": {"trigger": "axis"},
            "xAxis": {"type": "category", "data": ["Multi-Agent", "Direct LLM"]},
            "yAxis": {"type": "value", "max": 100, "name": "Score"},
            "series": [
                {
                    "type": "bar",
                    "data": [round(ab.multi_agent_score * 100, 1), round(ab.direct_llm_score * 100, 1)],
                    "itemStyle": {"color": BRAND_COLOR},
                    "label": {"show": True, "position": "top"},
                },
            ],
            "grid": {"left": 50, "right": 20, "bottom": 30, "top": 30},
        }
    return chart_id, _json(option)


def dimension_bar(result: Any) -> tuple[str, str]:
    """Dimension score bar chart (grouped by type)."""
    dims = list(result.dimension_scores.keys())
    scores = [round(result.dimension_scores.get(d, 0) * 100, 1) for d in dims]

    chart_id = "chart-dim-bar"
    option = {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": dims, "axisLabel": {"rotate": 30, "fontSize": 10}},
        "yAxis": {"type": "value", "max": 100, "name": "Score"},
        "series": [
            {
                "type": "bar",
                "data": [{"value": s, "itemStyle": {"color": BRAND_COLOR if s >= 60 else "#e07a5f"}} for s in scores],
                "label": {"show": True, "position": "top", "fontSize": 9},
            }
        ],
        "grid": {"left": 50, "right": 20, "bottom": 80, "top": 30},
    }
    return chart_id, _json(option)


def cost_stacked(result: Any) -> tuple[str, str]:
    """Cost breakdown stacked bar."""
    chart_id = "chart-cost-stacked"
    per_case_sut = []
    per_case_judge = []
    case_ids = []
    for r in result.per_case_results:
        if r.run_index == 0:
            case_ids.append(r.case_id[:20])
            per_case_sut.append(round(r.cost.sut_cost_usd, 4))
            per_case_judge.append(round(r.cost.judge_cost_usd, 4))

    option = {
        "tooltip": {"trigger": "axis"},
        "xAxis": {"type": "category", "data": case_ids, "axisLabel": {"rotate": 45, "fontSize": 8}},
        "yAxis": {"type": "value", "name": "Cost (USD)"},
        "series": [
            {"name": "SUT", "type": "bar", "stack": "cost", "data": per_case_sut, "itemStyle": {"color": BRAND_COLOR}},
            {
                "name": "Judge",
                "type": "bar",
                "stack": "cost",
                "data": per_case_judge,
                "itemStyle": {"color": "#5b8db8"},
            },
        ],
        "legend": {"top": 0},
        "grid": {"left": 60, "right": 20, "bottom": 100, "top": 40},
    }
    return chart_id, _json(option)
