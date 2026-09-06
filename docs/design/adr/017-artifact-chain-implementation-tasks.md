# 产物链、项目命名空间与议题池 — 实施任务清单

> ADR: docs/design/adr/017-artifact-chain-project-issue-pool.md
> 创建时间: 2026-09-04
> 状态: Phase 3 进行中（Phase 1 已闭环 2026-09-05 / Phase 2 已闭环 6952efb 2026-09-05）

---

## 实现期决策记录（起草任务清单时的代码核验结论）

以下决策为任务拆分时对现有代码核验后确定，均附核验依据：

| # | 决策 | 依据 |
|---|------|------|
| I1 | `artifacts.type` 直接复用 `deliverable_type` 取值（`feasibility_report`/`adr`/`test_suite`/`prd_openapi`/`design_doc`/…），不另建类型映射表 | ADR-017 的 type 枚举（prd/openapi/…）是示意性的；1:1 复用避免双份枚举漂移。`test_report` 伴生产物在 Phase 3 以独立 type 值出现 |
| I2 | 产物摘要注入复用 `state.reference_context` 通道（带「上游产物」分节标题），不新增 anchor 注入点 | `conclave_core/anchor.py:52` 已把 reference_context 注入全阶段 prompt，`app/agents/compute.py:398` 已有清洗（防注入）。血缘数据仍独立存 `source_artifact_ids`，注入通道共享不等于数据模型合并（ADR-017 D3 双轨仍成立） |
| I3 | `artifacts.content` / `source_artifact_ids` 用 PostgreSQL JSONB | 先例：`app/db/models/tenant.py:25` tenants.settings JSONB；测试与生产均为 PostgreSQL |
| I4 | Publish 幂等键 = `UNIQUE (meeting_id, type, version)`，冲突时 `on_conflict_do_update` 刷新内容 | ADR-017 D2 要求幂等可重试；version 由发布时查 max(version)+1 计算 |
| I5 | 大产物阈值：artifact JSON 序列化 > 200KB 时不写 `content` 列，只存 `summary` + `content_ref`（指向 `workspace/{meeting_id}/` 相对路径） | ADR-017「大产物不入库」红线；阈值为工程魔数，代码中加注释 |
| I6 | 三个新产出类型的 workflow 模板（`feasibility`/`adr`/`test_gen`）注册进 `WORKFLOW_TEMPLATES`；`run_clarify` 覆写 `workflow_template` 时，若 `deliverable_type` 属于三新类型则保留对应模板不被 complexity 映射覆盖 | 对齐 ADR-017「与 ADR-014 对齐」节；参照 `stage_runners.py:57` flow_plan=="plan" 的保留模式 |
| I7 | Publish 钩子位置：`runner.py` 设置 `MeetingStatus.DONE` 处（约 :798）之后调用，异常仅记日志不阻断终态 | Publish 是快照动作，失败可由补偿重试，不应使会议僵死；instant 模式终态路径实现时核实是否需要同步挂钩 |
| I8 | Phase 3 前置修复：`produce.py` 兜底分支（约 L1666）补 `feasibility_report`/`adr` 键；`test_suite` 走专属分支（含执行闭环）不走兜底 | 核验发现 Phase 1 缺口：三种新产出类型的 LLM 结果均无代码路径写入 `state.artifact`（兜底只拷贝 4 个旧键），质量门禁测试手工构造 artifact 未暴露该问题 |
| I9 | `test_suite` 沙箱执行只跑一次捕获结果，不做单文件 refine loop | `refine_python_code` 面向单文件设计，test_suite 为多文件结构；会议级 `should_iterate` 机制（质量门禁不达标重跑 produce）已提供粗粒度反馈环 |
| I10 | `test_files[].path` 双重防护：白名单正则 `^[A-Za-z0-9_][A-Za-z0-9_\-.\/]*$` + 拒绝 `..` + `resolve().relative_to(ws_root)`；pytest 命令仅由已校验路径拼接 | 路径来自 LLM 输出；字符集受限后命令拼接无注入面（对齐 `code.py` 参数列表无 shell 模式） |
| I11 | `test_report` 伴生产物在 `publish_meeting_artifact` 内发布：仅当 `deliverable_type == "test_suite"` 且 `artifact["test_report"]` 存在时追加一条 `type="test_report"` 记录，`source_artifact_ids` 指向同批 test_suite 产物 id；失败仅记日志 | 伴生产物不阻断主产物发布；血缘挂接使 lineage 可查（I1 决策：test_report 为独立 type 值） |
| I12 | git 封装新建 `app/services/git_service.py`：`asyncio.create_subprocess_exec("git", *args)` 参数列表无 shell（对齐 `code.py:_run_git`）；bot 身份 `conclave-bot <conclave-bot@conclave.local>` 仅 `git config --local`；提交排除临时文件（`.pytest_cache`/`__pycache__`/`*.pyc`/`.conclave/`） | 全后端无 git commit/push 封装与 bot 身份（核验确认）；本地配置不污染全局 |
| I13 | `POST /artifacts/{id}/push` 语义：`confirm=false`（默认）→ 200 返回 diff 摘要（dry-run 供 UI 展示）；`confirm=true` → 执行 push；workspace 非 git 仓库或无 remote → 409 | ADR-017 D8 + 工程红线「进入共享空间的 git 操作必须用户显式确认」；dry-run 与执行共用一端点，以 confirm 参数区分 |
| I14 | pytest 沙箱执行超时 60s（`CONCLAVE_TEST_SUITE_TIMEOUT` 可覆盖） | 测试套件通常重于 tested_system 单文件（30s）；魔数加环境变量出口（AGENTS.md §5.4） |

---

## Phase 1：产物一等公民 + 产物链最小闭环 + 三类型一次建齐

目标：会议成功终态产物自动发布入 `artifacts` 表；新会议可勾选上游产物精确消费（摘要注入 + 血缘记录）；`feasibility_report` / `adr` / `test_suite` 三种产出类型可用且各有质量门禁。

### T1.1 Alembic 迁移：artifacts 表 + meetings 加列

- 文件: `backend/alembic/versions/0007_add_artifacts_table.py`（down_revision = `0006_align_legacy_timestamp_types`）
- `artifacts` 表（对齐 ADR-017 数据模型 + 本项目 ORM 约定）:
  - `id` String(36) PK；`tenant_id` Integer nullable index（TenantScopeMixin 约定，非 ADR 示意中的 varchar）
  - `meeting_id` String(36) NOT NULL，FK meetings.id ondelete CASCADE
  - `project_id` String(36) NULL（Phase 2 补 FK，本阶段不建外键——目标表尚不存在）
  - `type` String(50) NOT NULL；`title` String(500)；`summary` Text
  - `content` JSONB NULL；`content_ref` String(500) NULL
  - `version` Integer NOT NULL default 1；`parent_id` String(36) NULL
  - `source_artifact_ids` JSONB NOT NULL default `'[]'::jsonb`
  - `created_by` String(100) NULL；`created_at` DateTime(tz) server_default now()
  - `UNIQUE (meeting_id, type, version)`（I4 幂等键）
  - 索引: `idx_artifacts_tenant`、`idx_artifacts_meeting`、`idx_artifacts_type`
- `meetings` 表: `ADD COLUMN project_id String(36) NULL`、`ADD COLUMN issue_id String(36) NULL`（ADR-017 Phase 1 第 1 条：先建列，FK Phase 2 补）
- downgrade: 删列 + 删表（逆序）
- 验收: `alembic upgrade head` / `downgrade -1` / `upgrade head` 往返成功（容器内）；`docker compose config` 合法
- 测试: 迁移本身不单测，由 DAO 集成测试覆盖建表结果

### T1.2 ArtifactModel ORM 模型

- 文件: `backend/app/db/models/artifact.py`（新建）+ `app/db/models/__init__.py` 注册导出
- 继承 `Base, UUIDPrimaryKeyMixin, CreatedAtMixin, TenantScopeMixin`（对齐 `meeting.py` 模式）
- 字段与迁移一致；`meeting_id` 声明 `ForeignKey("meetings.id", ondelete="CASCADE")`（meetings 是 ORM 管理表，可声明 FK，先例 `MeetingTagModel`）；`project_id` / `parent_id` 不声明 FK（目标表/自引用在 Phase 2 前不做约束，避免 create_all 报错，见 `db/base.py` docstring 警示）
- 不使用 relationship（`docs/sql-development-rules.md` §1.2 红线）
- 验收: `schema_verify` 通过；模型字段与迁移逐一对应
- 测试: 随 DAO 测试覆盖

### T1.3 artifact_dao（含租户隔离与幂等发布）

- 文件: `backend/app/dao/artifact_dao.py`（新建）
- 函数（对齐 `meeting_dao.py` 模式：`tenant_filter_expr` + `current_tenant_id` + `async_session_factory`）:
  - `publish_artifact(...) -> dict`: pg_insert + `on_conflict_do_update(index_elements=["meeting_id","type","version"])`，写入即幂等
  - `next_version(meeting_id, type) -> tuple[int, str|None]`: 查 max(version) 与最新版 id（供 parent_id）
  - `get_artifact(artifact_id) -> dict|None`: 租户过滤
  - `get_artifacts_by_ids(ids) -> list[dict]`: 批量 + 租户过滤（跨租户引用拒绝的数据基础，复用 `produce.py:734` 校验模式）
  - `list_artifacts(meeting_id=None, type=None, limit=50, offset=0) -> {items,total}`: `ORDER BY created_at DESC`（UI 红线：最新在上）
- 验收: 跨租户 `get_artifact` 返回 None；重复 publish 同 (meeting, type, version) 不产生新行
- 测试: `backend/tests/test_artifact_dao.py`（幂等重放、版本递增与 parent_id 链、跨租户隔离、空列表边界）

### T1.4 artifact_service（Publish 编排：状态 → 产物行）

- 文件: `backend/app/services/artifact_service.py`（新建；若 services 目录不存在则核实项目服务层惯例后落位）
- `publish_meeting_artifact(state: MeetingState) -> dict|None`:
  - `state.artifact` 为空 → 返回 None（不发布，记日志）
  - type = `state.deliverable_type`（I1）；title/summary 提取复用 `meeting_dao._extract_artifact_summary` 同款逻辑（抽为共享函数或复制，实现时按重复度定）
  - 大产物分流（I5）：序列化 > 200KB → `content=None` + `content_ref="{meeting_id}/"`；否则 `content=artifact dict`
  - version/parent_id 经 `next_version()`；`source_artifact_ids` 取自 state（T1.6 新增字段）
  - 整个函数 try/except 包裹由调用方执行：发布失败只记 `log_bus.error`，不抛出
- 验收: 同一 state 连续发布两次，第二次走冲突更新不新增行；超大 artifact 只存指针
- 测试: `backend/tests/test_artifact_publish.py`（空 artifact 不发布、大产物分流、摘要提取降级、重复发布幂等）

### T1.5 Runner 挂钩：DONE 终态触发 publish

- 文件: `backend/app/orchestrator/runner.py`（约 :798 `state.status = MeetingStatus.DONE` 之后）
- 调用 `await publish_meeting_artifact(state)`，异常捕获仅记日志（I7）
- 同步核实 instant 模式（`app/orchestrator/instant.py`）终态路径：若存在独立 DONE 设置点且产出 artifact，同样挂钩；若无则记录不挂钩原因
- 发布成功后 `bus.publish` 事件 `artifact.published`（meeting_id + artifact_id + type + version），供前端刷新
- 验收: 标准六阶段会议跑完 → artifacts 表出现一行；publish 内部异常不改变会议 DONE 终态
- 测试: 以 stub 状态对象驱动 publish 挂钩的纯逻辑测试（不依赖完整编排）

### T1.6 三个 produce 模板 + PRODUCE_TEMPLATES 注册

- 文件: `backend/conclave_core/prompts.py`
- 新增 `PRODUCE_FEASIBILITY_REPORT`（输出 JSON：title/summary/verdict[go|no-go|conditional]/dimensions[技术|成本|风险|合规]/assumptions/blockers）、`PRODUCE_ADR`（输出 JSON：title/summary/status/context/decision_table[D 决策表: #|决策|理由|被推翻替代]/consequences/alternatives_rejected）、`PRODUCE_TEST_SUITE`（输出 JSON：title/summary/target_scope/test_files[{path,code}]/run_instructions/coverage_notes）
- `PRODUCE_TEMPLATES` 追加三键（`feasibility_report`/`adr`/`test_suite`）
- `app/agents/prompts.py` re-export 列表补三个常量（produce 节点从该路径 import）
- 模板措辞遵守 `communication_style.yaml`（中文、无 emoji）；输出 JSON 约束与现有模板同风格（硬约束：结构化 JSON + Pydantic 校验）
- 验收: `get_produce_template("adr")` 返回新模板；未知类型仍回退 `PRODUCE`
- 测试: `backend/tests/test_produce_templates.py`（三模板注册存在、互不相同、render 占位符不缺省报错）

### T1.7 质量门禁分派扩展

- 文件: `backend/app/orchestrator/runner.py`
- `_evaluate_quality`（:1128）:
  - `feasibility_report` / `adr` → `_evaluate_quality_document`，`required_fields_map` 追加:
    - `feasibility_report`: [title, summary, verdict, dimensions, assumptions]
    - `adr`: [title, summary, context, decision_table, alternatives_rejected]
  - `test_suite` → `_evaluate_quality_code`，补 test_suite 分支（存在性看 `test_files` 非空 + `run_instructions`；无执行结果时按「未执行」扣分而非硬门槛——执行闭环 Phase 3 才有）
- 验收: 三类型空产出触发 hard_failures；完整产出 score ≥ 60 不触发迭代
- 测试: `backend/tests/test_quality_gate_new_types.py`（空产出硬门槛、缺字段扣分、占位符扣分、test_suite 未执行降级——非正向用例 ≥ 1）

### T1.8 workflow 模板注册 + clarify 保留逻辑

- 文件: `backend/app/orchestrator/workflow_templates.py` + `stage_runners.py`
- `WORKFLOW_TEMPLATES` 追加（I6）:
  - `feasibility`: stages=[clarify, intra_team, cross_team, evidence_check, produce]，produce_type=feasibility_report
  - `adr`: stages=[clarify, intra_team, cross_team, produce]，produce_type=adr
  - `test_gen`: stages=[clarify, intra_team, cross_team, produce]，produce_type=test_suite
- `run_clarify`（stage_runners.py:66 前）: `deliverable_type` ∈ 三新类型时，`workflow_template` 固定为对应模板，跳过 `complexity_to_template` 覆写（参照 :57 plan 保留模式）
- 验收: 创建 deliverable_type=adr 的会议，clarify 后 workflow_template=="adr" 不被覆写；旧类型行为不变
- 测试: `backend/tests/test_workflow_templates.py` 追加（新模板阶段序列、保留逻辑、未知类型回退 standard）

### T1.9 MeetingState 扩展 + 会议创建 API 接收 source_artifact_ids

- 文件: `backend/app/domain/meeting.py`、`backend/app/schemas/meeting.py`、`backend/app/routers/meetings.py`
- `MeetingState` 新增 `source_artifact_ids: list[str] = Field(default_factory=list)`（同步 `MeetingObservabilitySection` 与 snapshot/restore 路径——实现时 grep `reference_meeting_ids` 的全部出现点逐一对照）
- `CreateMeetingRequest` 新增 `source_artifact_ids: list[str] = Field(default_factory=list, max_length=20)`
- `create_meeting`:
  - `get_artifacts_by_ids(req.source_artifact_ids)` → 不存在/跨租户的 id 记日志并剔除（复用 `produce.py:734` 拒绝模式，不报错阻断创建）
  - 有效产物的 summary 拼入 `state.reference_context`（I2，分节标题「[上游产物引用]」）
  - `state.source_artifact_ids` = 有效 id 列表
- 验收: 引用合法产物创建会议 → reference_context 含产物摘要；引用他人租户产物 → 被静默剔除且有告警日志
- 测试: `backend/tests/test_create_meeting_artifacts.py`（正常引用、非法 id 剔除、跨租户剔除、空列表）

### T1.10 产物血缘写入：publish 时记录 source_artifact_ids

- 随 T1.4/T1.5 落地：publish 时 `source_artifact_ids=state.source_artifact_ids`
- 验收: 会议 A 出产物 → 会议 A1 引用该产物 → A1 的产物行 source_artifact_ids 含 A 的 artifact_id
- 测试: 并入 `test_artifact_publish.py`

### T1.11 产物查询 API（血缘可查）

- 文件: `backend/app/routers/artifacts.py`（新建，前缀 `/artifacts`）+ `backend/app/schemas/artifact.py`
- 端点:
  - `GET /artifacts?meeting_id=&type=&limit=&offset=` → 分页列表（租户过滤）
  - `GET /artifacts/{id}` → 单条（租户过滤，404 处理）
  - `GET /artifacts/{id}/lineage` → 上游链（沿 source_artifact_ids 递归，深度上限 10 防环）
- 注册三件套（对齐 015 T1.1 模式）: `app/main.py` router 注册、`frontend/vite.config.ts` proxy 列表、`frontend/nginx.conf` API 正则
- 验收: curl 三端点返回合法 JSON；跨租户访问 404；血缘成环不死循环
- 测试: `backend/tests/test_artifacts_api.py`（列表过滤、404、跨租户 404、血缘深度上限——非正向 ≥ 2）

### T1.12 前端：产出类型选项 + Artifact 类型定义

- 文件: `frontend/src/lib/constants.ts`（`DELIVERABLE_TYPES` 追加 可行性报告/ADR/测试套件 三项）、`frontend/src/types/`（Artifact 接口）、`frontend/src/lib/api.ts`（artifacts 查询封装）
- 遵守 UI 红线：不引入渐变/3D/重阴影；中文标签
- 创建会议面板引用上游产物的选择器 UI：**不在 Phase 1 范围**（API 已支持，UI 随 Phase 2 项目视图一起做），此处只落类型与 API 封装
- 验收: `npx tsc -b --noEmit` 0 errors；新类型出现在创建会议下拉
- 测试: 前端测试按 `testing-rules`（若加组件测试须 import 真实组件 + 非正向断言）

### Phase 1 验收标准（ADR-017 原文）

> 用户能"会议 A 出可行性报告 → 会议 A1 引用该产物出 ADR → 会议 A2 引用 ADR 出可部署服务"，血缘可查。

- [ ] 三种新产出类型可创建会议并跑通（StubLLM 下结构校验通过）
- [ ] 会议成功终态自动发布产物入表，重跑不重复
- [ ] 下游会议创建时勾选上游产物 → 摘要注入 prompt → 新产物血缘含上游 id
- [ ] `GET /artifacts/{id}/lineage` 返回完整上游链

---

## Phase 2：项目与议题池（已完成，6952efb）

1. Alembic 迁移：`projects` / `issues` 表；补 `meetings.project_id/issue_id` 外键。
2. 议题两条入口：用户手动（source=user）；会议候选经人工确认（source=meeting，D7）。
3. 议题 → 会议绑定：自动填充 `project_id`/`issue_id`，仓库摄入议题 workspace。
4. 议题状态机随会议生命周期流转（resolved 需挂 `resolution_artifact_id`）。
5. 产物：项目下多议题并行，工作区隔离，闭环可追溯。

## Phase 3：测试生成闭环（进行中）

目标：`test_suite` 会议产出可执行、执行结果入产物、提交可追溯。验收：仓库进 → 测试代码生成落 workspace → 沙箱执行 → `test_report` 伴生产物发布 → workspace 自动 commit → push 端点 dry-run/确认双模式。

### T3.1 produce 写入链路补齐（I8 前置修复）

- 文件: `backend/app/orchestrator/nodes/produce.py`、`backend/app/orchestrator/stage_runners.py`
- 兜底分支（produce.py 约 L1666）键列表补 `feasibility_report`、`adr`（test_suite 不进兜底，走 T3.2 专属分支）
- `stage_runners.py` 附件扫描类型列表（约 L603）补 `test_suite`
- 发言分派补 `test_suite` 分支（生成完成 → 准备沙箱执行）；`feasibility_report`/`adr` 沿用通用分支
- 验收: 三种新类型 LLM 结果均写入 `state.artifact` 对应键
- 测试: 构造含 `feasibility_report`/`adr`/`test_suite` 键的 result，断言 artifact 对应键非空（非正向：LLM 返回缺键时不 KeyError）

### T3.2 test_suite 沙箱执行闭环

- 文件: `backend/app/orchestrator/nodes/produce.py`（新增 `elif state.deliverable_type == "test_suite":` 分支，参照 tested_system 分支结构）
- 步骤:
  1. 校验 `test_files[].path`（I10 白名单正则 + `..` 拒绝 + `resolve().relative_to`），非法路径跳过并记日志
  2. 合法文件写入 `workspace/{meeting_id}/`（保持相对路径结构）
  3. `run_command("python -m pytest <已校验路径...> -v", ws_root, timeout=60, image=SANDBOX_IMAGE_DATASCIENCE, network_level=_detect_network_level(拼接代码))`（I14）
  4. 解析 pytest 输出（复用 `sandbox.py:1968-1984` 正则模式：`X passed`/`Y failed`/`FAILED <path>::<name>`）
  5. 写回 `state.artifact["test_suite"]`（含最终 test_files）、`state.artifact["execution"]`（exit_code/stdout/stderr/sandboxed）、`state.artifact["test_report"]`（passed/failed/failures/output 尾部 3000 字符/executed_at/test_file_count）
  6. 执行异常（沙箱不可用等）→ `execution={"error": ..., "exit_code": -1}`，test_report 记 `error`，不阻断产出
- 验收: StubLLM 下结构校验通过；沙箱拒绝执行时产物仍发布（降级可追溯）
- 测试: mock `run_command` 全通过/部分失败/沙箱异常三态；路径穿越用例（`../evil.py` 被拒）

### T3.3 质量门禁执行分支校准

- 文件: `backend/app/orchestrator/runner.py` `_evaluate_quality_code`（约 L1661-1675）
- 现状缺陷: `exit_code != 0` 且无 `error` 键时落入「未执行」分支（+15），已执行但失败被误判为未执行
- 修改: `exit_code is not None` 即视为已执行——`== 0` +30；非 0 +10 并反馈失败数（有 test_report 时带 passed/failed）；`exit_code is None` 才走 error/未执行分支
- 测试: 已执行失败（exit_code=1）不再命中「未执行」文案；未执行（无 execution）仍 +15

### T3.4 test_report 伴生产物发布（I11）

- 文件: `backend/app/services/artifact_service.py` `publish_meeting_artifact`
- 主产物发布成功后：`deliverable_type == "test_suite"` 且 `artifact["test_report"]` 为 dict → 追加发布 `type="test_report"`，`source_artifact_ids=[主产物 id]`，project_id 同主产物；异常仅 `log_bus.warning`
- 测试: 伴生发布成功/主产物发布失败不伴生/伴生异常不影响主产物返回（三态）

### T3.5 git_service（I12）

- 文件: `backend/app/services/git_service.py`（新建）
- 函数:
  - `commit_workspace(meeting_id, topic) -> dict`: workspace 无 `.git` 则 `git init`；`git config --local` bot 身份；写 `.gitignore`（`.pytest_cache/`、`__pycache__/`、`*.pyc`、`.conclave/`，幂等）；`git add -A` + `git commit -m "test(<meeting_id 前 8 位>): <topic 截断 80>"`；返回 `{commit_sha, files_changed, inserted, deleted}`；无变更返回 `{committed: False}`
  - `diff_summary(meeting_id) -> dict`: `git status --porcelain` + `git diff --stat HEAD`（未提交变更摘要，供 push dry-run）
  - `push_repo(meeting_id) -> dict`: 取首个 remote（`git remote`）→ `git push <remote> HEAD`；无 remote 抛 `GitPushError`；超时 120s kill（对齐 code.py 受控子进程模式：`GIT_TERMINAL_PROMPT=0` 防交互挂死）
- 子进程统一 `asyncio.create_subprocess_exec("git", *args)`，env 注入 `GIT_TERMINAL_PROMPT=0`；错误输出脱敏（复用 `code.py:_redact` 模式）
- 测试: 临时目录真实 git 仓库——init+commit 往返（提交可 `git log` 验证）、重复提交无变更返回 committed=False、临时文件不入提交、无 remote push 抛错、路径非 workspace 拒绝

### T3.6 POST /artifacts/{id}/push 端点（I13）

- 文件: `backend/app/routers/artifacts.py`、`backend/app/schemas/artifact.py`
- schema: `ArtifactPushRequest{confirm: bool = False}`；`ArtifactPushResponse{mode: "dry_run"|"pushed", diff: {...}|None, pushed_to: str|None, commit_sha: str|None, message: str}`
- 逻辑: `artifact_dao.get_artifact` 取产物（404 同现有语义）→ `meeting_id` 定位 workspace → `confirm=false` 返回 diff_summary；`confirm=true` 执行 push，`GitPushError` → 409
- 验收: 挂在现有 `/artifacts` 前缀下，vite proxy / nginx 无需改动（核验确认）
- 测试: dry-run 返回 diff 不 push；confirm 无 remote → 409；跨租户 → 404

### 验收标准（Phase 3 整体）

- [ ] T3.1-T3.6 全部完成
- [ ] 容器内 ruff/mypy/pytest 全绿（含新增测试，每文件 ≥1 非正向用例）
- [ ] StubLLM 端到端：test_suite 会议 → 产物表含 test_suite + test_report 两条记录，血缘可查
- [ ] git 链路：workspace 自动 commit（bot 身份、Conventional Commits）；push dry-run/确认双模式

## Phase 4：理想态（另开 ADR）

1. 自主迭代调度器（配额 + 每日上限 + 人工审批，D9）。
2. 项目级仓库缓存（共享克隆 + worktree）。
3. 项目级代码库理解索引（ADR-018，project_id 隔离）。
4. 产物版本 diff/merge 视图。
5. 议题合入流程（D11 + ADR-018 D13 索引增量）。

---

## 测试策略（用户约定）

- 开发期间只写测试、不逐次跑容器；Phase 1 全部任务完成后在 Docker 容器内一次性跑 `ruff check` + `ruff format --check` + `mypy` + `pytest` 全套。
- 每个测试文件至少 1 个非正向用例（`testing-rules` §9）；配对函数（publish/查询、版本链）有往返测试（§3）。

## 完成定义（DoD）

- [ ] T1.1-T1.12 全部完成
- [ ] 容器内 ruff/mypy/pytest 全绿
- [ ] 手动端到端冒烟：三类型链路（可行性报告 → ADR → 可部署服务）血缘可查
- [ ] 提交遵循 Conventional Commits（`feat(backend)` 为主，前端 `feat(frontend)`），单提交 ≤ 400 行，按 T 组拆提交
