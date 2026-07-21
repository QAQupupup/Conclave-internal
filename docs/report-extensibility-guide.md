# 动静分离架构 — 报告模板与数据分离设计

## 核心理念

**模板（静）与数据（动）分离**：报告的布局结构（章节有哪些、每章用什么组件）是静态模板，由后端 `report_layout.py` 定义；报告的内容数据（具体文字、数值、代码）由 agent 动态产出，存入 `state.artifact`。两者在 `build_report_layout()` 中结合，生成完整的 layout spec 交给前端渲染。

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐
│  Agent 产出   │     │  report_layout    │     │   前端渲染    │
│  (动态数据)   │────▶│  (静态模板 + 绑定) │────▶│  (通用渲染器) │
│  artifact    │     │  build_layout()   │     │  renderFromLayout() │
└─────────────┘     └──────────────────┘     └─────────────┘
```

## 数据流详解

### 1. Agent 产出数据（动态）

Agent 在 produce 阶段根据 `deliverable_type` 调用 LLM，产出结构化数据存入 `state.artifact`：

```python
# produce.py 中 agent 产出后
state.artifact = {
    "prd": {"title": "...", "goal": "...", "api_endpoints": [...]},
    "openapi": "openapi: 3.0.0\n...",
    "attachments": [{"filename": "prd.md", "size": 12345}],
}
```

数据结构由 `app/agents/prompts.py` 中的 `get_produce_template()` 定义，每种类型的 prompt 要求 LLM 输出对应结构的 JSON。

### 2. Layout Spec 生成（静态模板 + 绑定）

`report_layout.py` 中的 `_build_xxx_layout()` 函数定义了每种类型的布局模板：

```python
def _build_prd_openapi_layout(artifact, ctx):
    prd = artifact.get("prd", {})        # 从动态数据中取值
    return {
        "title": prd.get("title", ""),    # 绑定到动态数据
        "sections": [
            {
                "id": "summary",
                "title": "执行摘要",
                "blocks": [
                    # block 类型决定前端如何渲染
                    {"type": "paragraph", "data": {"text": prd.get("goal", "")}},
                    {"type": "list", "data": {"items": ctx["adopted_claims"]}},
                ],
            },
            # ... 更多章节
        ],
    }
```

**关键设计**：layout builder 只做"取哪个字段、放到哪个 block"的映射，不做任何展示逻辑。前端根据 block 的 `type` 选择对应的渲染器。

### 3. 前端通用渲染（纯展示）

```javascript
function renderReportFromLayout(layout) {
    // 遍历 sections → 遍历 blocks → 按 type 分发渲染
    layout.sections.map(sec => 
        sec.blocks.map(block => BLOCK_RENDERERS[block.type](block))
    )
}
```

前端不知道也不关心这是"研究报告"还是"商业分析"，它只按 block type 渲染。

## 新增报告类型的完整步骤

以"金融分析报告（financial_report）"为例：

### 步骤 1：后端 — 添加 Layout Builder

在 `report_layout.py` 中新增：

```python
def _build_financial_report_layout(artifact, ctx):
    fin = artifact.get("financial_report", {})
    meta = ctx["meeting_meta"]
    return {
        "title": fin.get("title", "金融分析报告"),
        "subtitle": meta.get("topic", ""),
        "sections": [
            {
                "id": "company_overview",
                "title": "公司概况",
                "blocks": [
                    {"type": "field", "data": {"label": "公司名称", "value": fin.get("company", "")}},
                    {"type": "field", "data": {"label": "行业", "value": fin.get("industry", "")}},
                    {"type": "paragraph", "data": {"text": fin.get("overview", "")}},
                ],
            },
            {
                "id": "financials",
                "title": "财务报表",
                "blocks": [
                    {"type": "data_model", "data": {"entities": fin.get("financial_tables", [])}},
                ],
            },
            {
                "id": "valuation",
                "title": "估值指标",
                "blocks": [
                    {"type": "kpi_grid", "data": {"items": fin.get("valuation_metrics", [])}},
                ],
            },
            {
                "id": "peers",
                "title": "同业对比",
                "blocks": [
                    {"type": "list", "data": {"items": fin.get("peer_comparison", []), "ordered": False}},
                ],
            },
            {
                "id": "recommendation",
                "title": "投资建议",
                "blocks": [
                    {"type": "paragraph", "data": {"text": fin.get("recommendation", "")}},
                    {"type": "risks", "data": {"items": fin.get("risk_factors", [])}},
                ],
            },
        ],
    }

# 注册到构建器表 — 只需一行
_LAYOUT_BUILDERS["financial_report"] = _build_financial_report_layout
```

### 步骤 2：后端 — 添加 Agent Prompt 模板

在 `prompts.py` 的 `get_produce_template()` 中新增 `financial_report` 的 prompt，要求 LLM 输出：

```json
{
  "financial_report": {
    "title": "公司名称 + 分析报告",
    "company": "公司名称",
    "industry": "所属行业",
    "overview": "公司概况...",
    "financial_tables": [{"entity": "资产负债表", "fields": ["资产", "负债", "权益"]}],
    "valuation_metrics": [{"label": "PE", "value": "25.3", "unit": "倍", "trend": "高于行业均值"}],
    "peer_comparison": ["对比公司A - PE 20.1", "对比公司B - PE 30.5"],
    "recommendation": "建议增持/减持/持有...",
    "risk_factors": [{"level": "high", "desc": "行业政策风险"}, {"level": "mid", "desc": "汇率波动"}]
  }
}
```

### 步骤 3：前端 — 添加类型到 REPORT_TYPES（可选）

```javascript
const REPORT_TYPES=[
    // ... 已有 9 种
    {id:'financial_report',label:'金融分析'},  // 新增一行
];
```

**注意**：如果前端不添加，后端下发的 layout spec 仍然能正常渲染（`applyReportLayout` 不依赖 `REPORT_TYPES`）。添加到 `REPORT_TYPES` 只是为了让用户能在类型切换器中看到并手动选择。

### 步骤 4：验证

```python
# 后端测试
from app.report_layout import build_report_layout
spec = build_report_layout("financial_report", {
    "financial_report": {
        "title": "腾讯控股分析报告",
        "company": "腾讯控股",
        "industry": "互联网科技",
        "overview": "腾讯是中国领先的互联网增值服务提供商...",
        # ... 其他字段
    }
}, {})
assert spec["type"] == "financial_report"
assert len(spec["sections"]) == 5
assert spec["sections"][2]["blocks"][0]["type"] == "kpi_grid"
```

## Agent 自适应生成机制

### 现有 Agent 能否基于已有结构生成新类型？

**能，但需要两个条件**：

1. **Prompt 指定输出结构**：Agent 的 LLM 输出格式由 prompt 中的 `schema_hint` 控制。新增类型时，在 prompt 中定义期望的 JSON 结构，LLM 就会按结构输出。

2. **Layout Builder 做字段映射**：LLM 输出的 JSON 字段名需要与 layout builder 中的 `artifact.get("field_name")` 一致。

### 动静分离的精髓

```
模板（静态）                    数据（动态）
─────────────────              ─────────────────
_layout_financial_report()     agent LLM 输出
  ├ section: 公司概况            ├ company: "腾讯"
  ├ section: 财务报表            ├ financial_tables: [...]
  ├ section: 估值指标            ├ valuation_metrics: [...]
  ├ section: 同业对比            ├ peer_comparison: [...]
  └ section: 投资建议            └ recommendation: "..."

         │                              │
         └──────── build_report_layout ────┘
                         │
                         ▼
                    layout spec JSON
                    { sections: [{ blocks: [{ type, data }] }] }
```

- **改模板不改数据**：调整章节顺序、换 block 类型、增减章节 — 只改 `_build_xxx_layout()`，agent prompt 不动
- **改数据不改模板**：LLM 输出不同公司数据 — 模板不变，渲染结果自动适应
- **加类型不动前端**：后端加 builder + 注册，前端零改动

## 展示区域

| 区域 | 位置 | 说明 |
|------|------|------|
| 报告类型切换器 | `report-type-bar` | 用户可切换查看不同类型（仅限已注册类型） |
| 报告内容区 | `view-report` → `report-content` | 按 layout spec 渲染的完整报告 |
| 演示模式 | `report-presentation` overlay | 全屏 PDF 画板风格，逐页展示 |
| API 入口 | `GET /api/meetings/{id}/report-layout` | 前端 `fetchReportLayout()` 调用 |
| 实时推送 | SSE `produce.progress` 事件 | 生成完成后可推送 spec 到前端 |

## 扩展检查清单

新增报告类型时，逐项确认：

- [ ] `report_layout.py` 新增 `_build_xxx_layout()` 函数
- [ ] `_LAYOUT_BUILDERS` 字典注册新类型
- [ ] `prompts.py` 的 `get_produce_template()` 新增 prompt 模板
- [ ] `produce.py` 的 artifact 存储逻辑覆盖新类型
- [ ] （可选）前端 `REPORT_TYPES` 添加类型标签
- [ ] （可选）`models.py` 的 `deliverable_type` 文档更新
- [ ] 后端测试：`build_report_layout("xxx", mock_artifact)` 返回有效 spec
- [ ] 前端测试：`applyReportLayout(spec)` 正确渲染
