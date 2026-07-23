[返回上级文档](../../README.md)

# Memory 模块 — 三层记忆系统

为 Agent 提供跨会议的持久化记忆能力，采用三层递进架构：原始发言 → 行为特征 → 稳定画像。会议结束后自动提取特征、沉淀画像，下次会议初始化时将画像注入 Agent Prompt，实现"越用越懂你"的角色演化。

---

## 架构概览

```
会议进行中
    │
    ▼
state.messages ─────────────────────────────────────┐
    │                                                │
    ▼                                                ▼
trigger_extraction()                        inject_profile() ← 下次会议初始化
    │                                                │
    ├─ record_raw()        → RawMemory（原始发言层）   │
    │                         不可变，全量留底          │
    │                                                │
    ├─ extract_features()  → FeatureMemory（特征层）   │
    │                         LLM 提炼行为特征         │
    │                                                │
    └─ update_profile()    → ProfileMemory（画像层）   │
                              高置信度稳定配置项 ──────┘
```

记忆开关由 `settings.memory_enabled` 控制，关闭时 `trigger_extraction()` 直接返回，不影响主流程。

---

## 三层记忆详解

### 第一层：RawMemory（原始发言层）

文件：`models.py` — `RawMemory`

每次会议结束后，遍历 `state.messages`，将所有 Agent 的发言按 `agent_role` 分组写入原始记忆。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | UUID |
| `agent_role` | str | 发言角色 |
| `meeting_id` | str | 所属会议 ID |
| `stage` | str | 发言阶段（clarify/intra_team/cross_team/arbitrate 等） |
| `content` | str | 发言原文 |
| `evidence_refs` | list[str] | 引用的证据 ID |
| `adopted` | bool | 是否被裁决采纳 |
| `corrected_by` | str \| None | 是否被后续纠正（记录纠错链） |
| `created_at` | datetime | UTC 时间戳 |

- 所有角色（包括临时借调角色）的发言都会记录
- 不可变，作为特征提炼的原料
- 单会议最多保留 1000 条（`_MAX_HISTORY_PER_MEETING`）

### 第二层：FeatureMemory（行为特征层）

文件：`models.py` — `FeatureMemory`

从多次原始发言中通过 LLM 提炼的行为特征，是连接原始数据和稳定画像的中间层。

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | str | UUID |
| `agent_role` | str | 角色 |
| `feature_type` | str | 特征类型（见下表） |
| `feature_value` | str | 特征值（如 "conservative"、"evidence_heavy"） |
| `confidence` | float | 置信度 0-1，基于样本量 |
| `sample_count` | int | 提炼自多少条原始记录 |
| `source_meeting_ids` | list[str] | 来源会议列表 |
| `extracted_at` | datetime | 提炼时间 |

**feature_type 取值：**

| 类型 | 说明 | 典型取值 |
|---|---|---|
| `stance_style` | 立场风格 | conservative / balanced / aggressive |
| `evidence_dependency` | 证据依赖度 | low / medium / high |
| `risk_appetite` | 风险偏好 | risk_averse / neutral / risk_taking |
| `collaboration` | 协作风格 | independent / collaborative / bridging |

StubLLM 模式下使用关键词匹配规则（`_RISK_HIGH_KEYWORDS`、`_RISK_LOW_KEYWORDS`、`_COLLAB_KEYWORDS`）做简单提炼，无需调用 LLM。

### 第三层：ProfileMemory（稳定画像层）

文件：`models.py` — `ProfileMemory`

少量高置信度配置项，是记忆系统的最终产出物，直接反哺下次会议初始化。

| 字段 | 类型 | 默认值 | 说明 |
|---|---|---|---|
| `agent_role` | str | — | 角色标识 |
| `default_stance_style` | str | `"balanced"` | 默认立场风格 |
| `ambiguity_tolerance` | float | `0.5` | 模糊容忍度 0-1 |
| `evidence_dependency_level` | str | `"medium"` | 证据依赖等级 |
| `collaboration_preference` | str | `"collaborative"` | 协作偏好 |
| `escalation_threshold` | float | `0.6` | 升级/借调阈值 0-1 |
| `updated_at` | datetime | UTC now | 最后更新时间 |
| `version` | int | `1` | 乐观锁版本号 |

- `version=1` 表示默认未更新，此时不注入 Prompt（保持迭代一行为不变）
- 仅当历史特征沉淀到足够置信度后才更新画像
- 借调角色（不在 `Role` 枚举中）只记录 RawMemory，**不沉淀画像**

---

## 画像演化与反哺机制

### 提取触发（会议结束时）

文件：`profile.py` — `trigger_extraction(state)`

会议结束后由会议收尾流程调用，执行步骤：

1. 按 `agent_role` 分组 `state.messages`
2. 对每条发言调用 `memory_store.record_raw()` 写入 RawMemory
3. 标记发言是否被裁决采纳（`adopted`）
4. 对正式 Role 的 Agent 调用 `extract_features()` + `update_profile()` 沉淀画像
5. 借调角色跳过画像沉淀

所有异常用 try/except 包裹，记忆子系统的任何错误都不会影响主会议流程。

### 画像注入（下次会议初始化时）

文件：`profile.py` — `inject_profile(prompt, agent_role)`

Agent 初始化构建 Prompt 时调用：

1. 从 `memory_store.get_profile_anchor(agent_role)` 获取画像锚点文本
2. 如果存在画像（`version > 1`），将锚点拼接到 Prompt 前面
3. 无画像时原样返回 Prompt，保持迭代一默认行为
4. 任何异常降级为原样返回 Prompt

```python
from app.memory.profile import inject_profile

base_prompt = "你是产品经理角色..."
final_prompt = inject_profile(base_prompt, "product_manager")
# 如果有画像，final_prompt 形如：
# "[历史画像] 你在过往会议中表现为 evidence_heavy 风格，风险偏好较低...
#
# 你是产品经理角色..."
```

---

## 存储实现

文件：`store.py` — `MemoryStore`（进程内单例 + PostgreSQL 持久化）

### 存储架构

- **内存缓存**：`_raw`、`_features`、`_profiles` 三个 dict，进程内快速访问
- **PostgreSQL 持久化**：复用 `async_session_factory`，通过 ORM 模型写入 `raw_memories`、`feature_memories`、`profile_memories` 表
- **启动加载**：`initialize()` 从 PG 加载已有画像和近期特征到内存
- 已从早期的 SQLite + `threading.Lock` 方案迁移至 PostgreSQL，去除了所有阻塞锁

### 容错设计

- 所有公开方法包裹在 try/except 中，失败只记 log 不抛异常
- 记忆系统是"锦上添花"能力，绝不能阻塞或破坏主会议流程
- 数据库不可用时降级为内存-only 模式

### 单例访问

```python
from app.memory.store import memory_store

# 启动时初始化（lifespan 阶段）
await memory_store.initialize()

# 记录原始发言
await memory_store.record_raw(
    meeting_id="m-123",
    agent_role="product_manager",
    stage="intra_team",
    content="我认为这个方案风险太高",
    evidence_refs=["ev-1"],
    adopted=True,
)

# 获取画像锚点
anchor = memory_store.get_profile_anchor("product_manager")
```

---

## 与 Agent 系统的集成

| 集成点 | 文件/函数 | 作用 |
|---|---|---|
| Prompt 构建 | `profile.inject_profile()` | Agent 初始化时注入画像锚点 |
| 会议收尾 | `profile.trigger_extraction()` | 会议结束后触发记忆提取 |
| ORM 模型 | `db.models.memory` | RawMemoryModel / FeatureMemoryModel / ProfileMemoryModel |
| 存储单例 | `store.memory_store` | 全局 MemoryStore 实例 |
| 配置开关 | `settings.memory_enabled` | 全局开关，关闭后记忆层完全旁路 |

---

## 关键文件索引

| 文件 | 职责 |
|---|---|
| `__init__.py` | 模块说明（三层记忆系统概览） |
| `models.py` | Pydantic 数据模型：`MemoryLayer` 枚举 + `RawMemory` / `FeatureMemory` / `ProfileMemory` |
| `profile.py` | 画像注入 `inject_profile()` + 提取触发 `trigger_extraction()` |
| `store.py` | `MemoryStore` 存储实现：内存缓存 + PostgreSQL 持久化 + 关键词规则提炼 |
