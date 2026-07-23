[返回上级文档](../../README.md)

# observability — 可观测性子系统

本模块为 Conclave 后端提供**统一的可观测性能力**，覆盖四大核心场景：

- **结构化日志**：旁路日志总线，多 Sink 分发
- **成本追踪**：LLM Token 消耗与费用统计，多维度聚合
- **运行时指标**：系统资源 + 业务指标的环形缓冲区采集
- **审计日志**：关键用户操作与安全事件持久化到 PostgreSQL

模块设计遵循「**旁路、非阻塞、故障隔离**」原则：所有观测组件的异常均不影响业务主流程。

---

## 1. 模块架构总览

```
业务代码 / 中间件 / Agent
        │
        ▼
┌──────────────────────────────────────────────┐
│            统一门面（logger.py）              │
│   get_logger(__name__) → 标准 logging 接口    │
│   WARNING 及以上自动旁路到 LogBus             │
└───────────┬──────────────────┬───────────────┘
            │                  │
            ▼                  ▼
     ┌─────────────┐    ┌──────────────┐
     │   LogBus    │    │  AuditLogger │──► PostgreSQL (audit_logs)
     │  (结构化)   │    │  (同步接口)  │
     └──────┬──────┘    └──────────────┘
            │
   ┌────────┼────────┬─────────────┐
   ▼        ▼        ▼             ▼
Console  JSONFile  EventBus    RemoteGRPC
 Sink     Sink      Sink (WS)    Sink (预留)
                      │
                      ▼
                 前端日志面板
                       
┌─────────────────┐   ┌─────────────────────┐
│  CostTracker    │   │   MetricsStore      │
│  (LLM/工具成本) │   │ (环形缓冲区,10s/点)  │
└─────────────────┘   └──────────┬──────────┘
                                 ▼
                         前端运维仪表盘
```

---

## 2. LogBus — 统一日志总线

**文件**：`log_bus.py`

### 设计理念

应用代码只负责 `emit(level, message, extra)`，不关心日志最终写到哪里。LogBus 负责：

1. **自动注入追踪上下文**：从 `contextvars` 提取 `request_id`、`meeting_id`、`runner_session_id`、`agent_role`、`user_id`、`username`、`user_role`，无需调用方手动传递。
2. **结构化事件构造**：统一 schema，所有 sink 拿到同一份 dict。
3. **多 sink 分发**：按注册顺序依次写入，sink 异常通过 `contextlib.suppress(Exception)` 静默隔离。
4. **进程级单例**：模块导入时创建 `log_bus = LogBus()`，直接 import 使用即可。

### 初始化默认 Sink

| Sink | 默认是否启用 | 触发条件 |
|---|---|---|
| `ConsoleSink` | 是 | 始终启用 |
| `EventBusSink` | 是 | 始终启用（有 meeting_id 时才推送） |
| `JSONFileSink` | 按环境 | 非 test 环境默认写入 `$CONCLAVE_LOG_DIR/conclave.jsonl`（默认 `/app/data/logs`）；也可通过 `CONCLAVE_LOG_JSON_FILE` 指定路径 |
| `RemoteGRPCSink` | 否 | 预留接口，需手动 `add_sink()` |

### 事件 Schema

```python
{
    "timestamp":         "2026-07-24T10:00:00+00:00",  # UTC ISO8601
    "level":             "INFO" | "WARNING" | "ERROR" | "DEBUG",
    "request_id":        "...",                         # 从 contextvars 自动注入
    "meeting_id":        "...",
    "runner_session_id": "...",
    "agent_role":        "...",
    "user_id":           "...",
    "username":          "...",
    "user_role":         "...",
    "logger":            "app.agents.clarify",
    "message":           "...",
    "extra":             {...},                         # 业务自定义字段
}
```

### 快捷方法

```python
from app.observability.log_bus import log_bus

log_bus.info("会议已创建", logger=__name__, extra={"meeting_id": mid})
log_bus.warning("LLM 调用失败，正在重试", extra={"provider": "siliconflow", "attempt": 2})
log_bus.error("浏览器池耗尽", extra={"pool_size": 10})
log_bus.debug("中间状态", extra={"state": state.dump()})
```

---

## 3. Sinks — 日志输出端

**文件**：`sinks.py`

所有 Sink 实现统一的 `write(event: dict) -> None` 接口，线程安全，内部吞掉所有异常。

### 3.1 ConsoleSink

人类可读格式输出到 stdout（默认），适合开发期调试。

**输出格式**：
```
2026-07-24T10:00:00 [INFO] [req-xxx] [mtg-xxx] [sess-xxx][alice] app.agents.clarify: 阶段完成 {"duration_ms": 123}
```

- 使用 `threading.Lock` 保证多线程下行不交错
- 自动 flush，支持 Docker 日志实时采集
- **无内置 ANSI 着色**：终端着色由日志消费者（如前端日志面板、外部日志工具）负责，后端保持纯文本以便日志系统（Loki/ELK）解析

### 3.2 JSONFileSink

每行一个 JSON 对象（JSON Lines 格式），写入追加模式的 UTF-8 文件。

- 适合生产环境，可被 ELK / Loki / Fluentd / vector 等直接采集
- 支持外部 `logrotate` 做日志轮转
- 线程安全写入，自动 flush
- 提供 `close()` 方法优雅关闭文件句柄

### 3.3 EventBusSink

**前端实时日志推送**的核心通道：将日志通过 WebSocket 事件总线发布为 `log.entry` 事件。

关键策略：

- **只推送有 `meeting_id` 上下文的日志**（会议运行期间产生的日志），避免系统级噪声干扰前端
- **最低级别 `INFO`**：DEBUG 日志不推送，减少前端流量
- **噪声过滤**：`uvicorn.access`、`uvicorn.error`、`app.middleware.trace` 等高频 logger 自动忽略
- **精简 payload**：只推送 `level / logger / message / timestamp / agent_role / stage` 字段，避免把大 extra 数据塞到 WS 帧
- **线程安全**：通过 `loop.call_soon_threadsafe` 跨线程投递到事件循环

### 3.4 RemoteGRPCSink（预留）

为后续中心化日志服务预留的 gRPC Sink，目前为 stub 实现：

- 内存缓冲，批量大小默认 100 条
- 预留 `_flush()` 方法，接入时替换为真实 gRPC client
- 需配套定义 `.proto` 文件、生成 stub、加入断路器与重试

---

## 4. CostTracker — Token 消耗与费用统计

**文件**：`cost_tracker.py`

### 设计原则

- **单一 `trace_id`**：会议开始时生成，等于 `runner_session_id`，贯穿整个会议生命周期内的每一次调用
- **扁平 Schema**：`CostRecord` 是一条原子记录，四个聚合层级（meeting / node / tool / call）都是对同一张扁平表的 `GROUP BY`
- **与 `CallTrace`/`LLMCallRecord` 互补**：后者记录 LLM 调用的详细 prompt/completion 文本，CostTracker 提供**所有调用（LLM + 工具）的统一成本视图**
- **后台异步刷盘**：记录先入内存，由后台 asyncio Task 批量写入数据库，不阻塞主流程

### CostRecord 字段

| 字段 | 说明 |
|---|---|
| `trace_id` | 等于 `runner_session_id`，贯穿会议 |
| `meeting_id` | 所属会议 |
| `request_id` | HTTP 请求 ID |
| `agent_role` | 发起调用的 Agent 角色（pm/tech/...） |
| `node` | pipeline 阶段（`clarify` / `intra_team` / `cross_team` / `evidence_check` / `arbitrate` / `produce`） |
| `tool_name` | `llm` / `web_search` / `browser.goto` / `browser.click` / ... |
| `cost_usd` | 估算成本（美元） |
| `input_tokens` / `output_tokens` / `total_tokens` | Token 计数（仅 LLM 有值） |
| `latency_ms` | 调用延迟 |
| `status` | `ok` / `error` / `fallback` |
| `extra` | 扩展字段（模型名、provider 等） |

### LLM 定价表

模块内置 `_LLM_PRICING` 字典（每百万 tokens 美元），覆盖主流模型：

- `gpt-4o` / `gpt-4o-mini` / `gpt-4-turbo`
- `deepseek-chat` / `deepseek-reasoner`
- `_default` 兜底（未知模型）

通过 `estimate_llm_cost(model, input_tokens, output_tokens) -> float` 函数估算单次调用成本。

### 公共 API

```python
from app.observability import get_cost_tracker, CostRecord

tracker = get_cost_tracker()
await tracker.record(CostRecord(
    node="intra_team",
    tool_name="llm",
    agent_role="tech",
    input_tokens=1200, output_tokens=300,
    cost_usd=estimate_llm_cost("deepseek-chat", 1200, 300),
    latency_ms=2400,
    status="ok",
))
```

### 聚合维度

- **会议维度**：`GROUP BY trace_id` — 单次会议总成本
- **节点维度**：`GROUP BY trace_id, node` — 各 pipeline 阶段成本
- **工具维度**：`GROUP BY trace_id, tool_name` — LLM vs 工具成本对比
- **角色维度**：`GROUP BY trace_id, agent_role` — 各 Agent 消耗占比
- **调用维度**：单条记录即一次调用详情

---

## 5. MetricsStore — 环形缓冲区指标存储

**文件**：`metrics_store.py`

### 设计

- **进程级单例**：模块导入后启动一个后台 `asyncio.Task`，每 10 秒采集一次系统指标
- **环形缓冲区**：`collections.deque(maxlen=360)`，默认保留最近 360 个数据点（10 秒 × 360 = **60 分钟**历史）
- **零依赖采集**：CPU / 内存通过 `psutil`（若可用），业务指标从内部计数器读取
- **前端轮询读取**：通过 `GET /metrics`（最新快照）和 `GET /metrics/history`（全量历史）两个 HTTP 端点暴露

### 可配置参数（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `METRICS_BUFFER_SIZE` | `360` | 缓冲区大小（点数） |
| `METRICS_COLLECTION_INTERVAL` | `10` | 采集间隔（秒） |

### MetricPoint 字段

```python
@dataclass
class MetricPoint:
    timestamp: float           # Unix 时间戳
    cpu_percent: float         # CPU 使用率 %
    memory_mb: float           # 进程内存 MB
    memory_percent: float      # 内存使用率 %
    total_tokens: int          # 累计 Token 消耗
    total_cost_usd: float      # 累计费用 USD
    api_requests_total: int    # 累计 API 请求数
    api_requests_per_minute: float  # 每分钟请求数
    avg_latency_ms: float      # 最近 100 次请求平均延迟
    active_meetings: int       # 活跃会议数
    browser_contexts: int      # 浏览器上下文数
```

### 公共方法

```python
from app.observability.metrics_store import get_metrics_store

store = get_metrics_store()
store.record_request(latency_ms=120)   # 中间件中每次 API 请求后调用
latest = store.latest()                # 最新一个点
history = store.history()              # 全部历史（用于图表）
snap = store.snapshot()                # 完整快照（uptime、QPS 等派生指标）
```

---

## 6. AuditLogger — 审计日志

**文件**：`audit.py`

### 用途

1. **实时问题定位**：追踪事件流向、错误上下文
2. **安全审计**：谁在什么时候做了什么
3. **行为分析**：用户操作路径、功能使用频率
4. **合规审计**：完整操作链路可追溯

### 持久化

审计事件写入 PostgreSQL `audit_logs` 表，ORM 模型位于 `app/db/models/observability.py`。M1.7 版本已从 SQLite（`audit.db`）迁移到 PostgreSQL。

### 设计要点

- **同步接口**：`log(category, action, ...)` 保持同步，因为调用点分布在中间件/路由/事件总线，改成 async 波及面太大
- **后台线程 + 独立事件循环**：内部启动专用线程跑 asyncio 事件循环，执行异步 PG 写入
- **内存缓冲 + 批量 flush**：默认每 2 秒批量刷盘一次；缓冲有上限防止 OOM
- **故障隔离**：写入失败不阻塞业务主流程

### 审计事件分类（AUDIT_CATEGORIES）

| 类别前缀 | 示例事件 | 分类 |
|---|---|---|
| `auth.*` | `auth.login` / `auth.logout` / `auth.login_failed` / `auth.token_refresh` | 认证 |
| `meeting.*` | `meeting.created` / `meeting.started` / `meeting.paused` / `meeting.aborted` / `meeting.deleted` / `meeting.viewed` | 会议生命周期 |
| `meeting.*`（控制） | `meeting.intervened` / `meeting.borrow_requested` / `meeting.borrow_approved` / `meeting.borrow_rejected` / `meeting.stage_changed` | 会议控制 |
| `sandbox.*` | `sandbox.command_executed` / `sandbox.service_deployed` / `sandbox.service_stopped` / `sandbox.file_read` / `sandbox.file_write` | 沙箱/部署 |
| `admin.*` | `admin.user_created` / `admin.user_deleted` / `admin.config_changed` / `admin.key_saved` | 系统管理 |
| `security.*` | `security.rate_limited` / `security.unauthorized_access` / `security.ssrf_blocked` / `security.sandbox_escape_attempt` / `security.path_traversal_blocked` | 安全事件 |
| `system.*` | `system.error` / `system.ws_connected` / `system.ws_disconnected` / `system.llm_error` / `system.llm_circuit_tripped` | 系统事件 |

### 使用方式

```python
from app.observability.audit import audit

audit.log("auth.login", "用户登录成功", extra={"provider": "password"})
audit.log("security.ssrf_blocked", "拦截 SSRF 尝试", extra={"target_url": url, "ip": client_ip})
audit.log("meeting.created", "会议创建", extra={"meeting_id": mid, "mode": mode})
```

---

## 7. 日志级别与着色

### 四个标准级别

| 级别 | 数值 | 用途 | ConsoleSink | EventBusSink | 自动旁路到 log_bus（通过 logger.py） |
|---|---|---|---|---|---|
| `ERROR` | 3 | 错误、异常、熔断 | 输出 | 推送 | 是 |
| `WARNING` | 2 | 降级、重试、非致命异常 | 输出 | 推送 | 是（最低级别） |
| `INFO` | 1 | 关键业务事件、阶段切换 | 输出 | 推送 | 否（仅写 Python logging） |
| `DEBUG` | 0 | 调试细节、中间状态 | 输出 | **不推送** | 否 |

### 着色策略

本模块**后端不做 ANSI 终端着色**，原因：

1. 容器化部署下 stdout 被 Docker / k8s 采集，ANSI 转义码会污染结构化日志解析
2. JSONFileSink 需要干净 JSON，不能混杂颜色码
3. 不同终端（Windows Terminal / iTerm2 / VSCode）颜色支持不一致

**着色在消费端完成**：

- **前端实时日志面板**：根据 `level` 字段应用颜色（ERROR 红 / WARNING 黄 / INFO 蓝 / DEBUG 灰），这是主要的彩色日志视图
- **外部日志工具**（Loki/ELK/Grafana）：在查询面板配置字段着色规则
- **本地开发**：可通过 `grep` + 终端主题，或 pipe 到 `lnav` / `jq` 等工具高亮

---

## 8. 统一门面 — logger.py

**文件**：`logger.py`

为消除项目中 `logging.getLogger(__name__)` / `log_bus.xxx()` / `audit()` 三种日志写法并存的分歧，`logger.py` 提供统一门面：

- `get_logger(__name__)` 返回标准 Python `logging.Logger`，兼容现有代码
- 自动从 `contextvars` 注入 `request_id` / `meeting_id` / `tenant_id` / `user_id` / `agent_role` / `runner_session_id` 到 `extra`
- `WARNING` 及以上自动旁路到 `log_bus`，INFO/DEBUG 仅走标准 logging，避免日志量爆炸
- 审计事件（auth/权限/敏感操作）仍走 `app.observability.audit`，不合并

```python
from app.observability.logger import get_logger

logger = get_logger(__name__)
logger.info("阶段完成", extra={"stage": "clarify", "duration_ms": 123})
logger.warning("LLM 调用失败", extra={"provider": "siliconflow", "attempt": 2})
logger.error("未处理异常", exc_info=True)
```

---

## 9. 关键文件索引

| 文件 | 职责 | 对外主要符号 |
|---|---|---|
| `__init__.py` | 模块导出入口 | `LogBus`, `log_bus`, `CostTracker`, `CostRecord`, `get_cost_tracker`, `estimate_llm_cost`, `ConsoleSink`, `JSONFileSink`, `RemoteGRPCSink` |
| `log_bus.py` | 结构化日志总线（单例） | `LogBus`, `log_bus` |
| `sinks.py` | 日志输出端实现 | `ConsoleSink`, `JSONFileSink`, `EventBusSink`, `RemoteGRPCSink` |
| `cost_tracker.py` | LLM/工具调用成本追踪 | `CostTracker`, `CostRecord`, `estimate_llm_cost`, `get_cost_tracker`, `reset_cost_tracker` |
| `metrics_store.py` | 系统/业务指标环形缓冲 | `MetricsStore`, `MetricPoint`, `get_metrics_store` |
| `audit.py` | 审计日志（PG 持久化） | `audit`, `AuditLogger`, `AUDIT_CATEGORIES` |
| `logger.py` | 统一日志门面 | `get_logger` |

---

## 10. 前端集成

### 10.1 实时日志面板

- **传输通道**：WebSocket（事件总线 `bus.publish()`）
- **事件类型**：`log.entry`
- **触发条件**：业务代码调用 `log_bus.info/warning/error` → EventBusSink 过滤后推送
- **Payload**：
  ```json
  {
    "level": "INFO",
    "logger": "app.agents.intra_team",
    "message": "技术主管开始分析需求",
    "timestamp": "2026-07-24T10:00:00+00:00",
    "agent_role": "tech",
    "stage": "intra_team"
  }
  ```
- **前端渲染**：按 `level` 着色（ERROR 红 / WARNING 黄 / INFO 蓝 / DEBUG 灰），按 `timestamp` 倒序追加，支持按 `agent_role` / `stage` 过滤

### 10.2 运维指标仪表盘

- **API 端点**：
  - `GET /metrics` — 最新快照（CPU、内存、QPS、平均延迟、活跃会议数、累计 Token/费用）
  - `GET /metrics/history` — 60 分钟历史曲线（用于折线图）
- **调用方式**：前端仪表盘页面每 10 秒轮询一次 `/metrics`，历史数据进入页面时一次性拉取
- **典型图表**：CPU/内存趋势、QPS 曲线、P50/P95 延迟、累计成本曲线、活跃会议数

### 10.3 成本统计面板（基于 CostTracker）

成本数据通过会议相关 API 聚合查询，按 trace_id 聚合后返回：

- 单次会议总成本、各 Agent 占比饼图
- 各 pipeline 阶段成本柱状图
- Token 消耗趋势（随会议进行实时累加）

---

## 11. 扩展指南

### 11.1 添加自定义日志 Sink

实现一个包含 `write(event: dict) -> None` 方法的类即可：

```python
# my_sink.py
from typing import Any

class AlertSink:
    """ERROR 级别日志推送到告警系统（飞书/钉钉/邮件）"""

    def write(self, event: dict[str, Any]) -> None:
        if event.get("level") != "ERROR":
            return
        try:
            # 调用告警 webhook（注意：不要阻塞，建议丢到队列或用 asyncio.create_task）
            self._send_alert(event)
        except Exception:
            pass  # sink 异常必须静默，不能影响主流程

    def _send_alert(self, event: dict[str, Any]) -> None:
        ...
```

注册到 LogBus：

```python
from app.observability.log_bus import log_bus
from my_sink import AlertSink

log_bus.add_sink(AlertSink())
```

**Slink 实现约束**：

1. `write()` 必须线程安全（可能被多个线程同时调用）
2. 内部必须捕获所有异常，禁止向上抛出
3. 阻塞操作（网络 IO、磁盘 IO）应异步化或丢到后台线程，避免阻塞日志调用点
4. 大字段 extra 不要原样转发到外部系统，建议先做字段裁剪

### 11.2 添加自定义指标

在 `MetricPoint` dataclass 中增加字段，并在 `MetricsStore._collect()` 方法中补充采集逻辑：

```python
# 1. 在 MetricPoint 中加字段
@dataclass
class MetricPoint:
    ...
    queue_depth: int = 0  # 新增：某队列深度

# 2. 在 _collect() 中赋值
async def _collect(self):
    while True:
        point = MetricPoint(
            ...
            queue_depth=my_queue.qsize(),
        )
        self._buffer.append(point)
        await asyncio.sleep(_COLLECTION_INTERVAL)

# 3. 在 snapshot() 中加入返回值（供 /metrics API 输出）
def snapshot(self):
    return {
        ...
        "queue_depth": latest.queue_depth if latest else 0,
    }
```

**指标设计原则**：

- 指标应是**可加的 / 可聚合的**数值，避免在指标点里塞大对象
- 高基数标签（如 meeting_id、user_id）不要放进 MetricPoint，应走日志/审计
- 采集间隔默认 10 秒，新指标的采集成本必须远低于此
- 派生指标（QPS、平均延迟）在 `snapshot()` 中计算，不要在每次 `_collect()` 里算

### 11.3 添加新的审计事件类别

在 `audit.py` 的 `AUDIT_CATEGORIES` 字典中注册新事件类型：

```python
AUDIT_CATEGORIES = {
    ...
    "plugin.installed":   "插件",
    "plugin.uninstalled": "插件",
}
```

然后在业务代码中调用：

```python
audit.log("plugin.installed", "插件安装成功", extra={"plugin_id": pid, "version": v})
```

新增持久化字段时，需要同步：
1. `audit_logs` 表 DDL（`app/dao/db_init.py`）
2. ORM 模型（`app/db/models/observability.py`）
3. Alembic 迁移脚本（若项目启用）

---

## 12. 环境变量速查

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_ENV` | — | `test` 环境下默认不启用 JSONFileSink |
| `CONCLAVE_LOG_DIR` | `/app/data/logs` | JSON 日志目录（非 test 环境默认写入 `conclave.jsonl`） |
| `CONCLAVE_LOG_JSON_FILE` | （空） | 显式指定 JSON 日志文件路径 |
| `METRICS_BUFFER_SIZE` | `360` | 指标缓冲区大小（点数） |
| `METRICS_COLLECTION_INTERVAL` | `10` | 指标采集间隔（秒） |
