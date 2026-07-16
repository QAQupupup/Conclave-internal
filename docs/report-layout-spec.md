# Report Layout Spec — 报告布局规范

> Conclave 多智能体会议系统 · 报告产出层规范
>
> 本规范定义 Conclave 平台报告产出层的布局协议。系统支持 **9 种产出类型**（deliverable types），通过后端驱动的 Layout Spec 让前端用**一个通用渲染器**渲染所有报告。新增报告类型时，前端无需任何改动。
>
> - 后端实现：`backend/app/report_layout.py`
> - 产出阶段：`backend/app/orchestrator/nodes/produce.py`
> - 前端渲染器：`renderReportFromLayout(layout)`（通用渲染，替代按类型硬编码的模板）
> - 规范版本：v1 · 最后更新 2026-07-16

本规范采用**分档结构**，各档深度不同：第一档给架构直觉，第二档是精确契约，第三档讲渲染语义，第四档是落地清单，第五档是扩展方法论，第六档是视觉收口。开发者按需阅读，新增报告类型时重点看第五档。

---

## 目录

- [第一档：架构总览](#第一档架构总览)
- [第二档：Layout Spec Schema 规范](#第二档layout-spec-schema-规范)
- [第三档：前端渲染规则](#第三档前端渲染规则)
- [第四档：9 种产出类型布局定义](#第四档9-种产出类型布局定义)
- [第五档：扩展指南 — 动静分离架构](#第五档扩展指南--动静分离架构)
- [第六档：风格准则](#第六档风格准则)

---

## 第一档：架构总览

### 1.1 系统架构图

Conclave 报告产出层是一条**单向数据流**：后端把 agent 产出的 artifact（动态数据）套进布局模板（静态结构），生成一份 Layout Spec JSON，前端只负责按 spec 渲染，不做任何业务判断。

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              后端 (Python)                                │
│                                                                           │
│   produce.py                          report_layout.py                    │
│  ┌──────────────┐    artifact +     ┌──────────────────────────┐          │
│  │  produce 阶段 │ ── ctx ────────▶ │ build_report_layout()    │          │
│  │  按 deliver-  │   (artifact,      │                          │          │
│  │  able_type    │    meeting_meta,  │  _LAYOUT_BUILDERS[type]  │          │
│  │  生成 artifact│    confidence,    │   ├─ _build_prd_openapi  │          │
│  │              │    decisions,     │   ├─ _build_research_..  │          │
│  │              │    conflicts,     │   ├─ ... (共 9 个)       │          │
│  │              │    llm_trace ...)  │   └─ _build_generic(回退)│          │
│  └──────────────┘                   └────────────┬─────────────┘          │
│                                                  │                        │
│                                                  ▼                        │
│                                       Layout Spec (JSON)                   │
│                                       { type, title, sections, ... }       │
└──────────────────────────────────────────────────┬──────────────────────────┘
                                                   │  (WebSocket / REST)
                                                   ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              前端 (TS/React)                              │
│                                                                           │
│   view-report  ──▶  report-type-bar（报告类型切换器）                      │
│                          │                                                │
│                          ▼                                                │
│              renderReportFromLayout(layout)                               │
│                  ├─ 遍历 sections[]  →  sec-1, sec-2, ...                  │
│                  │   └─ 遍历 blocks[]  →  BLOCK_RENDERERS[type](block)    │
│                  ├─ 自动生成 TOC（中文序号 一、二、三…）                     │
│                  ├─ 演示模式（封面→目录→章节→附录，←/→ 翻页）               │
│                  └─ 复制 / 折叠 / 打印 PDF / 下载 Markdown / 导出 HTML      │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 核心设计原则

| 原则 | 含义 | 落地 |
| --- | --- | --- |
| **模板与数据分离（动静分离）** | 布局结构（静态）与 agent 产出内容（动态）解耦。模板定义"放什么 block、怎么排"，agent 只管"填什么数据" | `report_layout.py` 持有模板，agent 持有 artifact |
| **后端驱动布局** | 章节顺序、block 类型选择、字段映射全部由后端决定，前端不写 `if (type === 'prd_openapi')` | `_LAYOUT_BUILDERS` 注册表按 type 分发 |
| **前端只负责展示** | 前端是"纯渲染器"，理解 16 种 block type 的展示语义即可，不理解任何业务领域知识 | `renderReportFromLayout` + `BLOCK_RENDERERS` 派发表 |
| **未知类型可回退** | 未注册的类型走 `_build_generic_layout`，遍历 artifact 每个 key 自动成节，保证"有内容就能看" | `_LAYOUT_BUILDERS.get(type) or _build_generic_layout` |
| **附录自动追加** | 只要存在 `llm_trace`，所有类型都自动追加"附录"章节（LLM 调用次数 / 成功率 / Token） | `_append_appendix_section()` |

### 1.3 数据流

一次完整的报告生成数据流如下：

1. **produce 阶段产出 artifact**：`produce.py` 根据 `state.deliverable_type` 选择产出模板，调用 LLM 生成结构化 artifact（如 `{prd, openapi, attachments}`），同时收集 `llm_trace`、`confidence`、`decisions`、`conflicts` 等上下文。
2. **构建 Layout Spec**：调用 `build_report_layout(deliverable_type, artifact, meeting_meta, confidence, decisions, adopted_claims, key_questions, team_config, conflicts, llm_trace)`，函数签名见 `backend/app/report_layout.py`。它从 `_LAYOUT_BUILDERS` 取出对应 builder，把 artifact（动态数据）与模板（静态章节结构）结合，产出一份完整 layout spec dict。
3. **下发 spec**：layout spec 随会议状态通过 WebSocket / REST 下发到前端。
4. **前端渲染**：`renderReportFromLayout(layout)` 遍历 `sections[]` → 遍历每个 section 的 `blocks[]` → 用 `BLOCK_RENDERERS[block.type](block)` 渲染对应 UI。TOC、章节序号、演示模式、复制/折叠均自动生成。

```
后端 artifact ──▶ build_report_layout() ──▶ Layout Spec ──▶ 前端 renderReportFromLayout()
   (动态数据)         (套模板)              (JSON 契约)          (通用渲染)
```

---

## 第二档：Layout Spec Schema 规范

本档是前后端之间的**精确契约**。后端必须按此结构产出，前端必须按此结构消费。

### 2.1 顶层结构

```jsonc
{
  "type": "research_report",          // 产出类型（9 种之一，见第四档）
  "title": "研究报告标题",              // 报告标题（前端可被用户覆盖）
  "subtitle": "副标题 / 会议议题",       // 报告副标题
  "sections": [ /* Section[]，有序 */ ],
  "meta": {                           // 可选：元信息
    "meeting_id": "mtg-xxxx",
    "status": "done",
    "generated_at": "2026-07-16T15:08:00Z"
  },
  "confidence": {                     // 可选：各阶段置信度
    "clarify": "high",
    "discuss": "high",
    "arbitrate": "mid",
    "produce": "high"
  }
}
```

| 顶层字段 | 类型 | 必需 | 说明 |
| --- | --- | --- | --- |
| `type` | `string` | 是 | 9 种产出类型之一；驱动 builder 选择与前端类型切换器展示 |
| `title` | `string` | 是 | 报告主标题 |
| `subtitle` | `string` | 否 | 副标题，通常取会议议题 `meeting_meta.topic` |
| `sections` | `Section[]` | 是 | 有序章节列表；为空时前端展示空态 |
| `meta` | `object` | 否 | 会议元信息（meeting_id / status / generated_at） |
| `confidence` | `object` | 否 | 阶段置信度，键为阶段名，值为 `high`/`mid`/`low` |

### 2.2 Section 结构

```jsonc
{
  "id": "summary",          // 章节唯一标识，用于锚点跳转
  "title": "执行摘要",       // 章节标题（前端会自动加中文序号）
  "icon": "summary",        // 可选：章节图标标识
  "blocks": [ /* Block[]，有序 */ ]
}
```

| 字段 | 类型 | 必需 | 说明 |
| --- | --- | --- | --- |
| `id` | `string` | 是 | 章节唯一标识；前端会额外生成位置锚点 `sec-1`、`sec-2`… 用于 TOC 与演示模式跳转 |
| `title` | `string` | 是 | 章节标题文案 |
| `icon` | `string` | 否 | 章节图标标识（如 `summary`、`code`、`risk`） |
| `blocks` | `Block[]` | 是 | 章节内内容块，按数组顺序渲染 |

### 2.3 Block 结构

```jsonc
{
  "type": "paragraph",      // block 类型，见 2.4 的 16 种
  "data": {                 // 该类型对应的数据结构
    "text": "..."
  }
}
```

每个 block 只有两个字段：`type`（决定如何渲染）与 `data`（承载具体内容）。前端 `BLOCK_RENDERERS[type]` 派发，未知类型回退展示 `[未知块类型: xxx]` 而不崩溃。

### 2.4 16 种 Block Type 完整目录

下表是全部 16 种 block type（与 `SUPPORTED_BLOCK_TYPES` 一一对应）。`data` 列给出字段结构。

| # | type | 用途 | `data` 结构 |
| --- | --- | --- | --- |
| 1 | `paragraph` | 段落文本 | `{ text }` |
| 2 | `list` | 列表（有序/无序） | `{ items: string[], ordered: boolean }` |
| 3 | `findings` | 研究发现卡片组 | `{ items: [{ num, topic, detail, trace, sources: string[] }] }` |
| 4 | `code` | 代码块（带语法高亮、复制、折叠） | `{ code, lang: PYTHON\|YAML\|DOCKER\|JSON\|BASH\|TEXT }` |
| 5 | `api_table` | RESTful API 端点表格 | `{ endpoints: string[] }`，每项格式 `"METHOD /path - description"` |
| 6 | `kpi_grid` | 关键指标卡片网格 | `{ items: [{ label, value, unit, trend }] }` |
| 7 | `conflicts` | 冲突与裁决卡片 | `{ items: [{ summary, sideA, sideB, verdict: a\|b\|compromise, rationale, trace }] }` |
| 8 | `risks` | 风险评估列表 | `{ items: [{ level: high\|mid\|low, desc }] }` |
| 9 | `timeline` | 时间线 | `{ items: [{ date, text }] }` |
| 10 | `data_model` | 数据模型实体 | `{ entities: [{ entity, fields: string[] }] }` |
| 11 | `test_groups` | 测试用例分组 | `{ tests: [{ name, result: pass\|fail, time }] }` |
| 12 | `file_tree` | 文件树 | `{ items: [{ name, type: dir\|file, indent: number }] }` |
| 13 | `field` | 单字段键值对 | `{ label, value }` |
| 14 | `team_config` | 团队配置 | `{ items: [{ role, stance }] }` |
| 15 | `attachments` | 附件列表 | `{ items: [{ filename, size: number }] }` |
| 16 | `raw` | 原始文本（Markdown 等，前端按需处理） | `{ text }` |

### 2.5 各 Block 的 `data` 详细示例

**paragraph**
```jsonc
{ "type": "paragraph", "data": { "text": "本报告基于多智能体讨论得出，旨在…" } }
```

**list**
```jsonc
{ "type": "list", "data": { "items": ["项一", "项二"], "ordered": false } }
```

**findings** — `num` 为序号（如 `01`），`trace` 为可选溯源对象，`sources` 为来源标签数组
```jsonc
{
  "type": "findings",
  "data": {
    "items": [
      {
        "num": "01",
        "topic": "服务拆分粒度",
        "detail": "建议按业务能力拆分，订单域与库存域分离…",
        "trace": { "stage": "discuss", "agent": "architect" },
        "sources": ["内部架构评审", "Q3 容量数据"]
      }
    ]
  }
}
```

**code** — `lang` 决定语法高亮方案
```jsonc
{ "type": "code", "data": { "code": "def hello():\n    print('hi')", "lang": "PYTHON" } }
```

**api_table** — 每项字符串会被解析为 `METHOD /path - description`
```jsonc
{
  "type": "api_table",
  "data": {
    "endpoints": [
      "GET /api/users - 获取用户列表",
      "POST /api/users - 创建用户"
    ]
  }
}
```

**kpi_grid**
```jsonc
{
  "type": "kpi_grid",
  "data": {
    "items": [
      { "label": "日均订单", "value": "1.2M", "unit": "单", "trend": "+8%" }
    ]
  }
}
```

**conflicts** — `verdict` 为 `a`/`b`/`compromise`，分别渲染为"采纳A方 / 采纳B方 / 折中"
```jsonc
{
  "type": "conflicts",
  "data": {
    "items": [
      {
        "summary": "是否引入消息队列",
        "sideA": "架构师：引入 Kafka 解耦",
        "sideB": "工程师：先用同步调用降复杂度",
        "verdict": "compromise",
        "rationale": "一期同步，二期引入 MQ",
        "trace": { "stage": "arbitrate" }
      }
    ]
  }
}
```

**risks** — `level` 决定颜色标签（高/中/低）
```jsonc
{
  "type": "risks",
  "data": { "items": [ { "level": "high", "desc": "迁移期间营销系统不可停机" } ] }
}
```

**timeline**
```jsonc
{ "type": "timeline", "data": { "items": [ { "date": "2026-08", "text": "订单域拆分上线" } ] } }
```

**data_model** — `fields` 支持标记 `[PK]`/`[FK]`，前端高亮主外键
```jsonc
{
  "type": "data_model",
  "data": { "entities": [ { "entity": "User", "fields": ["id [PK]", "name", "order_id [FK]"] } ] }
}
```

**test_groups** — `result` 决定通过/失败标记，`time` 为耗时字符串
```jsonc
{
  "type": "test_groups",
  "data": { "tests": [ { "name": "test_register_user", "result": "pass", "time": "0.12s" } ] }
}
```

**file_tree** — `indent` 控制缩进层级，`type` 区分目录/文件
```jsonc
{
  "type": "file_tree",
  "data": { "items": [ { "name": "src/", "type": "dir", "indent": 0 }, { "name": "app.py", "type": "file", "indent": 1 } ] }
}
```

**field**
```jsonc
{ "type": "field", "data": { "label": "目标", "value": "完成微服务迁移" } }
```

**team_config**
```jsonc
{ "type": "team_config", "data": { "items": [ { "role": "架构师", "stance": "主张渐进式拆分" } ] } }
```

**attachments** — `size` 为字节数，前端折算为 KB
```jsonc
{ "type": "attachments", "data": { "items": [ { "filename": "prd.pdf", "size": 12345 } ] } }
```

**raw** — 无结构的兜底文本
```jsonc
{ "type": "raw", "data": { "text": "任意 Markdown 或原始字符串" } }
```

### 2.6 一份完整 Layout Spec 示例

```jsonc
{
  "type": "research_report",
  "title": "微服务迁移可行性研究报告",
  "subtitle": "将现有单体电商平台迁移至微服务架构",
  "sections": [
    {
      "id": "summary",
      "title": "执行摘要",
      "blocks": [
        { "type": "paragraph", "data": { "text": "本报告评估了单体电商迁移至微服务架构的可行性…" } },
        { "type": "list", "data": { "items": ["迁移可行", "建议分两期"], "ordered": false } }
      ]
    },
    {
      "id": "findings",
      "title": "研究发现",
      "blocks": [
        { "type": "findings", "data": { "items": [
          { "num": "01", "topic": "服务拆分", "detail": "按业务能力拆分", "trace": null, "sources": ["内部评审"] }
        ] } }
      ]
    }
  ],
  "meta": { "meeting_id": "mtg-0837a71f", "status": "done", "generated_at": "2026-07-16T15:08:00Z" },
  "confidence": { "clarify": "high", "discuss": "high", "produce": "high" }
}
```

---

## 第三档：前端渲染规则

本档描述通用渲染器的语义契约。前端代码只有一个渲染入口，**不理解任何业务领域**，只理解 16 种 block 的展示规则。

### 3.1 通用渲染器工作原理

```
renderReportFromLayout(layout)
  ├─ 渲染报告头（title + subtitle + meta + confidence）
  ├─ 渲染操作条（打印/PDF · 演示 · 下载 Markdown · 导出 HTML）
  ├─ reportToc(sections.map(s => s.title))      // 自动生成目录
  └─ sections.map((sec, i) =>                      // 遍历章节
       <section id="sec-{i+1}">
         reportSectionTitle(中文序号 + sec.title)     // 一、执行摘要
         sec.blocks.map(b => renderBlock(b))          // 遍历块
       </section>
     )
```

`renderBlock(block)` 的派发逻辑：

```ts
function renderBlock(block: Block): string {
  const renderer = BLOCK_RENDERERS[block.type]
  if (!renderer) return `<div class="report-p" style="color:var(--text-3)">[未知块类型: ${block.type}]</div>`
  return renderer(block) || ''
}
```

`BLOCK_RENDERERS` 是一张 `type → renderFn(block)` 的派发表，每种 block type 对应一个纯函数，输入 `block.data`，输出 HTML/JSX。新增 block type 只需在此表注册一项。

### 3.2 章节 ID 自动生成

- 每个章节按**出现顺序**生成位置锚点：`sec-1`、`sec-2`、`sec-3`…
- 该锚点用于 TOC 跳转与演示模式定位，独立于 builder 传入的 `section.id`（`section.id` 是语义标识，`sec-N` 是位置标识）。
- TOC 中每项链接到对应 `#sec-N`。

### 3.3 章节标题中文序号

章节标题前自动加中文序号，序号取自章节在 `sections[]` 中的下标：

```js
const CN = ['一','二','三','四','五','六','七','八','九','十']
// 第 0 个章节 → "一 执行摘要"，第 1 个 → "二 研究发现"…
function cnSectionTitle(title, index) {
  return `${CN[index] || index + 1} ${title}`
}
```

超过第 10 章回退为阿拉伯数字（`index + 1`）。

### 3.4 TOC 自动生成

- TOC 从 `sections.map(s => s.title)` 自动生成，无需后端单独维护目录。
- 每条 TOC 项前显示两位序号（`01`、`02`…，等宽字体），点击平滑滚动到 `#sec-N`。
- TOC 作为一个独立区块渲染在报告头之后、首个章节之前；在演示模式中作为独立"目录页"。

### 3.5 演示模式（Presentation Mode）

演示模式把报告转成全屏幻灯片，适合汇报场景。

- **进入**：点击操作条"演示"按钮，触发 `presStart()`，叠加 `.report-presentation.active` 全屏覆盖层（`z-index: 200`，背景 `#fafafa`）。
- **幻灯片序列**：封面页 → 目录页 → 各章节页（每章一页，内部可滚动）→ 附录页。
  - 封面页：`title`（32px）+ `subtitle` + `meta` + `confidence`。
  - 目录页：复用 TOC 渲染，点击某项跳到对应章节页。
  - 章节页：章节标题（26px）+ 该章全部 blocks。
- **翻页交互**：
  - 键盘 `→` / `Space` 下一页，`←` 上一页，`Esc` 退出。
  - 屏幕左右各 20% 宽度为隐形点击区，左点上一页、右点下一页。
  - 底部导航条：上一页 / 计数器（`3 / 12`）/ 下一页 / 退出。
- **顶部进度条**：2px 高，宽度随当前页/总页数比例变化。
- **演示模式适配**：演示模式下隐藏复制按钮、代码折叠按钮、测试分组折叠，代码块自动展开（`max-height: none`），整体留白放大。

### 3.6 复制功能

| 复制对象 | 触发位置 | 复制内容 | 反馈 |
| --- | --- | --- | --- |
| 代码块 | 每个 `code` block 右上角"复制"按钮 | 该 block 的 `data.code` 原文 | 按钮变"已复制"，2 秒后还原 |
| 章节内容 | 每个章节标题旁"复制"按钮 | 该章节纯文本（`innerText`，已 trim） | 按钮变"已复制"，2 秒后还原 |

复制通过 `navigator.clipboard.writeText()` 实现。演示模式与打印模式下隐藏所有复制按钮。

### 3.7 折叠功能

| 折叠对象 | 触发条件 / 位置 | 行为 |
| --- | --- | --- |
| 代码块 | 当 `code` 按 `\n` 分割后**行数 > 12** 时，自动渲染为可折叠容器（默认折叠） | 标题上方显示"展开/折叠"按钮，点击切换 `.collapsed`；折叠时裁剪高度并加渐隐遮罩 |
| 测试分组 | `test_groups` 按 `test_` 前缀自动分组，每组头部可点击 | 点击分组头切换 `.collapsed`，展开/收起该组用例；分组头显示用例数与"全部通过/有失败"状态 |

测试分组规则：取每个 `test.name` 去掉前导 `test_` 后的第一段下划线前缀作为分组名（如 `test_register_user` → 分组 `register`），同组用例聚到一起。

### 3.8 其它操作条能力

- **打印 / PDF**：切换到报告视图后调用 `window.print()`，打印样式隐藏导航/工具栏/复制按钮。
- **下载 Markdown**：将 layout 序列化为 Markdown 文档下载。
- **导出 HTML**：导出可独立打开的自包含 HTML 报告。

---

## 第四档：9 种产出类型布局定义

本档是**落地清单**。每种类型列出其章节结构（`section.id → 章节标题`，按渲染顺序），并给出后端实现函数。所有类型在存在 `llm_trace` 时自动追加"附录"章节。

> 通用附录章节（自动追加）：`appendix → 附录`，含 LLM 调用次数 / 成功率 / 总 Token 三个 `field` block。由 `_append_appendix_section()` 注入，无需在各 builder 内手写。

### 4.1 `prd_openapi` — PRD + OpenAPI

> 后端实现：`_build_prd_openapi_layout()` · artifact 键：`prd` / `openapi` / `attachments`

| 顺序 | section.id | 章节标题 | 主要 block |
| --- | --- | --- | --- |
| 1 | `summary` | 执行摘要 | paragraph（PRD goal）+ list（采纳主张） |
| 2 | `key_questions` | 关键问题 | list（有序，关键问题） |
| 3 | `team_config` | 团队配置 | team_config |
| 4 | `conflicts` | 冲突与裁决 | conflicts（经 `_enrich_conflicts` 合并 decisions） |
| 5 | `prd` | 最终产出 — PRD | field×3 + list×2 + api_table + list |
| 6 | `openapi` | OpenAPI 规范 | code（lang=YAML） |
| 7 | `attachments` | 附件 | attachments |
| 8 | `appendix` | 附录 | field×3（自动） |

### 4.2 `research_report` — 研究报告

> 后端实现：`_build_research_report_layout()` · artifact 键：`research_report`

| 顺序 | section.id | 章节标题 | 主要 block |
| --- | --- | --- | --- |
| 1 | `summary` | 执行摘要 | paragraph + list（采纳主张） |
| 2 | `findings` | 研究发现 | findings（自动编号 `01`…，含 sources） |
| 3 | `analysis` | 分析 | paragraph |
| 4 | `recommendations` | 建议 | list（有序） |
| 5 | `attachments` | 附件 | attachments |
| 6 | `appendix` | 附录 | field×3（自动） |

### 4.3 `business_report` — 商业分析

> 后端实现：`_build_business_report_layout()` · artifact 键：`business_report`

| 顺序 | section.id | 章节标题 | 主要 block |
| --- | --- | --- | --- |
| 1 | `summary` | 执行摘要 | paragraph（executive_summary） |
| 2 | `kpis` | 关键指标 | kpi_grid |
| 3 | `market_analysis` | 市场分析 | paragraph |
| 4 | `risk_assessment` | 风险评估 | risks（由 `_parse_risks_from_text` 解析） |
| 5 | `timeline` | 时间线 | timeline |
| 6 | `next_steps` | 下一步行动 | list（有序） |
| 7 | `appendix` | 附录 | field×3（自动） |

### 4.4 `comprehensive` — 综合文档

> 后端实现：`_build_comprehensive_layout()` · artifact 键：`comprehensive`（含 requirements / system_design / api_design / data_model）

| 顺序 | section.id | 章节标题 | 主要 block |
| --- | --- | --- | --- |
| 1 | `requirements` | 需求 | field + list×3（functional / non_functional / constraints） |
| 2 | `system_design` | 系统设计 | paragraph + list + paragraph |
| 3 | `data_model` | 数据模型 | data_model（`_parse_entities`）+ paragraph + field |
| 4 | `api_design` | API 规范 | api_table + field×2 |
| 5 | `attachments` | 附件 | attachments |
| 6 | `appendix` | 附录 | field×3（自动） |

### 4.5 `design_doc` — 设计文档

> 后端实现：`_build_design_doc_layout()` · artifact 键：`design_doc`

| 顺序 | section.id | 章节标题 | 主要 block |
| --- | --- | --- | --- |
| 1 | `overview` | 系统概述 | paragraph |
| 2 | `architecture` | 架构设计 | paragraph |
| 3 | `tech_stack` | 技术选型 | list |
| 4 | `data_model` | 数据模型 | paragraph |
| 5 | `api_design` | 接口设计 | paragraph |
| 6 | `deployment` | 部署方案 | paragraph |
| 7 | `risks` | 风险 | risks（`_parse_risks_from_list`） |
| 8 | `open_questions` | 遗留问题 | list |
| 9 | `appendix` | 附录 | field×3（自动） |

### 4.6 `code_analysis` — 代码分析

> 后端实现：`_build_code_analysis_layout()` · artifact 键：`prd` / `code_analysis` / `execution`

| 顺序 | section.id | 章节标题 | 主要 block |
| --- | --- | --- | --- |
| 1 | `summary` | 执行摘要 | field（title）+ paragraph（goal） |
| 2 | `analysis_description` | 分析说明 | field + paragraph |
| 3 | `code` | 分析代码 | code（lang=PYTHON） |
| 4 | `expected_output` | 预期输出 | paragraph |
| 5 | `execution` | 执行结果 | code（stdout/stderr）+ field（exit_code）（条件存在） |
| 6 | `appendix` | 附录 | field×3（自动） |

### 4.7 `data_science` — 数据科学

> 后端实现：`_build_data_science_layout()` · artifact 键：`prd` / `code_analysis` / `execution`

| 顺序 | section.id | 章节标题 | 主要 block |
| --- | --- | --- | --- |
| 1 | `summary` | 分析目标 | field + paragraph×2（goal / scope） |
| 2 | `methodology` | 方法论 | paragraph |
| 3 | `code` | 分析代码 | code（lang=PYTHON） |
| 4 | `execution` | 执行结果 | code + field（条件存在） |
| 5 | `appendix` | 附录 | field×3（自动） |

### 4.8 `tested_system` — 测试系统

> 后端实现：`_build_tested_system_layout()` · artifact 键：`prd` / `tested_system` / `execution`

| 顺序 | section.id | 章节标题 | 主要 block |
| --- | --- | --- | --- |
| 1 | `summary` | 系统说明 | field + paragraph |
| 2 | `prd` | PRD | field×2 + api_table |
| 3 | `main_code` | 主代码 | code（lang=PYTHON） |
| 4 | `test_code` | 测试代码 | code（lang=PYTHON） |
| 5 | `run_command` | 运行命令 | code（lang=BASH） |
| 6 | `test_results` | 测试结果 | test_groups（条件存在） |
| 7 | `appendix` | 附录 | field×3（自动） |

### 4.9 `deployable_service` — 可部署服务

> 后端实现：`_build_deployable_service_layout()` · artifact 键：`prd` / `deployable_service` / `review` / `deployment` / `execution`

| 顺序 | section.id | 章节标题 | 主要 block | 备注 |
| --- | --- | --- | --- | --- |
| 1 | `deploy_status` | 部署状态 | field×3（服务地址 / 部署状态 / 部署时间） | `_build_deploy_status_blocks` |
| 2 | `prd` | PRD | field×3 + api_table | |
| 3 | `code_structure` | 代码结构 | file_tree（`_parse_file_tree`） | |
| 4 | `code_review` | 代码审查 | field + list | 条件：`review` 存在 |
| 5 | `test_results` | 测试结果 | test_groups | 条件：`execution` 含 tests |
| 6 | `dockerfile` | Dockerfile | code（lang=DOCKER） | 条件：`ds.dockerfile` |
| 7 | `docker_compose` | docker-compose.yml | code（lang=YAML） | 条件：`ds.docker_compose` |
| 8 | `appendix` | 附录 | field×3（自动） | |

> 4.6–4.9 的"执行结果/测试结果"章节为**条件章节**：仅当 `artifact.execution` 存在时才追加，由 `_build_execution_blocks` / `_build_test_result_blocks` 构造。

### 4.10 类型注册表

9 种类型在后端通过 `_LAYOUT_BUILDERS` 字典注册，未命中走 `_build_generic_layout`（遍历 artifact 每个 key 自动成节，长文本转 `code/TEXT`，dict 转 `raw`）：

```python
_LAYOUT_BUILDERS = {
    "prd_openapi":      _build_prd_openapi_layout,
    "research_report":  _build_research_report_layout,
    "business_report":  _build_business_report_layout,
    "comprehensive":    _build_comprehensive_layout,
    "design_doc":       _build_design_doc_layout,
    "code_analysis":    _build_code_analysis_layout,
    "data_science":     _build_data_science_layout,
    "tested_system":    _build_tested_system_layout,
    "deployable_service": _build_deployable_service_layout,
}
```

---

## 第五档：扩展指南 — 动静分离架构

本档是**方法论**。读完本档，开发者应能独立新增一种报告类型，且**不改动前端任何代码**。

### 5.1 核心理念：模板与数据分离

Conclave 报告层把"怎么排"与"填什么"切成两层：

| 层 | 归属 | 内容 | 变化频率 |
| --- | --- | --- | --- |
| **模板（静态）** | `report_layout.py` | 章节结构、block 类型选择、字段映射规则 | 低（产品定义后稳定） |
| **数据（动态）** | agent 产出的 artifact | 具体文本、代码、指标数值 | 高（每次会议不同） |

`build_report_layout()` 是两者结合点：它把动态 artifact 套进静态模板，输出一份 layout spec。前端只认 spec，因此**模板演进不需要前端发版**。

### 5.2 新增报告类型的步骤

以新增"金融分析报告"`financial_report` 为例。

**步骤 1 — 后端：在 `report_layout.py` 新增 builder 函数**

```python
def _build_financial_report_layout(artifact: dict, ctx: dict) -> dict:
    f = artifact.get("financial_report", {})
    meta = ctx["meeting_meta"]
    sections = [
        {
            "id": "overview",
            "title": "公司概况",
            "blocks": [
                {"type": "field", "data": {"label": "公司名称", "value": f.get("company", "")}},
                {"type": "paragraph", "data": {"text": f.get("overview", "")}},
            ],
        },
        {
            "id": "financials",
            "title": "财务报表",
            "blocks": [
                {"type": "kpi_grid", "data": {"items": f.get("financials", [])}},
            ],
        },
        {
            "id": "valuation",
            "title": "估值指标",
            "blocks": [
                {"type": "data_model", "data": {"entities": f.get("valuation", [])}},
            ],
        },
        {
            "id": "peers",
            "title": "同业对比",
            "blocks": [
                {"type": "paragraph", "data": {"text": f.get("peers", "")}},
            ],
        },
        {
            "id": "recommendation",
            "title": "投资建议",
            "blocks": [
                {"type": "list", "data": {"items": f.get("recommendation", []), "ordered": True}},
            ],
        },
    ]
    _append_appendix_section(sections, ctx)
    return {"title": f.get("company", "金融分析报告"), "subtitle": meta.get("topic", ""), "sections": sections}
```

**步骤 2 — 后端：注册到 `_LAYOUT_BUILDERS`**

```python
_LAYOUT_BUILDERS["financial_report"] = _build_financial_report_layout
```

**步骤 3 — 前端：无需任何改动**

通用渲染器已支持全部 16 种 block type，`renderReportFromLayout(layout)` 自动消费新类型的 sections/blocks。前端报告类型切换器（`report-type-bar`）只需在类型列表里加一个选项即可让用户切换到该类型。

完成。新增类型只需写一个 builder + 注册一行，前端零改动。

### 5.3 Agent 驱动的模板生成

Conclave 的报告生成是"agent 产出数据 + 后端提供模板"的协作：

```
现有 agent 产出 artifact（动态部分）
        +
report_layout.py 提供布局模板（静态部分：章节结构 + block 类型选择）
        ‖
        ▼
build_report_layout() 结合两者 → 完整 layout spec
```

- **agent 的职责**：按 `deliverable_type` 产出结构化 artifact 数据（如 `{financial_report: {company, financials, valuation, peers, recommendation}}`）。agent 不关心这些数据最终怎么排版。
- **模板的职责**：决定 artifact 的每个字段映射到哪个章节、用哪种 block 展示。例如"概况 → field + paragraph"、"财务报表 → kpi_grid"、"估值 → data_model"。

### 5.4 新增类型的 block 映射示例

以"金融分析报告"为例，展示从 artifact 字段到 block 的映射：

| artifact 字段 | 章节 | 选用 block | 理由 |
| --- | --- | --- | --- |
| `company` | 公司概况 | `field` | 单值键值，突出公司名 |
| `overview` | 公司概况 | `paragraph` | 长文本描述 |
| `financials[]` | 财务报表 | `kpi_grid` | 多指标卡片网格，含 trend |
| `valuation[]` | 估值指标 | `data_model` | 结构化指标实体 |
| `peers` | 同业对比 | `paragraph` | 对比叙述 |
| `recommendation[]` | 投资建议 | `list`（有序） | 顺序建议项 |

### 5.5 前端展示区域

- **会议报告视图**：前端 `view-report` 视图承载报告渲染，`renderReportFromLayout(layout)` 的输出挂载于此。
- **报告类型切换器**：`report-type-bar` 让用户在会议产出的多个报告类型间切换（一个会议可能产出多种类型，如同时有 PRD 与研究摘要）。切换器读取可用类型列表，调用渲染器重绘。
- 展示层不绑定具体类型知识，切换类型即重新调用 `renderReportFromLayout(newLayout)`。

### 5.6 扩展检查清单

新增报告类型前，确认以下事项：

- [ ] builder 函数返回 `{title, subtitle, sections}` 三件套
- [ ] 每个 section 含 `id` / `title` / `blocks`
- [ ] 每个block 的 `type` 属于 16 种之一，`data` 符合该 type 契约
- [ ] 长文本用 `paragraph`/`raw`，结构化指标用 `kpi_grid`/`data_model`，代码用 `code` 并给对 `lang`
- [ ] 调用 `_append_appendix_section(sections, ctx)` 追加附录
- [ ] 在 `_LAYOUT_BUILDERS` 注册一行
- [ ] 如有特殊解析（风险文本、实体、文件树），复用现有 `_parse_*` 辅助函数或新增
- [ ] 前端无需改动；如需在类型切换器露出，在类型列表加一项即可

---

## 第六档：风格准则

本档是**视觉收口**，保证 9 种报告类型渲染风格统一。报告渲染器使用一组独立的文字 token（`--text` / `--text-2` / `--text-3`），与全局设计 token 对齐（全局 `tokens.css` 中 `--text` / `--text-secondary` / `--text-muted` 分别对应此处的三个层级）。

### 6.1 配色（文字层级）

| 语义 | token | 用途 |
| --- | --- | --- |
| 主文字 | `var(--text)` | 报告标题、章节标题、正文重点、字段值 |
| 次级文字 | `var(--text-2)` | 正文正文、副标题、列表项、卡片描述 |
| 辅助文字 | `var(--text-3)` | 元信息、序号、标签、来源、辅助说明 |

状态色沿用全局语义色：成功 `--ok-fg`、警告 `--warn-fg`、错误 `--err-fg`；强调色 `--accent`。背景以纯白 `--bg` 为主，演示模式用浅灰 `#fafafa`。

### 6.2 字号层级

| 层级 | 字号 | 用途 |
| --- | --- | --- |
| 报告标题 | 24px | 报告头主标题（演示模式 32px） |
| 章节标题 | 18px | `report-section-title`（演示模式 26px） |
| 正文 | 14px | 段落、列表、卡片详情（演示模式 15px） |
| 辅助 | 12px | 元信息、序号、来源、lang 标签 |

### 6.3 间距

| 场景 | 间距 |
| --- | --- |
| 章节之间 | 32px |
| 块之间 | 16px |
| 段落内 / 列表项内 | 8px |

间距系统遵循全局 4/8/12/16/20/24/32/40/48/64 的 4px 基线。

### 6.4 代码块

- 深色背景（`--bg-code`），等宽字体 `var(--font-mono)`（JetBrains Mono / SF Mono）。
- 行高 1.6（演示模式 1.8）。
- 右上角语言标签（`lang`）+ 复制按钮。
- 行数 > 12 自动折叠（默认收起，渐隐遮罩，"展开/折叠"按钮）。
- `DOCKER` / `YAML` 有专属语法高亮，其余按纯文本转义。

### 6.5 卡片

- 白底（`--bg-elev`），1px 边框（`--border`），圆角 6px（`--radius`）。
- 阴影极轻或无（`--shadow-xs`），禁重阴影。
- 卡片内 padding 通常 16–20px；卡片间距 12–16px。
- 适用于 findings、conflicts、kpi、data_model entity、api_table 行、test_groups 等。

### 6.6 演示模式

| 项 | 值 |
| --- | --- |
| 背景 | `#fafafa`（浅灰） |
| 标题 | 32px（封面）/ 26px（章节标题） |
| 正文 | 15px，行高 1.75 |
| 留白 | 更大（canvas padding 48px 80px，slide max-width 760px） |
| 隐藏元素 | 复制按钮、代码折叠按钮、测试分组折叠、操作条 |
| 代码块 | 自动展开，行高 1.8 |
| 进度条 | 顶部 2px，宽度按当前页比例 |

### 6.7 一致性原则

- 所有 block 渲染为纯函数，输出仅依赖 `block.data`，不读取全局状态。
- 颜色、字号、间距一律走 CSS 变量，不硬编码；新增 block type 时复用既有 token。
- 中文序号、TOC、复制/折叠等装饰能力由渲染器统一提供，builder 不关心。
- 暗色主题通过覆盖同名词元实现（`[data-theme="dark"]`），结构不变，报告渲染器自动适配。

---

*本规范为 Conclave 报告产出层的权威契约。后端 `report_layout.py` 已实现第一至第四档；前端通用渲染器 `renderReportFromLayout()` 为目标实现，将逐步替代按类型硬编码的报告组件。新增报告类型请严格遵循第五档步骤。*
