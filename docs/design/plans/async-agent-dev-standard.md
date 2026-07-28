# 异步 Agent 系统开发规范（可复用）

> **定位**：可嵌入任意项目 AGENTS.md 的标准开发规范。技术栈基线为 Python 3.12 + asyncio + Redis + MQ（按需）+ 负载均衡 + Docker。
> **风格**：实战纪律 + 踩坑清单，非学术论文。每条规则可执行、可核验。
> **来源**：由 Conclave 项目架构讨论沉淀（见 `discussion-engine-component-autonomy.md`），已去项目耦合，通用化处理。
> **状态**：草案 v0.1，待实战验证后定稿。

---

## 0. 核心原则（先记住这三条）

1. **组件自治 + 引擎做薄**。组件自己管健康/限流/自身并发，引擎只管发现/编排/监督/契约。引擎一旦插手组件的并发和数据一致性，组件就退化成薄壳。
2. **出口形态跟着调用方走，不跟着"层"走**。同进程用函数调用，跨进程用消息/RPC，对外才用 HTTP。一个系统里通常只有最外层需要 Web 框架（FastAPI）。
3. **复杂度分层下放，不在应用层重造分布式协调**。无状态 + 外置状态是水平扩展的前提，水平扩展的复杂度交给基础设施（Docker/K8s），别在 Python 进程内重实现。

---

## 1. 技术栈基线

| 层 | 技术 | 用途 | 关键约束 |
|---|---|---|---|
| 运行时 | Python 3.12 + asyncio | 主运行时 | 原生 asyncio，禁止阻塞调用；CPU 密集段用 `run_in_executor` 或拆 worker |
| Web | FastAPI | 对外 HTTP 网关 | **只在最外层用一处**，内层组件不重复起 HTTP 服务 |
| 缓存/锁 | Redis | 去重、限流、分布式锁、轻量队列 | 易失，关键状态必须落 DB |
| 消息 | MQ（Redis Stream / NATS / RabbitMQ） | 跨进程可靠投递 | **按需引入**，见 §4.2，不是默认全上 |
| 数据库 | PostgreSQL（+ JSONB 扩展槽） | 持久状态、唯一约束、事务 | 状态机的唯一真相源 |
| 部署 | Docker Compose / K8s | 多阶段构建、水平扩展 | 禁止本地直接跑服务 |

**依赖管理铁律**：所有依赖锁定版本（lock 文件），镜像源统一国内源。新增依赖先确认无替代、维护活跃、license 兼容。

---

## 2. 架构原则：引擎 + 组件自治

### 2.1 组件自治的边界（按成本分三档）

| 档 | 关注点 | 谁来管 | 落点 |
|---|---|---|---|
| 便宜 | 健康检查、生命周期守护、限流 | 组件自己 | 健康端点 + per-component token bucket + supervisor 重启 |
| 中等 | 并发控制、竞争 | 组件自己，用现成原语 | `LazyLock`/`LazySemaphore`（循环感知），别重造 |
| 昂贵 | 水平扩展、平面节点扩展 | 基础设施 | K8s/Docker，应用只保证无状态 + 外置状态 |

**第三档铁律**：千万别在应用层重造。水平扩展的难点不在"加节点"，在"加完后状态一致、租户隔离、任务不重跑、连接不串"。应用层想自己解决 = 在 Python 进程内重实现分布式协调，投入产出比极差。

### 2.2 引擎的三职责（只做这三件）

1. **发现与路由**：组件注册、能力声明、请求分发。
2. **监督与编排**：组件挂了重启、pipeline 阶段流转、超时熔断。
3. **契约**：组件间用结构化消息通信，不直接 import 对方内部模块。

**引擎不该做**：替组件管并发、替组件管限流、替组件管数据一致性。一旦插手，组件就不自治，退化成"引擎 + 一堆薄壳"。

### 2.3 进程边界决定引擎形态

| 部署形态 | 引擎形态 | 隔离强度 |
|---|---|---|
| 单进程 | 进程内 event_bus + 组件注册表 | 逻辑隔离（一崩全崩） |
| 多进程/多容器 | 消息总线（Redis Stream/NATS）+ 契约 schema | 物理隔离（独立扩展/重启） |
| 对外 | FastAPI 网关（唯一 HTTP 出口） | — |

**决策顺序**：先定 AgentRunTime 与 backend 是同进程还是分进程。这个选择决定引擎是进程内总线还是跨进程消息总线，后面所有架构决策都依赖它。

---

## 3. 出口形态分层

**核心规则：出口形态由调用方决定，不由"我是第几层"决定。**

| 调用方 | 出口形态 | 何时用 |
|---|---|---|
| 同进程上层代码 | 函数调用 / 方法 | 默认，零成本 |
| 同机其他进程 | Unix socket / 本地 RPC | 拆进程后 |
| 跨机组件 | 消息总线 / RPC | 拆服务后 |
| 浏览器/外部客户端 | HTTP API | **只有这层用 FastAPI** |

**反模式：每层一个 FastAPI。** 把对外网关的形态复制到内层 = 每次调用走 HTTP 序列化 + 网络栈，白增延迟和复杂度，零收益。正确形态是**越往内越轻，最内层就是函数调用**。

---

## 4. 并发与一致性

### 4.1 并发五问的解法分层

这五个问题不是一类东西，混在一起会让"引擎"变成上帝对象。逐个归位：

| 问题 | 谁来解 | MQ 是解法吗 |
|---|---|---|
| 幂等性 | 消费端 + 数据库约束 | 不是。MQ 是其**来源**（重复投递），不是解法 |
| 唯一性 | 数据库唯一约束 / 分布式锁 | 不是。存储层的活 |
| 消息重复消费 | 消费端幂等 + 去重表 | 不是。MQ 保证 at-least-once，去重仍靠自己 |
| 失败回滚 | 本地事务 / Saga 补偿 | 不是。MQ 只管投递，回滚是业务逻辑 |
| 死信队列 | MQ 原生能力 | **是**。只有这个是 MQ 的活 |

**五个里只有一个真正需要 MQ。** 其余四个，MQ 不但不解决，反而会制造——"重复消费"正是因为引入了 MQ 才出现。

**解法速查**：
- 幂等性：`INSERT ON CONFLICT DO NOTHING`（upsert）/ 乐观锁（version 字段）/ 幂等键去重表
- 唯一性：PG `UNIQUE` 约束（最可靠）/ Redis `SETNX`（分布式锁）
- 重复消费：消息 ID 去重表 / 让操作本身幂等
- 失败回滚：单操作用本地事务；跨服务用 Saga 补偿；2PC 基本不用（太重）
- 死信队列：RabbitMQ/NATS 原生；Redis Stream 无原生，需自造（读 PEL 超时 + 转移）

### 4.2 MQ 引入时机（不要提前上）

**MQ 引入的是最终一致性，代价是脆弱性增加**（多故障点、调试难、运维重）。不是"将来可能要用就提前上"。

**引入 MQ 的触发判据（满足才上）**：
1. 已决定拆进程/拆服务，组件间需要跨进程通信
2. 确实需要"可靠投递 + 消费确认 + 重试 + 死信"这一整套
3. 流程是事件驱动（非同步编排），需要异步解耦

**不该上 MQ 的场景**：
- 单进程 asyncio，event_bus 是进程内的 → 没有跨进程投递，没有重复消费问题
- 同步编排的 pipeline（A→B→C 顺序执行）→ 用 MQ 是过度设计
- 跨进程但只需轻量通知 → 用 PG `LISTEN/NOTIFY` 或 Redis pub/sub，比 MQ 轻得多

### 4.3 幂等方案：trace_id 去重

**方向**：trace_id 作幂等键是行业标准做法。但有两个细节必须拆对。

**拆分一：去重和排队是两件事。**
- 去重：判断"这个 key 处理过没有" → 用独立存储（Redis SETNX / PG 唯一约束）
- 排队：决定"消息按什么顺序投递" → 用队列

把去重塞进队列 = 队列同时承担两个职责，反而更脆（队列要维护"已投递集合"，这个集合本身是共享状态，又引入新竞争）。

**正确流程**：
1. 消息进来，先查去重存储：`SET key value NX EX ttl`
2. NX 成功 → 没处理过 → 入队投递
3. 已存在 → 重复 → 丢弃或返回上次结果

**拆分二：去重粒度必须是 (trace_id, stage)，不是 trace_id。**
- 多阶段 pipeline 里，同一 trace_id 要依次经过多个阶段
- 若 key 只用 trace_id，前一阶段锁着，后一阶段正常流转会被误挡 → pipeline 卡死
- key 格式：`{namespace}:dedup:{trace_id}:{stage}`

**锁的防护组合（防僵尸锁）**：
1. TTL 兜底：`EX ttl`，按阶段最大执行时间设
2. 状态机：锁 value 存 `{status: processing|done|failed, result_ref: ...}`
3. 完成写终态：`status=done`，后续重复请求读 result_ref 返回缓存
4. 失败释放：`DEL key`，让下次重试能重新抢锁

**伪代码**：
```python
key = f"conclave:dedup:{trace_id}:{stage}"
ok = await redis.set(key, json.dumps({"status": "processing"}), nx=True, ex=300)
if not ok:
    state = json.loads(await redis.get(key))
    if state["status"] == "done":
        return cached_result(state["result_ref"])  # 幂等返回
    return "already_processing"  # 重复挡掉
try:
    result = await run_stage(stage, ...)
    await redis.set(key, json.dumps({"status": "done", "result_ref": ...}), ex=86400)
except Exception:
    await redis.delete(key)  # 失败释放，允许重试
    raise
```

**去重存储选型**：
- Redis SETNX：快但易失（重启丢锁，可能短暂放行重复）
- PG 唯一约束：慢但持久，低频操作更稳
- 原则：高频用 Redis，低频关键状态用 PG

---

## 5. 状态机与阶段推进

### 5.1 两种"stage 重复"要分开

| 成因 | 描述 | 解法 |
|---|---|---|
| A：已完成阶段被重新触发 | 状态已前移，旧阶段又被请求 | 状态机 n+1 规则挡住 |
| B：同一阶段被并发同时启动 | 两请求同时看到 current_stage=n，都启动 | trace_id+锁串行化 |

**n+1 状态机是主防护（成因 A），trace_id 锁是并发补防护（成因 B）。两者分工，不是二选一。**

### 5.2 n+1 主规则 + 非线性转移白名单

**默认规则**：成功状态强制前移 n→n+1。

**但 pipeline 往往不是严格线性**。显式列出所有合法的非前移转移，用白名单而非"+1 规则"：

```
允许的转移（示例，按实际 pipeline 调整）：
  clarify        → intra_team      (正常前移)
  clarify        → clarify         (循环：需用户补充)
  intra_team     → cross_team      (正常前移)
  intra_team     → intra_team      (supplement 补角色，带 attempt 计数)
  cross_team     → evidence_check  (正常前移)
  cross_team     → intra_team      (回流，带门禁校验)
  evidence_check → arbitrate
  arbitrate      → produce
  任意(failed)   → 同阶段           (失败重试，带 attempt 上限)
```

白名单比"+1 规则"稳，因为它把所有例外显式化，不会出现"以为只允许前移，结果循环被卡"的隐蔽 bug。

### 5.3 失败重试

- failed 状态允许同阶段重试（n→n），attempt+1
- attempt 超阈值（如 3 次）→ 不再重试，整个 run 标 failed，等人工/降级
- 成功后 attempt 清零，前移 n+1

### 5.4 两道防护协作（请求处理流程）

```
请求进来 (trace_id, target_stage)
  ↓
[第一道：状态机检查] current_stage 与 target_stage 是否符合白名单？
  ├─ 不符合 → 拒绝（成因 A 被挡）
  └─ 符合 → 继续
  ↓
[第二道：trace_id 锁] SET trace_id:stage NX
  ├─ 已存在 → 重复请求，返回"处理中"或缓存结果（成因 B 被挡）
  └─ 抢到锁 → 执行阶段
  ↓
执行完成 → 状态机前移 current_stage = n+1 → 释放锁并写终态
执行失败 → 保留 failed 状态 → 释放锁允许重试
```

**进阶：状态机带版本号（乐观锁）**。用 `UPDATE ... WHERE current_stage=:expected` 在一条 SQL 里完成"检查+前移"，天然防住成因 B 的一部分，减少对 trace_id 锁的依赖。

---

## 6. 容错与监督

### 6.1 健康检查

- 每个组件暴露 `/health`，返回自身依赖状态（DB/Redis/MQ 是否 ok）
- 引擎聚合各组件健康状态，对外暴露总健康端点
- 健康检查不查业务数据，只查依赖连通性

### 6.2 守护与重启

- **单进程内**：try/except + supervisor 重置状态。不是 OS 级守护。
- **跨进程**：容器编排（Docker `restart: unless-stopped` / K8s liveness probe）负责重启
- 重启策略：指数退避，避免崩溃循环

### 6.3 限流

- per-component token bucket（组件自治）
- 全局限流在网关层（FastAPI 中间件）
- LLM 调用必须有限流，防止配额耗尽

### 6.4 超时熔断

- 每个阶段设最大执行时间（LLM 调用 5 分钟，DB 查询 30 秒）
- 超时 → 标记 failed，走失败重试
- 连续失败触发熔断：暂停该组件，告警

---

## 7. 部署与扩展

### 7.1 无状态原则

**可水平扩展的前提是组件无状态。** 状态分类处理：

| 状态类型 | 处理 | 例子 |
|---|---|---|
| 业务状态 | 外置到 PG | 会议、claim、decision |
| 缓存状态 | 外置到 Redis | 中间结果、会话 |
| 进程内状态 | 允许，但重启丢失不影响正确性 | 连接池、LRU 缓存 |

**禁止**：把影响正确性的状态留在进程内（如"已处理标记"），重启后丢失会导致重复处理。

### 7.2 水平扩展交给基础设施

- 应用层只保证无状态 + 外置状态
- 水平扩展的复杂度（负载均衡、健康检查、滚动更新）交给 Docker Compose / K8s
- 不在 Python 里自造服务发现/负载均衡

### 7.3 多实例协作的注意点

加节点后必须保证：
- 状态一致（外置到 DB）
- 租户隔离（每查询带 tenant_id）
- 任务不重跑（trace_id 去重 + 状态机）
- 连接不串（连接池按实例隔离）

### 7.4 CPU 密集段的处理

asyncio 是单线程，CPU 密集段（embedding、arbitrate 计算）会阻塞事件循环：

- 轻量：`asyncio.run_in_executor(process_pool, cpu_func)`
- 重量：拆独立 worker 进程/容器，asyncio 主进程只做编排
- 拆 worker 是"平面节点扩展"的天然切口

---

## 8. 问题注意清单（踩坑）

> 每条都踩过，出现即 CI 红或生产 Bug。写代码时主动避开。

### 8.1 asyncio 事件循环绑定

**症状**：`RuntimeError: got Future attached to a different loop`、测试挂死。

**根因**：模块级实例化的 `asyncio.Lock()/Semaphore()/Event()/Queue()` 绑定到第一个循环，`asyncio.run()` 创建新循环后原语失效。

**规则**：
1. 模块级禁止直接实例化 asyncio 原语，用循环感知的 `LazyLock`/`LazySemaphore`（首次访问绑定当前循环，循环变化自动重建）
2. 持有原语的单例 getter 必须循环感知：保存创建时 loop 引用，`get()` 时检测 `loop.is_closed()` 或 loop 变化则重建
3. 不要在同步代码中 `asyncio.run(engine.dispose())` 去释放绑定到其他循环的引擎，直接丢弃引用让 GC 回收

### 8.2 僵尸锁

**症状**：处理中崩溃，锁留在 Redis，后续所有同 key 请求被误挡。

**规则**：锁必须带 TTL + 状态机。value 存 `{status, result_ref}`，完成写终态，失败主动 DEL。不能只 `SET NX` 不带 `EX`。

### 8.3 去重粒度错误

**症状**：多阶段 pipeline 卡死，后阶段无法流转。

**根因**：去重 key 只用 trace_id，前一阶段锁着，后阶段被误挡。

**规则**：去重粒度必须是 `(trace_id, stage)`，不是 trace_id 单独。同阶段重复才挡，跨阶段正常流转。

### 8.4 状态机写成"+1 规则"

**症状**：合法的循环/回流/supplement 被卡死，pipeline 无法推进。

**规则**：状态机转移写成显式白名单（允许的 from→to 对），不要用"只允许 +1"的简单规则。非线性转移（循环、回流、supplement）必须显式列出。

### 8.5 函数内 import 滥用

**症状**：代码审查发现大量 import 写在函数体内。

**规则**：
1. 默认模块级 import（Python import 幂等，不重复加载）
2. 仅三种情况允许函数内 import：循环依赖、重依赖延迟加载、可选依赖 try/except
3. 重构前必须验证无循环依赖（grep 反向引用），无反向引用则安全提到模块级
4. 禁止"习惯性函数内 import"（不确定有没有循环依赖就全塞函数里）

### 8.6 多实例数据隔离

**症状**：加节点后数据交叉污染、任务重跑、Redis key 冲突。

**规则**：
1. 每查询带 tenant_id，GET by ID 必须校验 tenant_id
2. 测试隔离用独立 PG 库 / Redis DB / collection
3. 清理数据用 `DELETE FROM` + `ALTER SEQUENCE`，不用 `TRUNCATE CASCADE`（锁超时）
4. 外键统一 `ON DELETE SET NULL`，避免级联删除意外

### 8.7 MQ 过早引入

**症状**：单进程系统强行上 MQ，调试困难，延迟增加，无收益。

**规则**：MQ 只在"已拆进程 + 需要可靠投递 + 事件驱动"三条件同时满足时引入。单进程用 event_bus，同步编排用函数调用，轻量通知用 PG LISTEN/NOTIFY 或 Redis pub/sub。

### 8.8 每层一个 HTTP 服务

**症状**：内层组件套 FastAPI，每次调用走 HTTP 序列化 + 网络栈，延迟高、复杂度高。

**规则**：只有最外层（面向浏览器/外部客户端）用 FastAPI。内层出口形态由调用方决定：同进程函数调用，跨进程消息/RPC。

---

## 9. AGENTS.md 嵌入模板（精简版）

> 以下内容可直接粘贴到项目 AGENTS.md 的技术栈/架构章节。完整版见本文档 §1–§8。

```markdown
## 技术栈基线

| 层 | 技术 | 关键约束 |
|---|---|---|
| 运行时 | Python 3.12 + asyncio | 原生 asyncio，禁止阻塞调用；CPU 密集段用 run_in_executor |
| Web | FastAPI | 只在最外层用一处，内层不重复起 HTTP |
| 缓存/锁 | Redis | 去重、限流、分布式锁；易失，关键状态落 DB |
| 消息 | MQ（按需） | 拆进程 + 需要可靠投递 + 事件驱动时才引入 |
| 数据库 | PostgreSQL + JSONB | 状态机唯一真相源 |
| 部署 | Docker Compose / K8s | 多阶段构建，禁止本地直接跑服务 |

## 架构三原则

1. 组件自治 + 引擎做薄。组件管健康/限流/自身并发，引擎管发现/编排/监督/契约。
2. 出口形态跟着调用方走。同进程函数调用，跨进程消息，对外才 HTTP。
3. 水平扩展交给基础设施。应用只保证无状态 + 外置状态，别在 Python 里重造分布式协调。

## 并发五问解法

- 幂等性：upsert / 乐观锁 / 幂等键去重表
- 唯一性：PG UNIQUE 约束 / Redis SETNX
- 重复消费：消费端幂等 + 去重表（MQ 保证 at-least-once，去重靠自己）
- 失败回滚：本地事务 / Saga 补偿
- 死信队列：MQ 原生能力（唯一真正需要 MQ 的）

## 幂等去重规则

- key 格式：`{ns}:dedup:{trace_id}:{stage}`（粒度必须是 trace_id+stage，不是 trace_id）
- 锁必须带 TTL + 状态机（value 存 status，完成写终态，失败 DEL）
- 去重和排队分开：去重用 SETNX，排队用队列，别让队列背去重

## 状态机规则

- 成功状态强制 n+1，但用显式白名单而非"+1 规则"
- 非线性转移（循环/回流/supplement）必须显式列出
- failed 允许同阶段重试，带 attempt 计数，超阈值不再重试
- 两道防护：状态机检查（成因 A）+ trace_id 锁（成因 B）

## 踩坑清单（高频）

- asyncio 原语禁止模块级实例化，用循环感知的 LazyLock/LazySemaphore
- 锁必须带 TTL，否则僵尸锁
- 去重粒度必须是 (trace_id, stage)
- 状态机用白名单，不用"+1 规则"
- import 默认模块级，仅循环依赖/重依赖/可选依赖才函数内
- 多实例每查询带 tenant_id，清理用 DELETE 不用 TRUNCATE CASCADE
- MQ 不提前上，三条件满足才引入
- 只有最外层用 FastAPI，内层别套 HTTP
```

---

## 10. 待验证项（定稿前需实战核验）

- [ ] 幂等方案在真实高并发下的表现（trace_id 锁的竞争程度）
- [ ] 状态机白名单是否覆盖所有合法转移（需结合具体 pipeline）
- [ ] MQ 引入时机判据是否可操作（三条件是否足够）
- [ ] CPU 密集段拆 worker 的切口选择
- [ ] 去重存储选型（Redis vs PG）的决策阈值

---

> 本规范为草案 v0.1，基于架构讨论推导，未在独立项目实战验证。采用前建议先在一个真实场景跑通，根据反馈迭代。每条规则定稿前需按项目实际情况核验。
