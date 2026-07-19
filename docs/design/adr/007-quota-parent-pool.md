# ADR-007: 配额父池切分模型

| 字段 | 值 |
|------|-----|
| 编号 | ADR-007 |
| 状态 | Accepted |
| 日期 | 2026-07-19 |
| 影响范围 | `teams` 数据模型、配额计算服务、余额查询 API、API Key 继承逻辑、LLM 调用路由钩子、billing 插件 |

## 背景

Conclave 支持团队树形组织结构：企业（根团队）下可创建多个部门团队，部门下可创建子团队，以此类推。每个团队都需要有独立的 LLM Token 配额，用于控制会议期间的 AI 功能（实时总结、行动项提取、会后纪要生成等）的成本。

在树形团队结构下，配额管理有一个核心问题需要解决：**子团队的配额从哪里来？**

v0.2 版本中每个团队独立配置 API Key 和配额，在实际使用中暴露出以下问题：

1. **企业级客户充值分散**：一个拥有 20 个部门的企业客户，需要为每个部门分别在 OpenAI/Anthropic 平台充值、分别维护 API Key，IT 管理成本极高。实际访谈中 80% 的企业客户希望统一充值、统一管理；
2. **配额孤岛**：部门 A 配额耗尽但部门 B 配额有大量剩余时无法调配，造成整体资源浪费。某内测客户反馈研发团队配额使用率达 120%（超额），而行政团队使用率仅 15%；
3. **API Key 管理负担**：每个 Team Admin 都需要了解如何在 LLM 提供商平台创建 Key、配置限额、处理充值，技术门槛过高；
4. **平台统一池方案的顾虑**：如果 Conclave 平台统一提供 API Key 并按团队计量计费，Conclave 需要处理支付、充值、发票、退款等完整 Billing 流程，这对于 v0.4 MVP 来说过重，且涉及资金合规问题。

此外，还有一个关键产品决策需要明确：**Conclave 是否处理充值？** 结论是 Conclave 不直接处理充值——用户直接在 LLM 提供商（OpenAI、Anthropic、Google、国内模型厂商等）平台充值，Conclave 只做配额管理和用量追踪。

我们需要设计一种配额模型，既支持企业级客户的"统一充值、内部分配"需求，又保留团队独立使用自己 API Key 的灵活性，同时不引入复杂的支付结算逻辑。

## 决策

采用**父池切分 + API Key 继承 + 可选覆盖**模型。

### 核心概念

1. **配额池（Quota Pool）**：每个团队拥有一个逻辑配额池，由 `monthly_token_budget`（月度 Token 预算）定义；
2. **父池切分**：子团队的预算从父团队的池中"切分"出来，父团队需要跟踪已切分给子团队的总量；
3. **API Key 继承**：子团队默认使用父团队配置的 API Key（向上递归继承，直到找到显式配置的 Key 或到达根团队）；
4. **可选覆盖**：子团队可以配置自己的 API Key，覆盖继承来的 Key，此时该子团队的配额消耗从自己的 Key 计费，不消耗父池配额；
5. **不处理充值**：Conclave 不提供充值功能，API Key 对应的 LLM 账户余额由用户在提供商平台自行管理。Conclave 管理的是"用量预算"（防止超支），不是"资金账户"。

### 数据模型

在 `teams` 表上增加以下字段：

```sql
ALTER TABLE teams ADD COLUMN monthly_token_budget BIGINT NOT NULL DEFAULT 0;
-- 已切分给直接子团队的总量（缓存值，由切分/回收操作维护）
ALTER TABLE teams ADD COLUMN allocated_to_children BIGINT NOT NULL DEFAULT 0;
-- 本月已消耗 Token 量（通过 usage 记录聚合，或异步更新缓存）
ALTER TABLE teams ADD COLUMN current_usage BIGINT NOT NULL DEFAULT 0;
-- API Key 配置（加密存储，NULL 表示继承父团队）
ALTER TABLE teams ADD COLUMN llm_api_key_encrypted BYTEA;
ALTER TABLE teams ADD COLUMN llm_provider VARCHAR(50);  -- 'openai', 'anthropic', 'custom' 等
ALTER TABLE teams ADD COLUMN llm_base_url TEXT;        -- 自定义端点（如 Azure OpenAI、国内代理）
ALTER TABLE teams ADD COLUMN llm_model VARCHAR(100);   -- 默认模型覆盖
-- 预算重置日期（每月几号重置，默认 1）
ALTER TABLE teams ADD COLUMN budget_reset_day SMALLINT NOT NULL DEFAULT 1;
```

### 配额切分规则

1. **根团队初始化**：根团队创建时必须配置 API Key（或使用平台默认 Key，见下文），设置月度总预算 `monthly_token_budget`；
2. **创建子团队**：创建子团队时，父团队 Admin 指定子团队的 `monthly_token_budget`，此时：
   - 父团队的 `allocated_to_children += child_budget`；
   - 校验：父团队的可用余额 = `monthly_token_budget - current_usage - allocated_to_children`，必须 >= child_budget，否则拒绝切分；
3. **子团队再切分**：子团队也可以向自己的子团队切分配额，规则相同——子团队的可用余额 = 子团队 `monthly_token_budget` - 子团队 `current_usage` - 子团队 `allocated_to_children`；
4. **回收配额**：父团队 Admin 可以降低子团队的预算（子团队已使用量不得超过新预算），差额回到父团队的可用池；删除子团队时，其未使用的预算自动回收给父团队；
5. **预算不跨层跳切**：父团队只能切分给直接子团队，不能直接给孙团队切分（保持层级清晰，孙团队的预算由子团队从自己的池中切分）。

### API Key 解析逻辑（运行时）

当 LLM 调用发生时，通过以下链式查找确定使用哪个 API Key：

```python
def resolve_api_key(team_id: int) -> ResolvedKey:
    team = get_team(team_id)
    visited = set()
    while team is not None:
        if team.id in visited:
            raise QuotaConfigurationError("团队层级循环检测")
        visited.add(team.id)
        if team.llm_api_key_encrypted is not None:
            return ResolvedKey(
                api_key=decrypt(team.llm_api_key_encrypted),
                provider=team.llm_provider,
                base_url=team.llm_base_url,
                model=team.llm_model,
                key_owner_team_id=team.id,  # 实际计费归属
                requesting_team_id=team_id,
            )
        team = get_team(team.parent_team_id)
    # 到达根团队仍无 Key，使用平台默认 Key（如果配置了）
    if PLATFORM_DEFAULT_KEY:
        return ResolvedKey(
            api_key=PLATFORM_DEFAULT_KEY,
            provider="openai",
            key_owner_team_id=None,  # 平台计量
            requesting_team_id=team_id,
        )
    raise NoAPIKeyConfiguredError("团队未配置 API Key 且无继承 Key 可用")
```

### 余额计算

每个团队的"可用配额"需要考虑层级关系：

```
团队可用余额 = min(
    自身 budget - 自身 current_usage - 自身 allocated_to_children,
    父团队的可用余额（递归）
)
```

即：子团队能使用的配额受限于自身预算，同时也受限于父链上所有祖先团队的可用余额（因为底层使用的是某个祖先的 API Key，该 Key 的预算是由那个祖先控制的）。

### 用量归集

每次 LLM 调用完成后（通过 `after_llm_call` 钩子）：

1. 将 Token 用量记录到 `team_usage` 表（按天、按模型、按 key_owner_team_id 聚合）；
2. 更新**请求发起团队**到 **Key 归属团队**之间链路上所有团队的 `current_usage`；
3. 如果 Key 归属团队不是请求发起团队（即使用了继承的 Key），用量同时计入 Key 归属团队的 `current_usage`（即父池被消耗）。

### 平台默认 Key（可选，SaaS 部署模式）

对于不想配置自己 API Key 的个人用户或小团队，Conclave SaaS 部署可提供平台默认 Key，此时：

- 使用平台 Key 的团队按实际用量计量（Conclave 侧记录），但 Conclave 仍不处理充值，而是在免费额度用完后提示用户配置自己的 Key；
- 平台 Key 有严格的速率限制和月度限额（如每月 5 美元免费额度），仅用于试用和轻量场景。

私有化部署场景下不配置平台 Key，根团队必须配置自己的 Key。

## 选项对比

| 选项 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 选项1：每个团队独立 Key + 独立充值 | 模型最简单，团队间完全隔离；计费清晰，无跨团队干扰；不需要配额切分逻辑 | 企业客户管理成本极高（N 个团队需 N 个 Key + N 次充值）；配额孤岛无法调配；中小团队 Admin 需要理解 LLM 平台操作；不符合企业客户"统一采购、内部分配"的实际需求 | 否决，用户调研已证明此模式不适合企业场景 |
| 选项2：父池切分 + API Key 继承 + 可选覆盖（选定） | 符合企业客户统一管理需求（一个 Key 充值，全组织可用）；父池可灵活切分给子团队，避免配额孤岛；子团队可选择覆盖为自己的 Key（如独立项目组有独立经费）；Conclave 不触碰资金，只做用量预算管理；层级模型与团队树形结构天然对齐 | 配额计算需要递归向上检查祖先余额，有一定实现复杂度；用量归集需要沿链路更新多个团队；API Key 继承链需要防循环检测；余额展示需要清晰说明"受限于哪个父团队" | 选定，在 MVP 复杂度下满足核心需求，层级模型清晰可扩展 |
| 选项3：平台统一池 + 按团队计量（Conclave 转售） | 用户体验最简单——注册即用，无需任何 Key 配置；Conclave 可通过差价盈利 | Conclave 需要处理完整的支付、充值、发票、退款流程，涉及资金合规（支付牌照、税务）；需要对接支付网关（Stripe/支付宝/微信）；LLM 成本波动风险由 Conclave 承担（模型涨价直接影响毛利）；企业客户对"数据经第三方平台"有顾虑；MVP 阶段开发量预估增加 6-8 周 | 否决，MVP 阶段不做转售 billing。未来可作为增值服务（Conclave Cloud），但需要独立的 billing 系统，不在 v0.4 范围内 |

## 后果

### 正面影响

1. **企业客户体验提升**：IT 管理员只需在根团队配置一次 API Key 并充值，部门团队自动继承，管理成本从 O(N) 降为 O(1)；
2. **配额灵活调配**：父团队 Admin 可根据部门实际用量动态调整切分额度，月底未使用的配额自动回收（次月重置），提高资源利用率；
3. **保留独立性**：有独立经费或合规要求的子团队（如收购的子公司、外部合作伙伴加入的团队）可配置自己的 Key，与父池隔离；
4. **不触碰资金合规**：Conclave 不处理支付，规避了金融合规风险，MVP 开发周期不被 Billing 阻塞；
5. **模型可演进**：未来若要支持平台转售（选项3），只需在根团队之上增加一个"平台"虚拟层即可，数据模型和切分逻辑可复用。

### 负面影响

1. **配额计算复杂度**：检查一个团队是否有可用余额需要递归向上遍历到 Key 归属团队，最坏情况下 O(depth) 次查询。通过缓存 Key 解析结果和各团队余额可缓解；
2. **用量归集路径长**：一次 LLM 调用需要更新链路上所有团队的 `current_usage`，高并发下可能成为热点。通过异步批量更新（Redis 计数器 + 定时刷库）缓解；
3. **余额展示需要说明**：UI 上显示"可用余额"时，需要清晰标注是受自身预算限制还是受父团队预算限制，否则用户会困惑"我的预算还有 100 万 Token 为什么说余额不足"；
4. **Key 泄露影响范围**：如果根团队的 API Key 泄露，整个组织的配额都受影响。需要支持 Key 轮换和泄露时的紧急切换；
5. **层级变更影响**：团队在树中移动（如从部门 A 调整到部门 B）时，配额切分关系需要重新计算，需要谨慎设计移动操作的配额处理逻辑。

### 缓解措施

- **缓存 Key 解析**：`resolve_api_key` 的结果缓存到 Redis（TTL 5 分钟），团队 Key 配置变更时主动失效缓存；
- **异步用量聚合**：LLM 调用后仅向 Redis 写入 INCR 命令（按 team_id 分 key），后台任务每 30 秒批量聚合刷入 PostgreSQL，避免行锁竞争；
- **余额查询优化**：提供 `GET /api/teams/{id}/quota` 接口，返回余额明细：
  ```json
  {
    "monthly_budget": 10000000,
    "current_usage": 2300000,
    "allocated_to_children": 5000000,
    "self_available": 2700000,
    "effective_available": 2700000,
    "limited_by": null,
    "key_source": "inherited",
    "key_owner_team": {"id": "root", "name": "Acme Corp"}
  }
  ```
- **Key 安全**：API Key 使用 AES-256-GCM 加密存储（密钥从 KMS 获取），日志中禁止打印完整 Key（仅显示末 4 位）；提供 Key 轮换接口，支持新旧 Key 并行过渡期；
- **团队移动策略**：团队在树中移动时，默认回收其在原父团队下切分的预算（回到原父团队），然后在新父团队下重新申请切分。移动操作需要新父团队有足够可用余额，否则拒绝；
- **预算重置**：每月 `budget_reset_day` 触发定时任务，将所有团队的 `current_usage` 重置为 0，重新计算切分关系（allocated_to_children 保持不变，因为切分关系是持久的）。

### 与 BYOK Fallback 的关系

本 ADR 描述的是配额的**正常分配模型**，即"从哪个池扣配额"。当某个团队的有效可用余额耗尽时的行为（硬阻断还是降级到用户个人 Key）由 ADR-008 单独定义。两个 ADR 共同构成完整的配额管理体系：

- ADR-007：配额从哪里来、如何分配、如何计算余额；
- ADR-008：配额耗尽时怎么办、如何降级、如何提示用户。

## 相关

- ADR-001：插件化架构——quota 服务作为 CORE 层基础服务，billing 插件通过钩子订阅用量事件
- ADR-008：配额耗尽自动降级（BYOK Fallback）——配额耗尽时的运行时行为
- ADR-002：JSONB 元数据扩展槽——API Key 的自定义 provider 参数（如 Azure 的 deployment_name）可存储在 metadata 中
- 设计文档：`docs/design/quota-allocator.md`（配额切分算法详细设计）
