# ADR-002: 元数据扩展槽（JSONB）而非核心表加业务字段

| 字段 | 值 |
|------|-----|
| 编号 | ADR-002 |
| 状态 | Accepted |
| 日期 | 2026-07-19 |
| 影响范围 | meetings 表结构、核心 MeetingState 领域模型、插件数据读写模式、数据库迁移策略 |

## 背景

在实施插件化架构（ADR-001）后，首个落地的业务插件是 team（团队管理）。team 插件需要为每场会议记录以下信息：

- `namespace`：会议所属的团队/项目命名空间（如 `acme-corp/design-team`）；
- `visibility`：可见性级别（private / team / workspace / public）；
- `token_source`：使用的 API Key 来源（user-provided / team-pool / enterprise-pool）；
- `default_prompt_template`：团队默认提示词模板 ID；
- `compliance_tags`：合规标签列表（如 `gdpr`, `hipaa`, `internal-only`）。

未来其他插件也会有类似需求：billing 插件需要记录 `cost_center`、`charge_account`；audit 插件需要记录 `retention_policy`、`legal_hold`；analytics 插件需要记录 `campaign_id`、`ab_test_group` 等。

我们面临一个架构决策：这些插件专属的字段应该如何存储？在 v0.2 的硬编码时代，做法是直接给 `meetings` 表加列，但插件化之后核心不应感知任何业务插件的字段语义。我们需要一种既能让插件便捷存取专属数据、又不污染核心表结构、性能可接受的方案。

## 决策

在核心 `meetings` 表上添加一个通用扩展字段：

```sql
ALTER TABLE meetings ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::jsonb;
```

**核心规则：**

1. **核心不解读内容**：核心代码（`conclave/core/`）永远不读取 `metadata` 内的具体键，不在上面施加业务校验，仅做透传存取；
2. **命名空间隔离**：插件必须使用自身名称作为顶级键进行命名空间隔离，例如 team 插件写入 `metadata['team'] = {...}`，billing 插件写入 `metadata['billing'] = {...}`；
3. **读写约定**：
   - 插件通过钩子 `on_meeting_create`、`before_meeting_update` 返回要 merge 的 metadata 片段，核心负责将其 merge 到行记录；
   - 读取时核心将完整 `metadata` 字段注入 `MeetingState`，插件通过 `meeting.metadata['team']` 访问自身数据；
   - 禁止插件写入其他插件的命名空间（核心在 DEBUG 模式下做越权检测并告警）；
4. **索引策略**：核心不创建任何 `metadata` 相关的 GIN 索引。如果某个插件需要按其命名空间内的字段查询，由该插件在自己的迁移文件中创建部分索引（Partial Index），例如：
   ```sql
   CREATE INDEX idx_meetings_team_namespace ON meetings ((metadata->'team'->>'namespace'))
   WHERE metadata ? 'team';
   ```
5. **默认值与迁移**：新字段默认空对象 `'{}'::jsonb`，不需要为历史数据做 backfill。插件在读取时应对缺失键做防御性处理（使用 `.get()` 并提供默认值）。

**领域模型层面：**

- `MeetingState` 增加 `metadata: dict[str, Any]` 字段，类型为通用 dict；
- 核心提供 `MetadataView` 辅助类，插件通过 `MetadataView(meeting, 'team')` 获得一个带默认值和类型提示的访问器，但不强制使用。

## 选项对比

| 选项 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 选项A：插件自建关联表，每个插件一张 `meeting_<plugin>_data` 表，通过 `meeting_id` 外键关联 | 范式严格，字段类型明确；数据库层面约束强；插件可完全自主管理表结构 | 每次加载 Meeting 需要 JOIN 多张表（5+ 插件意味着 5+ JOIN），查询复杂度上升；插件启停需要动态加/删 JOIN；WebSocket 推送 MeetingState 时需要跨表聚合，代码复杂；跨插件查询（如"列出 namespace=X 且 cost_center=Y 的会议"）需要多表 JOIN，性能差；插件卸载可能留下孤儿表 | 否决，性能和代码复杂度代价过高，不符合单体插件化的简洁目标 |
| 选项B：核心表直接加具体业务字段，如在 meetings 上加 namespace、visibility、token_source 等列 | 查询性能最优；字段类型、NOT NULL、外键约束天然支持；现有 ORM 代码无需改动 | 核心必须感知 team 等插件的业务概念，违反 ADR-001 的插件化原则；每加一个插件就要改核心表，核心与插件同生共死；字段爆炸——20 个插件可能加 80+ 列，meetings 表变得极宽；私有化部署禁用 team 插件时这些列为空，浪费存储且语义混乱 | 否决，与插件化架构直接冲突，会让核心重新沦为"上帝对象" |
| 选项C：JSONB metadata 扩展槽（选定） | 无需改核心表结构即可容纳任意插件字段；单表查询，无 JOIN 开销；PostgreSQL JSONB 支持字段级索引、包含查询、路径操作，性能在合理索引下与原生列差距 <10%；核心完全不感知业务语义，插件启停自由；天然支持 schema 演进，插件加字段只需改自己的代码 | 数据库层面无法对 JSONB 内部键施加类型/非空约束，需要插件在应用层做校验；JSONB 存储比原生列略占空间；不恰当的全量 GIN 索引会拖慢写入；多插件并发 merge 同一行 metadata 时需要乐观锁或序列化隔离（核心通过 SELECT ... FOR UPDATE 解决） | 选定，在保持核心纯净的前提下提供了优秀的灵活性和可接受的性能 |

## 后果

### 正面影响

1. **核心表稳定**：`meetings` 表的核心列长期保持稳定（预计只增不减，且新增仅限核心语义字段如 `summary_updated_at`），插件增删不触发核心迁移；
2. **插件自治**：插件开发者可以自主决定要存储哪些字段、何时加字段、字段的 JSON 结构，不需要提交核心 PR 修改表结构；
3. **查询性能**：读取会议详情是单点主键查询，无 JOIN，单次查询 <1ms；列表查询通过插件自建的 Partial Index 保证性能；
4. **部署灵活**：禁用插件时，该插件命名空间下的 metadata 自然被忽略，不需要清理数据；重新启用后数据仍在；
5. **简化 API 层**：`GET /meetings/{id}` 接口直接返回完整 metadata，前端按插件需要渲染对应区块，不需要为每个插件定制响应字段。

### 负面影响

1. **数据校验责任下移**：核心不再替插件做字段类型校验，插件必须自己在写入前校验 schema（推荐使用 Pydantic model 做 metadata 子结构校验）；
2. **跨插件查询受限**：无法用一条 SQL 做"跨 3 个插件命名空间的复杂 JOIN"，需要在应用层组装或通过 EventBus 做数据投影；
3. **迁移一致性**：插件升级需要修改 metadata 子结构时（如字段重命名），需要插件自己写数据迁移脚本，核心不提供通用机制；
4. **调试可见性**：直接在数据库里 `SELECT * FROM meetings` 时 metadata 列是一坨 JSON，阅读体验不如原生列；
5. **乐观冲突**：两个插件在同一请求中并发更新 metadata 的不同命名空间时，若使用默认读提交隔离级别可能丢失更新，需要核心显式加行锁。

### 缓解措施

- 核心在 `before_meeting_update` 钩子调用前对会议行执行 `SELECT ... FOR UPDATE`，保证钩子链中所有 metadata 修改在同一事务内原子 merge；
- 提供 `conclave.lib.metadata.MetadataView` 工具类，内置 Pydantic schema 校验、默认值填充、变更检测，减少插件重复代码；
- 规定插件必须在 `plugin.yaml` 中声明 metadata schema 版本（`metadata_schema_version`），并在插件启动时对历史数据做惰性升级（lazy migration）；
- 在开发环境提供 CLI 工具 `conclave doctor metadata`，扫描所有会议的 metadata 并报告违反命名空间规范、schema 版本过旧的数据；
- 运营数据库定期对 metadata 列做 `pg_column_size` 监控，单条记录 metadata 超过 8KB 时告警（防止插件滥用扩展槽存储大文本，大文本应使用独立表或对象存储）。

### Metadata Merge 语义

核心在合并多个插件返回的 metadata 片段时，采用**深度 merge（deep merge）**策略而非简单替换：

- 不同命名空间的键互相独立（`metadata['team']` 与 `metadata['billing']` 互不影响）；
- 同一命名空间内，若两个插件（虽然规范不推荐，但理论上可能）写入同一顶级键，按钩子调用顺序后者覆盖前者；
- merge 在 Python 层使用递归 dict merge 实现，不使用 PostgreSQL 的 `jsonb_set` 链式调用，保证钩子链中所有修改在应用层聚合后一次性写库；
- 对于列表类型字段（如 `compliance_tags`），插件若需追加元素，应读取现有列表后返回完整新列表，而非期望核心做智能数组合并。

MetadataView 使用示例：

```python
from conclave.lib.metadata import MetadataView
from pydantic import BaseModel

class TeamMetadata(BaseModel):
    namespace: str = "personal"
    visibility: str = "private"
    token_source: str = "user-provided"
    compliance_tags: list[str] = []

view = MetadataView(meeting, namespace="team", schema=TeamMetadata)

# 读取，自动返回 Pydantic 模型实例，带默认值
team_meta = view.get()  # TeamMetadata(namespace="personal", ...)

# 写入，自动校验 schema
view.set(TeamMetadata(namespace="acme/design", visibility="team"))

# 部分更新（patch）
view.patch({"visibility": "public"})
```

### 不纳入本决策的内容

- 本决策仅规范核心领域对象（meetings、users）的元数据扩展，不约束插件自建表。插件如果有高频聚合查询、大量数据写入、或超出单 JSON 字段容量的需求，仍可自建表；
- transcript（逐字稿）、message（实时消息）等高频写入的明细表不使用 metadata 扩展槽，避免 JSONB 解析开销影响写入吞吐。

## 相关

- ADR-001：插件化架构作为核心扩展机制（本决策是 ADR-001 的数据层落地方案）
- ADR-003：插件三层分级（CORE 层插件如 auth 的用户 metadata 同样使用此扩展槽）
- 设计文档：`docs/design/metadata-conventions.md`（metadata 命名规范、schema 版本约定、索引最佳实践）
- 示例代码：`conclave/plugins/team/metadata.py`（team 插件的 Pydantic metadata 模型定义）
