# Conclave 代码优化待办（设计模式方向）

> 本文记录基于设计模式审查发现的优化项，作为未来迭代的方向和可选待办。
> 已完成的优化见文末"已完成"小节；未完成的按优先级分组，每项标注涉及的设计模式与风险评估。
> 审查依据：[`design-principles.md`](./design-principles.md)（设计原则）、[`architecture-review.md`](./architecture-review.md)（架构评审）。
>
> 最后更新：2026-06-28

> **历史注记** (2026-07-14): 本清单编写时 `nodes.py` 为单文件，现已拆分为 `nodes/` 包。行号引用已失效，请按函数名在对应节点文件中定位：P1-13 → `nodes/evidence_check.py` 和 `nodes/cross_team.py`；P1-14 → `nodes/produce.py`；P2-15 → `nodes/_helpers.py`；P2-16 → `nodes/intra_team.py`。

---

## 1. 优先级说明

- **P0 高**：收益显著、风险可控，建议下一迭代优先处理
- **P1 中**：有明显架构价值，但改动面较大或触及核心链路
- **P2 低**：锦上添花，可在相关功能迭代时顺手做

---

## 2. 前端待办

### P0-1 抽 `useSvgPanZoom` hook（DRY + 组合）
- **位置**：`frontend/src/components/AgentGraph.tsx`、`frontend/src/components/LogicGraph.tsx`
- **问题**：两图各自维护 `scale / translate / dragging / dragStart`、wheel 缩放监听、mousedown/move/up 拖拽、FocusMode 包裹 + `+/−/重置/聚焦查看` 工具栏 + 图例 + hint，约 150 行逻辑重复。
- **建议**：抽 `useSvgPanZoom(ref, {min, max})` hook + `<GraphToolbar/>` 组件。
- **风险**：中。两图节点数据结构略有差异（Agent vs Claim），需保证 hook 只管交互不管渲染。

### P0-2 抽 `useAutoScroll` hook（DRY）
- **位置**：`frontend/src/components/ChatPanel.tsx`（智能跟随 + 新消息提示）、`frontend/src/components/WorkspacePanel.tsx`（终端自动滚底）
- **问题**：两处 auto-scroll 逻辑各自实现，阈值与行为类似。
- **建议**：抽 `useAutoScroll(ref, deps, {threshold=50})`。
- **风险**：低。

### P1-3 Panel 容器抽象（组合优于继承）
- **位置**：`TopicPanel / EvidencePanel / ArtifactPanel / ChatPanel` 均为 `<section className="panel x-panel"><div className="panel-title">…`
- **问题**：8 处 panel 容器结构重复，空态/标题右侧插槽各自实现。
- **建议**：抽 `<Panel title action>{children}</Panel>`。
- **风险**：低，纯展示组件重构。

### P1-4 颜色常量绕过 CSS 变量（依赖倒置）
- **位置**：`AgentGraph.tsx` 的 `ROLE_COLORS/TYPE_COLORS`、`LogicGraph.tsx` 的 `COLOR_*`
- **问题**：`index.css` 已定义 `--role-*`，组件却硬编码同色 hex，主题改一处改不完。
- **建议**：组件用 `var(--role-moderator)` 或经 `getComputedStyle` 取值。
- **风险**：低。

### P2-5 CSS 按域拆分
- **位置**：`frontend/src/index.css`（2666 行单文件）
- **问题**：`.panel-title` 主规则在 L564，但 L882/L924 有 per-panel 覆盖；变量层已集中（L5-52）。
- **建议**：按域拆分 partial（graph / chat / panel / workspace），变量层保持。
- **风险**：低，但需调整 Vite 构建配置。

---

## 3. 后端 agents 待办

### P0-6 角色画像描述统一到 ROLE_LIBRARY（Registry 单一数据源）
- **位置**：`backend/app/agents/prompts.py` L19-44（ARCHITECT_INTRA/ENGINEER_INTRA 内的"视角+决策偏置"文本）与 `role_templates.py` L38-61（perspective/prompt_template）
- **问题**：同一角色的画像描述在 prompts.py 和 role_templates.py 各写一份，role_templates 的 ROLE_LIBRARY 仅服务于借调，主流程不用。
- **建议**：以 `role_templates.ROLE_LIBRARY` 为唯一注册表，prompts.py 只保留阶段骨架，角色偏置从注册表注入。
- **风险**：中。需保证 prompt 文本输出完全不变（已有回归测试可保护）。

### P1-7 LLM 重试/超时/降级策略对象化（Strategy / Policy Object）
- **位置**：`backend/app/agents/llm.py` L328（MAX_ATTEMPTS=3）、L355-423（重试循环内联）、L334（timeout=120）、L479（produce 600s 硬编码）、L422（降级 StubLLM 硬编码）
- **问题**：重试次数、退避、超时、降级目标全部写死在 `complete()` 里，无法按阶段/模型调整；`STAGE_TEMPERATURES`（L301）是策略表但无策略对象。
- **建议**：抽 `RetryPolicy`、`TimeoutPolicy`、`FallbackPolicy` 三对象注入 `RealLLM`；温度表封装为 `TemperatureStrategy`。
- **风险**：高。触及 LLM 调用核心，需完整回归测试覆盖。

### P1-8 trace.py 与 log_bus.py 职责重叠（Observer / 单一事件总线）
- **位置**：`trace.py` L115-160（record_call 注入 request_id/meeting_id）与 `log_bus.py` L38-66（emit 注入相同上下文）
- **问题**：两者都做"结构化事件 + 上下文注入 + 旁路分发"，trace 专做 LLM 调用记录，log_bus 做通用日志，但 `llm.py` L372-408 同时调用两者，重复记录。`trace.py` L169 `setattr(last, key, value)` 直接改 Pydantic 字段绕过校验。
- **建议**：trace 作为 log_bus 的一个 sink（LLMCallSink），消除双写；移除 `update_last_record` 的 setattr，改不可变重建。
- **风险**：中。影响 trace 端点输出，需同步调整前端 TokenPanel。

### P1-9 schemas.py 未覆盖全部 produce 模板（Schema Registry）
- **位置**：`backend/app/agents/schemas.py` L119-134 与 `prompts.py` L204-213（7 种 PRODUCE_TEMPLATES）
- **问题**：`SCHEMA_MAP["produce"]` 仅映射 `ProduceResult`(PRD+OpenAPI)，而 prompts 有 design_doc/comprehensive/research_report/business_report/code_analysis/tested_system 6 种，RealLLM 解析这些时走兜底的"仅 JSON 解析"，校验失效。
- **建议**：每种 produce 模板对应一个 Pydantic 模型，`SCHEMA_MAP` 改为 `(stage, subtype)` 二级键。
- **风险**：中。

### P2-10 compute.proto 字段冗余（契约最小化）
- **位置**：`backend/proto/compute.proto` L13-15
- **问题**：`temperature`/`seed` 在请求里，但实际策略在 `llm.py` STAGE_TEMPERATURES，Worker 侧无法知道该不该覆盖；`trace_context_json` 与 `meeting_id`/`runner_session_id` 信息重叠。
- **建议**：proto 只传 `stage`+`schema_hint`，温度由 Worker 侧策略决定；删除 `trace_context_json`。
- **风险**：低，但涉及 gRPC 契约变更，需前后端同步。

### P2-11 compute.py 与 proto 双重定义（Adapter / Anti-Corruption Layer）
- **位置**：`compute.py` L22-44（dataclass ThinkRequest/ThinkResponse）与 `compute.proto` L5-26
- **问题**：同一数据结构两处定义，proto 改了 dataclass 不会同步。
- **建议**：生成 `compute_pb2` 后用适配层转换，dataclass 仅作进程内 DTO。
- **风险**：低。

---

## 4. 后端 orchestrator 待办

### P0-12 借调三问抽 BorrowAdjudicator（Chain of Responsibility / Strategy）
- **位置**：`backend/app/orchestrator/state.py` `_handle_loan`（已在命令模式重构中拆出，但仍是过程式 if/elif）
- **问题**：三问裁决是过程式 if/elif（防重复→数量上限→approve_temporary），verdict 枚举散落在字符串里，无 `BorrowAdjudicator` 类，`approve_frozen_scope` 分支未实现。
- **建议**：抽 `BorrowAdjudicator`，每条规则一个 `Rule` 对象，组成责任链。
- **风险**：中。借调流程已有测试覆盖。

### P1-13 `_prefetch_evidence` 与 `evidence_check_node._retrieve_evidence` 重复（DRY / 策略模式）
- **位置**：`backend/app/orchestrator/nodes.py` L478-519 与 L547-580
- **问题**：RAG + web + common_knowledge 降级逻辑写两遍，cross_team 预检索与 evidence_check 复用同一套检索流程。
- **建议**：抽取 `EvidenceCollector` 统一方法，两处复用。
- **风险**：中。涉及证据检索主链路。

### P1-14 produce_node 改策略分派（策略模式 / 工厂）
- **位置**：`backend/app/orchestrator/nodes.py` L699-753
- **问题**：`produce_node` 用 `if/elif/else` 按 `deliverable_type` 串接沙箱执行逻辑，`code_analysis` 与 `tested_system` 的写文件+run 重复。
- **建议**：改为 `ProduceStrategy` 字典分派，每类型一个策略类。
- **风险**：中。produce 阶段已有 7 种模板和沙箱执行，改动面较大。

### P2-15 `_match_role` 关键词表硬编码（DRY）
- **位置**：`backend/app/orchestrator/nodes.py` L45-56
- **问题**：`_match_role` 关键词表硬编码于编排层，与 charter/conclusion_chain 各自重复关键词逻辑。
- **建议**：上移到 `agents/role_templates` 统一 `RoleMatcher`。
- **风险**：低。

### P2-16 charter 与 conclusion_chain 的 2-gram 关键词提取重复（DRY）
- **位置**：`backend/app/orchestrator/charter.py` L107-127 与 `conclusion_chain.py` L181-203
- **问题**：`_scope_keywords` 与 `_extract_keywords` 的 2-gram 提取+填充字过滤逻辑重复。
- **建议**：抽 `TextTokenizer` 共用。
- **风险**：低。

### P2-17 produce_node 末尾同步调 trigger_extraction（观察者模式）
- **位置**：`backend/app/orchestrator/nodes.py` L785-786
- **问题**：`produce_node` 末尾同步调 `trigger_extraction`，且函数内多次局部 `import`。
- **建议**：改发布 `meeting.finished` 事件，由 memory 异步订阅。
- **风险**：中。涉及事件时序，需保证画像提取不丢。

---

## 5. 后端 RAG / 可观测 / 路由待办

### P1-18 RAG 接口预留（接口隔离 / 开闭原则）
- **位置**：`backend/app/rag/chunker.py` 全文、`rag/store.py`
- **问题**：仅 markdown 标题切块+embedding，`Chunk` 无 `metadata/relations/claims`，`Store` 无 graph/术语表端口，未为 design-principles §四"图关系/多维提炼/术语归一"预留接口（仅做到 char_offset 保真）。
- **建议**：补薄扩展接口（Chunk 加 metadata/relations 字段、Store 加 graph/term 端口），实现可后置。
- **风险**：低，只加接口不改实现。

### P1-19 领域事件层引入 BroadcastRunner + 多 EventSink（中介者 / 观察者）
- **位置**：`backend/app/events.py` L34-51、`routers/ws.py` L68
- **问题**：`InMemoryEventBus.publish` 无去重/节流/trace 注入，`routers/ws.py` 直订阅 bus，领域事件层未走多 sink（`log_bus` 已实现 LogSink Protocol + Console/JSONFile/RemoteGRPC 多 sink，但仅覆盖日志，非领域事件）。
- **建议**：引入 `BroadcastRunner` + 多 `EventSink`，让 ws/log/trace 都作为 sink。
- **风险**：中。事件总线是实时推送核心。

### P1-20 memory 持久化预留 Repository 端口（Repository 模式）
- **位置**：`backend/app/memory/store.py` L331
- **问题**：`memory_store` 进程内单例无持久化，重启丢画像（与 design-principles §四"SQLite 留底"目标不符）。
- **建议**：预留 `ProfileRepository` 端口，实现可后置。
- **风险**：低，只加接口。

### P2-21 routers 重复的 load_state_or_404 模式（装饰器 / 模板方法）
- **位置**：`backend/app/routers/meetings.py` L111/297/323/372/403
- **问题**：5 个端点重复 `get_state → load_or_create → topic=="" → 404` 恢复模式。
- **建议**：抽 `load_state_or_404` 依赖辅助或 FastAPI `Depends`。
- **风险**：低。

---

## 6. 已完成的优化（2026-06-28）

本次设计模式审查已完成以下 4 个分组 commit，作为后续优化的基线：

| Commit | 分组 | 设计模式 | 改动概述 |
|---|---|---|---|
| `7644d71` | 前端 hooks/utils 抽象 | DRY + 单一职责 + 适配器 | 新建 `lib/format.ts` `lib/clipboard.ts` `lib/download.ts` + `hooks/useCopy.ts` `hooks/usePersistentState.ts`；MessageCard/ArtifactPanel/ReportViewer/App 改用；删除死码 Header.tsx |
| `ca969f0` | 前端常量统一 | Registry 单一数据源 | 新建 `constants.ts`（STAGE_NAMES / STORAGE_KEYS / getMeetingStatusInfo / EVIDENCE_SOURCE_LABEL）；消除 ReportViewer/MeetingSidebar/AgentGraph/EvidencePanel 4 处重复定义 |
| `01b3e53` | 后端 agents 角色分派 | Facade + Registry + 策略模式 | 删除 roles.py 的 6 个死方法；compute.py 新增 `_INTRA_TEAM_TEMPLATES` 注册表 + `_get_intra_template`，消除 2 处 if/elif 硬编码 |
| `f87da58` | 后端 orchestrator 信号分派 | 命令模式 + Registry | state.py 拆分 5 个 if/elif 为独立 `_handle_*` 函数 + `_SIGNAL_HANDLERS` 注册表；apply_signal 从 106 行降到 16 行 |

---

## 6.1 设计缺陷记录（2026-06-29 端到端验证发现）

> 以下缺陷在端到端真实 LLM 验证中发现并已修复。记录根因和教训，避免后续重犯。

### 缺陷 1：ProduceResult schema 丢弃 code_analysis 字段（已修复，commit `84a66ce`）

**现象**：deliverable_type=code_analysis 时，LLM 生成了代码，但 artifact 中 code_analysis 是空字典。

**根因**：`ProduceResult` 只有 `prd` 和 `openapi` 字段。LLM 返回的 `code_analysis` 被 Pydantic 校验丢弃。**设计时只考虑了 PRD 场景，没考虑多产出类型的 schema 扩展。**

**教训**：新增产出类型时，必须同步更新 schema 定义，不能只改 prompt 模板。schema 是契约，prompt 是指导，两者必须对齐。

### 缺陷 2：沙箱 stdin 管道在 Windows Docker 下阻塞（已修复，commit `8975ca2`）

**现象**：produce 阶段 LLM 成功后，RefineLoop 调 `run_python` 时无限卡住，无日志无超时。

**根因**：`docker run python -` + `proc.communicate(input=data)` 的 stdin 管道在 Windows Docker Desktop 下不兼容。Python 进程在容器内等待 stdin EOF，但宿主机的字节流没被正确传递。**当时选 stdin 方式是为了"避免写临时文件"，但忽略了一个更根本的约束：跨 Docker 容器的 stdin 管道在 Windows 上不可靠。**

**教训**：
1. 跨容器数据传递优先用文件系统（volume 挂载），不用 stdin 管道。文件系统是 Docker 的可靠抽象，stdin 管道不是。
2. 设计选择要考虑部署环境。Conclave 运行在 Windows Docker Desktop 上，不是 Linux 原生。跨容器 stdin 兼容性在 Windows 上是已知问题。
3. "避免临时文件"不是好的设计理由。临时文件可清理、可检查、可调试，stdin 管道不可检查、不可调试。可调试性比"干净"更重要。

### 缺陷 3：Docker 卷名前缀不一致（已修复，commit `8975ca2`）

**现象**：沙箱容器挂载 `conclave-workspace:/workspace`，但 backend 容器实际挂载的卷是 `conclave_conclave-workspace`（compose 自动加项目前缀）。两个不同的卷，文件互不可见。

**根因**：docker-compose 的卷名默认带项目名前缀（`{project}_{volume}`）。沙箱是 sibling 容器，用 `docker run` 直接创建，不走 compose，所以卷名不带前缀。**设计时假设卷名就是 `conclave-workspace`，但 compose 实际创建的是 `conclave_conclave-workspace`。**

**教训**：
1. Sibling 容器挂载 compose 管理的卷时，必须用 compose 实际的卷名（带项目前缀），不能用逻辑卷名。
2. 跨 Docker 管理方式（compose vs docker run）的卷名不一致是隐蔽的 bug——不报错，只是文件互不可见。需要在沙箱初始化时校验卷名。

---

## 7. 建议的处理顺序

若继续推进，建议按以下顺序（优先做收益高、风险低的）：

1. **P0-1 useSvgPanZoom** + **P0-2 useAutoScroll**（前端 DRY，低风险）
2. **P0-6 角色画像统一到 ROLE_LIBRARY**（后端 Registry，有回归测试保护）
3. **P0-12 BorrowAdjudicator**（借调责任链，已有测试覆盖）
4. **P1-13 EvidenceCollector** + **P1-14 ProduceStrategy**（orchestrator 策略模式，中等风险）
5. **P1-7 LLM 策略对象化**（高风险，需完整回归）
6. **P1-18/19/20 接口预留**（低风险，为 v3 铺路）

其余 P2 项可在相关功能迭代时顺手完成。
