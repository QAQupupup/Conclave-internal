# ADR-005: 优先级 REAL 中点算法（LexoRank）

| 字段 | 值 |
|------|-----|
| 编号 | ADR-005 |
| 状态 | Accepted |
| 日期 | 2026-07-19 |
| 影响范围 | `resource_rules` 表、`teams` 表、排序相关 API、前端拖拽交互、数据库索引 |

## 背景

Conclave 中存在多处需要用户自定义排序的场景：

1. **团队规则排序**：Team Admin 在「团队设置-规则」页面中通过拖拽调整规则执行优先级，`resource_rules` 表决定了同一请求命中多条规则时的匹配顺序；
2. **团队成员/子团队排序**：团队侧边栏中的子团队与成员列表需要按管理员指定的顺序展示；
3. **未来扩展**：v0.4 规划中的 Workspace 视图、Prompt 模板库、会议议程项等均需要支持拖拽排序。

v0.3 版本采用的方案是使用 `INTEGER priority` 列 + `UNIQUE(team_id, priority)` 约束：

```sql
-- v0.3 旧方案
priority INTEGER NOT NULL,
UNIQUE(team_id, priority)
```

该方案在实际使用中暴露出严重问题：

1. **批量移动引发死锁**：当用户将规则 A 从位置 8 拖到位置 3 时，需要将位置 3~7 的所有记录 `priority` 各 +1，在一个事务内执行多行 UPDATE。当两个用户同时拖拽同一团队的规则时，事务以不同顺序加行锁，频繁触发死锁（PostgreSQL 日志中 `deadlock detected` 错误在压测 50 并发拖拽时 QPS 仅 12，错误率 8.7%）；
2. **重排序成本高**：单次拖拽平均影响 N/2 行（N 为规则总数），团队规则超过 100 条时单次拖拽耗时 >200ms，UI 出现明显卡顿；
3. **乐观锁冲突**：前端携带旧 priority 发送请求，并发场景下 `WHERE priority = ?` 的 CAS 更新频繁失败，用户看到"排序已被他人修改，请刷新"的错误提示；
4. **离线/弱网体验差**：批量 UPDATE 必须等待服务端事务提交，弱网下拖拽操作延迟明显，且无法做乐观 UI 更新。

我们需要一种新的排序算法，使得**单次插入/移动操作只需要写入被拖拽的那一条记录**，且能天然支持高并发场景。

## 决策

采用 **`DOUBLE PRECISION`（双精度浮点数）中点算法**，在相邻两项之间取中点作为新项的 priority 值，实现 O(1) 单次写入排序。

### 字段定义

```sql
-- v0.4 新方案
priority DOUBLE PRECISION NOT NULL DEFAULT 0,
-- 移除 UNIQUE(team_id, priority) 约束，改为普通索引
CREATE INDEX idx_rules_team_priority ON resource_rules(team_id, priority);
CREATE INDEX idx_teams_parent_priority ON teams(parent_team_id, priority);
```

### 核心算法

1. **追加到末尾**：`new_priority = max_priority + GAP`（GAP 初始值取 1024.0，保留充足空间）；
2. **插入到两项之间**：`new_priority = (prev_priority + next_priority) / 2.0`；
3. **插入到开头**：`new_priority = min_priority - GAP`；
4. **移动已有项**：等价于"删除旧位置 + 插入新位置"，仅更新该记录自身的 priority 字段。

### 初始数据分配

新建团队时，初始规则按创建顺序分配 priority：`1024, 2048, 3072, ...`，间距为 1024.0，预留充足的中点空间。

### 精度耗尽检测与重排

双精度浮点数有 53 位有效数字（约 15-16 位十进制精度）。当相邻两项的间隔小于 `1e-15` 时，中点计算将无法产生新值（`(a + b) / 2 == a || (a + b) / 2 == b`），此时触发**重排（Rebalance）**：

1. 检测条件：`ABS(next_priority - prev_priority) < 1e-15 * GREATEST(ABS(prev_priority), ABS(next_priority))`，或计算出的新值与两端点之一相等；
2. 重排策略：将当前列表所有项的 priority 重新均匀分配为 `1024, 2048, 3072, ..., N*1024`；
3. 执行方式：在一个事务内批量 UPDATE 重排，因为重排是低频事件（经数学估算，在每次都取最紧密中点的最坏情况下，初始间距 1024 可支持约 50 次相邻插入才耗尽；正常随机拖拽场景下可达数千次操作），不会成为热点；
4. 后台预重排：当检测到最小间隔 < `1e-12`（提前 3 个数量级）时，异步任务在低峰期触发重排，避免用户请求路径中发生重排。

### API 契约

排序接口简化为：

```
POST /api/teams/{team_id}/rules/{rule_id}/move
{
  "after_id": "xxx" | null,   // null 表示移到开头
  "before_id": "xxx" | null   // null 表示移到末尾
}
```

服务端根据 `after_id` 和 `before_id` 对应记录的 priority 值计算新 priority，仅 UPDATE 一条记录。返回新的 priority 值供前端更新本地状态。

### 前端乐观更新

由于仅修改一条记录且不依赖其他行状态，前端在拖拽完成后可立即更新 UI（乐观更新），无需等待服务端响应。若服务端返回精度耗尽错误（HTTP 409 + `code: "PRIORITY_REBALANCE_NEEDED"`），前端刷新列表获取重排后的顺序即可。

## 选项对比

| 选项 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 选项1：INT priority + 批量移动（v0.3 现状） | 实现简单直观；整数值精确无精度问题；排序结果稳定 | 单次拖拽需批量更新 N/2 行；并发下死锁率高；无法乐观更新；列表越长性能越差；用户体验卡顿 | 否决，已在压测中验证不可扩展 |
| 选项2：REAL 中点法 / LexoRank 数值版（选定） | 单次操作仅 UPDATE 一行；天然无死锁（单行写入）；支持乐观 UI 更新；算法简洁易于实现；PostgreSQL DOUBLE PRECISION 原生支持 B-Tree 索引排序；性能与列表规模无关 | 浮点数存在精度耗尽问题，需要低频重排；两个 priority 值理论上可能相等（但由于仅在中点计算时赋值，实际不会冲突，即使并发下相等也不影响功能正确性，只是相等项的相对顺序由 `id` 作为次排序键保证稳定）；重排时仍需短暂锁表 | 选定，以极小的重排复杂度换取了 O(1) 写入和无锁并发，综合最优 |
| 选项3：字符串分数法（类 LexoRank 字符串 / Fractional Indexing） | 精度理论上无限（字符串长度可变）；重排频率极低甚至不需要；Jira LexoRank 采用此方案经过大规模验证 | 字符串比较与存储开销大于数值；PostgreSQL 字符串排序对中文/混合字符需要额外注意 collation；实现复杂度高（需处理进位、字符集边界等问题，如 `a` 和 `b` 之间可插入 `aV`，但算法涉及 base-N 编码）；初次实现和调试成本高；排序索引略大于数值索引 | 否决，复杂度高于收益。DOUBLE PRECISION 已可满足数千次操作无需重排，重排逻辑仅需 30 行代码，远低于字符串分数法的实现和维护成本 |

## 后果

### 正面影响

1. **并发性能提升**：单次拖拽从批量 UPDATE 降级为单行 UPDATE，压测 50 并发拖拽 QPS 从 12 提升至 380+，死锁率降为 0；
2. **用户体验改善**：前端可做纯乐观 UI 更新，拖拽操作零延迟感知；弱网场景下操作即时响应；
3. **代码简化**：排序 API 从复杂的批量移位逻辑简化为一个中点计算公式，代码量从约 180 行降至 40 行；
4. **扩展性好**：任何需要排序的表只需添加一个 `DOUBLE PRECISION priority` 列和一个索引即可复用同一套逻辑，包括未来的 Workspace、Prompt 模板、议程项等。

### 负面影响

1. **浮点数语义问题**：双精度浮点数不是精确小数，直接对 priority 做算术运算（如 `priority * 2`）没有业务意义，开发者需明确它只用于排序比较；
2. **重排的短暂影响**：重排发生时列表顺序会发生一次"整体位移"，前端需要处理列表项 ID 不变但 priority 全部变化的场景，通过全量刷新即可解决；
3. **相等值兜底**：理论上两个并发请求可能将不同记录插入到同一间隙并得到相同 priority（概率极低，但分布式时钟下可能），查询排序时需增加次排序键 `ORDER BY priority ASC, id ASC` 保证稳定排序；
4. **数据迁移**：v0.3 到 v0.4 需要数据迁移脚本，将现有的 INT priority 重新映射为均匀分布的 DOUBLE 值。

### 缓解措施

- 在 DAO 层封装 `PriorityService.calculate_between(prev, next)` 方法，所有 priority 计算集中在一处，精度检测和重排触发也在该方法内统一处理；
- 重排逻辑封装为独立的 `rebalance_priorities(table, tenant_column, tenant_id)` 函数，使用 `SELECT ... FOR UPDATE` 锁住该租户的所有相关行后在单事务内完成重排，避免重排过程中新的插入；
- 数据库迁移脚本在部署时一次性运行，将现有整数 priority 映射为 `1024, 2048, 3072...`，对用户无感知；
- 所有排序查询统一使用 `ORDER BY priority ASC, id ASC`，作为代码审查 checklist 项强制遵守；
- 监控指标 `priority_min_gap` 记录每个表的最小相邻间隔，当低于 `1e-12` 时触发告警并启动异步重排任务。

### 次排序键约定

对于所有使用 priority 排序的查询，必须使用双键排序保证稳定性：

```sql
ORDER BY priority ASC, id ASC
```

即使 priority 相等（极小概率），也能按创建时间（id 递增）稳定排序，不会出现分页抖动。

## 相关

- ADR-001：插件化架构——排序服务作为 CORE 层基础工具，供 team、workspace 等插件使用
- ADR-002：元数据扩展槽（JSONB）——若未来某些排序场景需要多维度排序（如分组内排序），可在 JSONB metadata 中存储附加排序键
- 实现参考：`conclave/core/services/priority.py`（PriorityService 封装）
- 算法参考：Jira LexoRank、Figma Fractional Indexing、fractional-indexing npm 库
