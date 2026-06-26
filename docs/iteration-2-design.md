# Conclave 迭代二详细设计

> 本文是 [`mvp-plan.md`](./mvp-plan.md) v2 阶段的工程细化：三层记忆、动态角色库、事件总线抽象、力导向图。
> 迭代一已完成主闭环（六阶段 + 五层确定性 + 证据分级 + 感知层接口），迭代二在此之上做"系统化升级"。
> 设计原则遵循 [`design-principles.md`](./design-principles.md)，终态愿景对齐 [`ideal-design.md`](./ideal-design.md)。

---

## 1. 迭代二目标

迭代一解决了"能跑通"和"输出稳定"两个问题。迭代二解决三个新问题：

1. **记忆碎片化**——每次会议从零开始，agent 不记得上次的表现，无法迭代优化。
2. **角色僵化**——固定 3 角色无法应对不同议题类型，但自动加角色又容易角色爆炸。
3. **实时性弱**——run 端点同步阻塞，前端等待期间无反馈；事件只有内存广播，无法审计回放。

迭代二不引入新的外部依赖，全部在现有 Python + FastAPI + React 栈内完成。

### 1.1 实现状态（2026-06-27 更新）

| 章节 | 功能 | 状态 | 测试 |
|---|---|---|---|
| §2 | 三层记忆系统（RawMemory + FeatureMemory + ProfileMemory） | ✅ 已实现 | 24 个 |
| §3 | 动态角色库（RoleTemplate + ROLE_LIBRARY 6 角色） | ✅ 已实现 | 8 个 |
| §4 | 事件总线序列号 + 增量回放 + GET /events | ✅ 已实现 | 8 个 |
| §5 | 力导向图（d3-force SVG 可视化） | ✅ 已实现 | npm build 通过 |
| §6 | run 异步化（asyncio.create_task） | ✅ 已实现（第一周） | 4 个 |
| §7 | 审计端点（trace + charter） | ✅ 已实现（第一周） | 6 个 |

全部 75 个测试通过（22 smoke + 24 memory + 8 role_library + 8 event_replay + 13 determinism），前端构建通过。三层记忆的 SQLite 持久化预留接口（当前内存存储），画像自动更新阈值调参待后续迭代。

---

## 2. 三层记忆系统

### 2.1 设计目标

对齐 [`ideal-design.md`](./ideal-design.md) §6 的三层记忆：原始发言层、行为特征层、稳定画像层。迭代一只有 SQLite 留底（原始层），迭代二补齐特征层和画像层。

### 2.2 数据模型

```python
# app/memory/models.py（新建）

class MemoryLayer(str, Enum):
    RAW = "raw"           # 原始发言（不可变）
    FEATURE = "feature"   # 行为特征（提炼产出）
    PROFILE = "profile"   # 稳定画像（反哺初始化）

class RawMemory(BaseModel):
    """原始发言记录：迭代一已有，此处正式建模"""
    id: str
    agent_role: str
    meeting_id: str
    stage: str
    content: str
    evidence_refs: list[str]
    adopted: bool              # 是否被裁决采纳
    corrected_by: str | None   # 是否被后续纠正
    created_at: datetime

class FeatureMemory(BaseModel):
    """行为特征：从多次原始发言中提炼"""
    id: str
    agent_role: str
    feature_type: str          # stance_style | evidence_dependency | risk_appetite | collaboration
    feature_value: str         # "conservative" | "aggressive" | "evidence_heavy" | ...
    confidence: float          # 0-1，基于样本量
    sample_count: int          # 提炼自多少条原始记录
    source_meeting_ids: list[str]
    extracted_at: datetime

class ProfileMemory(BaseModel):
    """稳定画像：少量高价值配置项，反哺下次会议初始化"""
    agent_role: str
    default_stance_style: str       # "conservative" | "balanced" | "aggressive"
    ambiguity_tolerance: float      # 0-1
    evidence_dependency_level: str  # "low" | "medium" | "high"
    collaboration_preference: str   # "independent" | "collaborative" | "bridging"
    escalation_threshold: float     # 0-1，何时倾向升级/借调
    updated_at: datetime
    version: int                    # 乐观锁
```

### 2.3 提炼流水线

会议结束后（produce 阶段完成），自动触发提炼：

```text
produce 完成
  → 收集本次会议所有 RawMemory
  → 调 LLM 做特征提炼（输入：该角色全部发言 + 裁决结果）
  → 产出 FeatureMemory（附 confidence 和 sample_count）
  → 合并到已有 FeatureMemory（加权平均）
  → 每 N 次会议后（或 confidence > 0.7）触发画像更新
  → 产出 ProfileMemory
  → 下次会议初始化时，agent 的 prompt 注入其画像参数
```

### 2.4 画像注入

下次会议创建 agent 时，查 `ProfileMemory`，把画像参数拼到角色 prompt 的"决策偏置"部分：

```
[系统] 你是产品架构师。
决策偏置（基于历史行为特征）：
- 默认风格：conservative
- 证据依赖：high
- 协作偏好：bridging
- 升级阈值：0.6
```

没有历史数据时走默认值（迭代一行为不变）。

### 2.5 迭代二实现边界

| 必须实现 | 预留接口 | 不做 |
|---|---|---|
| RawMemory 正式建模 + SQLite 存储 | 画像自动更新阈值调参 | 跨 agent 画像迁移 |
| 特征提炼（LLM 驱动，会议结束触发） | 多维度特征加权策略 | 在线学习 / 梯度更新 |
| ProfileMemory 存储 + 注入 | 画像版本对比与回滚 | 人格漂移检测 |

---

## 3. 动态角色库

### 3.1 设计目标

迭代一固定 3 角色（moderator / product_architect / engineer）。迭代二引入角色库 + 借调机制，但严格受借调三问法约束（[`design-principles.md`](./design-principles.md) 原则 2）。

### 3.2 角色模板

```python
# app/agents/role_templates.py（新建）

class RoleTemplate(BaseModel):
    """角色模板：可被会议实例化"""
    role_id: str                    # "product_architect" | "security_expert" | "data_engineer" | ...
    display_name: str
    perspective: str                # 核心视角描述
    evidence_preference: str        # "constraints" | "risk" | "goals" | "policies"
    risk_appetite: str             # "conservative" | "balanced" | "aggressive"
    default_stance: str             # 默认立场
    prompt_template: str            # 该角色的 intra_team prompt 模板

# 内置角色库（首期 6 个）
ROLE_LIBRARY: dict[str, RoleTemplate] = {
    "moderator": ...,
    "product_architect": ...,
    "engineer": ...,
    "security_expert": ...,         # 新增：安全视角
    "data_engineer": ...,           # 新增：数据视角
    "ux_designer": ...,              # 新增：用户体验视角
}
```

### 3.3 借调完整流程

迭代一的借调只记录申请不真正加入 agent。迭代二补齐：

```text
主持人提交借调申请（三问表单）
  → charter.is_already_borrowed? → 是 → reject
  → 否 → charter.register_borrow(target_role, "approve_temporary")
  → 实例化 RoleTemplate 为 Agent
  → 注入到当前阶段（intra_team 或 evidence_check）
  → 该 agent 发言后，标记为 "temporary_borrowed"
  → 会议结束后，该 agent 的发言纳入特征提炼
  → 但不纳入稳定画像（临时借调不沉淀人格）
```

### 3.4 角色数量约束

借调三问法 + charter 防重复 + 硬上限：

- 单次会议最多借调 2 个角色（硬上限，防止角色爆炸）
- 每个借调角色只能发言一次（frozen scope）
- 借调角色的发言不参与 cross_team 辩论（只提供视角，不参与裁决）

---

## 4. 事件总线抽象

### 4.1 设计目标

对齐 [`ideal-design.md`](./ideal-design.md) §4。迭代一是 `InMemoryEventBus`，迭代二抽薄接口 + 加 replay 能力。

### 4.2 接口升级

```python
# app/events.py（改造）

class EventBus(Protocol):
    """事件总线协议：首期内存实现，后期换 Redis/MQ 不改上层"""
    async def publish(self, event: DomainEvent) -> None: ...
    async def subscribe(self, topic: str) -> AsyncIterator[DomainEvent]: ...
    def history(self, meeting_id: str) -> list[DomainEvent]: ...  # 新增：回放
    def replay(self, meeting_id: str, from_ts: datetime | None = None) -> list[DomainEvent]: ...  # 新增

class InMemoryEventBus:
    """内存实现 + 事件历史存档"""
    _events: dict[str, list[DomainEvent]]  # 按 meeting_id 分组

    async def publish(self, event: DomainEvent) -> None:
        # 广播给订阅者 + 存入历史
        ...

    def history(self, meeting_id: str) -> list[DomainEvent]:
        return self._events.get(meeting_id, [])

    def replay(self, meeting_id: str, from_ts: datetime | None = None) -> list[DomainEvent]:
        events = self.history(meeting_id)
        if from_ts:
            events = [e for e in events if e.ts >= from_ts]
        return events
```

### 4.3 WS 连接增强

WS 连接时除了推快照，还推历史事件回放（已有），迭代二加增量回放：

```text
WS 连接
  → 推 snapshot（当前状态）
  → 推 history events（全部历史）
  → 推 replay.done
  → 之后实时推送
```

断线重连时，客户端带 `last_event_ts`，服务端只推该时间点之后的事件（增量回放）。

---

## 5. 力导向图（前端）

### 5.1 设计目标

迭代一前端是四块布局，迭代二在 Header 下方加一个可折叠的力导向图，展示 agent 关系与冲突拓扑。

### 5.2 数据结构

```typescript
interface ForceGraphData {
  nodes: {
    id: string          // agent role 或 conflict id
    label: string
    type: 'agent' | 'conflict' | 'evidence'
    role?: Role
    stance?: string
  }[]
  links: {
    source: string
    target: string
    type: 'argues' | 'conflicts' | 'supports' | 'cites'
    weight: number
  }[]
}
```

### 5.3 组件

```text
<ForceGraph data={graphData} collapsed={true} onToggle={...} />
```

- 纯 SVG + d3-force（不引入完整 d3，只装 `d3-force` 一个子包）
- 可折叠（默认收起，点击展开覆盖四块布局）
- 节点点击高亮对应聊天消息和证据面板

---

## 6. run 异步化

### 6.1 当前问题

`POST /meetings/{id}/run` 同步 await 整个六阶段，HTTP 请求阻塞直到完成。StubLLM 很快可接受，真实 LLM 时前端等待期间无反馈。

### 6.2 改造方案

```python
# app/routers/meetings.py（改造）

@router.post("/meetings/{id}/run")
async def run_meeting(id: str):
    """触发会议流程：立即返回，后台异步执行"""
    meeting = get_meeting(id)
    if not meeting:
        raise HTTPException(404)
    if meeting.status == "running":
        raise HTTPException(409, "Meeting already running")

    # 后台任务执行，不阻塞 HTTP 响应
    asyncio.create_task(runner.run(meeting_id=id))
    return {"meeting_id": id, "status": "running", "message": "会议已启动，通过 WS 观看实时进度"}
```

前端调 run 后立即连 WS，通过事件流观看进度。run 端点不再等待完成。

### 6.3 状态同步

- run 触发后 `status=running`
- 每个阶段完成后通过 `stage.changed` 事件推送
- produce 完成后 `status=done` + `artifact.generated`
- 异常时 `status=error` + `error` 事件

---

## 7. 审计端点

### 7.1 GET /meetings/{id}/trace

导出本次会议的完整 LLM 调用追踪：

```json
{
  "meeting_id": "...",
  "summary": {
    "total_calls": 12,
    "successful": 10,
    "fallback": 2,
    "inconsistent": 1,
    "avg_latency_ms": 1200
  },
  "calls": [
    {
      "call_id": "...",
      "stage": "clarify",
      "model": "Qwen/Qwen3.5-4B",
      "temperature": 0.0,
      "seed": 42,
      "prompt": "...",
      "raw_response": "...",
      "validation_status": "valid",
      "consistency_status": "consistent",
      "attempt": 1,
      "latency_ms": 800
    }
  ]
}
```

### 7.2 GET /meetings/{id}/charter

导出会议宪章 + 结论锁定链：

```json
{
  "charter": {
    "original_topic": "...",
    "clarified_topic": "...",
    "meeting_goal": "...",
    "scope": ["..."],
    "constraints": ["..."],
    "forbidden_topics": [],
    "borrow_history": []
  },
  "conclusion_chain": {
    "conclusions": [
      {
        "conclusion_id": "locked-clarify-abc123",
        "stage": "clarify",
        "content": {...},
        "content_hash": "abc123",
        "locked_at": "..."
      }
    ]
  },
  "confidence_flags": {
    "clarify": "high",
    "intra_team": "low",
    ...
  },
  "drift_log": [
    {"stage": "intra_team", "severity": "minor", "reason": "..."}
  ]
}
```

---

## 8. 迭代二排期

| 周次 | 任务 | 产出 |
|---|---|---|
| 第 1 周 | run 异步化 + 事件总线 history/replay + 审计端点 | 后端可异步跑 + 审计可导出 |
| 第 1 周 | 三层记忆数据模型 + 特征提炼 + 画像注入 | agent 可跨会议积累特征 |
| 第 2 周 | 动态角色库 + 借调完整流程 | 可按议题借调专家 |
| 第 2 周 | 力导向图前端 + ChatPanel 流式优化 | 可视化升级 |
| 第 2 周 | 集成测试 + Demo 录制 | 端到端可演示 |

---

## 9. 与其它文档的关系

- 三层记忆对齐 [`ideal-design.md`](./ideal-design.md) §6
- 动态角色库受 [`design-principles.md`](./design-principles.md) 原则 2（借调三问法）约束
- 事件总线对齐 [`ideal-design.md`](./ideal-design.md) §4
- run 异步化是 [`iteration-1-design.md`](./iteration-1-design.md) §4 WS 事件的配套升级
- 力导向图对齐 [`mvp-plan.md`](./mvp-plan.md) v2 演进路线
