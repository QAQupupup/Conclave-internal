[返回上级文档](../../README.md)

# DB 模块 — 数据层

数据持久化层，统一管理 SQLAlchemy 异步引擎、ORM 模型、Redis 缓存与向量存储抽象。业务代码通过本模块提供的工厂函数和抽象接口访问底层存储，不直接耦合具体实现。

---

## 模块职责

| 子系统 | 职责 |
|---|---|
| 异步引擎 | PostgreSQL 连接池管理、循环感知单例、跨测试循环自动重建 |
| ORM 模型 | 14 张业务表的 SQLAlchemy 声明式映射，用于 Alembic 迁移与只读查询 |
| Redis 客户端 | 异步 Redis 连接池，用于缓存、Pub/Sub、会话数据 |
| 向量存储 | `VectorStore` 抽象接口 + Qdrant 实现，面向 RAG 场景的向量检索 |

---

## Engine（异步引擎）

文件：`engine.py`

- 仅支持 PostgreSQL 后端，连接串由 `settings.database_url` 配置
- 连接池参数：`pool_size=10`、`max_overflow=20`、`pool_pre_ping=True`、`pool_recycle=3600`
- **循环感知单例**：`_ensure_engine()` 在首次调用或事件循环切换/关闭时自动重建引擎
  - 使用 `threading.Lock` 做 double-check 防止并发重建
  - 旧引擎直接丢弃引用由 GC 回收，不在同步代码中调用 `engine.dispose()`（避免跨循环报错）
  - 生产环境只有一个事件循环不会触发重建；测试场景（多次 `asyncio.run()`）依赖此机制

```python
from app.db.engine import async_session_factory

async with async_session_factory() as session:
    result = await session.execute(...)
```

### asyncio 原语使用规范（重要）

> 依据 AGENTS.md §4.1：**模块级禁止直接实例化 `asyncio.Lock()` / `Semaphore()` / `Event()` / `Queue()`**。
>
> 这些原语在创建时绑定到第一个事件循环，测试场景中循环变化后会抛出 `RuntimeError: ... got Future <Future ...> attached to a different loop`。
>
> 必须使用 `app/lazy_asyncio.py` 提供的 `LazyLock` / `LazySemaphore`，它们在首次访问时绑定当前循环、循环变化时自动重建。

---

## ORM 基类与 Mixin

文件：`base.py`

所有 ORM 模型继承自 `Base`（`DeclarativeBase`），公共字段通过 Mixin 复用：

| Mixin | 提供字段 | 用途 |
|---|---|---|
| `UUIDPrimaryKeyMixin` | `id: String(36)` 主键，默认 `uuid4()` | 大部分业务表 |
| `IntegerPrimaryKeyMixin` | `id: Integer` 自增主键 | 租户表等需要整数 ID 的场景 |
| `CreatedAtMixin` | `created_at: DateTime(timezone=True)` | 不可变记录（events、messages、tags） |
| `UpdatedAtMixin` | `updated_at: DateTime(timezone=True)`，带 `onupdate=utcnow` | 配置/画像类表 |
| `TimestampMixin` | `created_at` + `updated_at` | 标准双时间戳 |
| `TenantScopeMixin` | `tenant_id: Integer`，`nullable=True`，带索引 | 多租户隔离字段 |

### ForeignKey 陷阱（AGENTS.md §4.12）

对于由 raw SQL 创建的表（如 `tenants`、插件管理表），**不要**在 ORM 模型中声明 `ForeignKey(...)`，否则 `Base.metadata.create_all()` 会因找不到被引用表抛出 `NoReferencedTableError`。外键约束统一由 `app/tenants/service.py::ensure_business_tables_tenant_id()` 通过 raw SQL `ALTER TABLE ... ADD CONSTRAINT` 添加。

---

## ORM 模型一览

模型定义在 `models/` 子包，共 14 个模型，通过 `models/__init__.py` 统一 re-export，Alembic 通过 `from app.db.models import *` 注册到 metadata。

| 模型 | 文件 | 说明 |
|---|---|---|
| `AgentRoleModel` | `models/agent_role.py` | Agent 角色定义 |
| `DockerHostModel` | `models/docker_host.py` | Docker 远程主机配置 |
| `DockerHostSecretModel` | `models/docker_host.py` | Docker 主机密钥（加密存储） |
| `DocumentModel` | `models/document.py` | 上传文档元数据 |
| `EventModel` | `models/event.py` | 领域事件持久化记录 |
| `MeetingModel` | `models/meeting.py` | 会议主表 |
| `MeetingAuxModel` | `models/meeting.py` | 会议辅助数据 |
| `MeetingTagModel` | `models/meeting.py` | 会议标签关联 |
| `RawMemoryModel` | `models/memory.py` | 原始发言记忆 |
| `FeatureMemoryModel` | `models/memory.py` | 行为特征记忆 |
| `ProfileMemoryModel` | `models/memory.py` | 稳定画像记忆 |
| `MessageModel` | `models/message.py` | 会议消息 |
| `CostRecordModel` | `models/observability.py` | LLM 调用成本记录 |
| `ApiKeyModel` | `models/user.py` | API 密钥 |
| `UserPreferenceModel` | `models/user.py` | 用户偏好设置 |

---

## Redis 客户端

文件：`redis.py`

- 异步 Redis 客户端（`redis.asyncio`），在 FastAPI lifespan 阶段通过 `init_redis(app)` 初始化
- 连接池参数：`max_connections=20`、`socket_keepalive=True`、`socket_connect_timeout=5`
- **循环感知单例**：`_is_usable()` 检测当前循环是否匹配，循环变化时返回 `None` 让调用方降级
- Redis 不可用时不阻塞应用启动，`app.state.redis` 为 `None`，调用方需做降级处理
- 用途：事件总线 Pub/Sub、缓存、会话数据

```python
from app.db.redis import get_redis

redis = get_redis()
if redis:
    await redis.publish("channel", json.dumps(payload))
```

---

## 向量存储

### 抽象接口

文件：`vector_store.py`

`VectorStore`（ABC）定义向量检索标准契约，方法签名与 Qdrant 概念对齐但足够通用：

| 方法 | 说明 |
|---|---|
| `ensure_collection(name, vector_size)` | 确保集合存在，不存在则创建 |
| `upsert(collection, points)` | 批量写入向量点，points 格式：`[{"id", "vector", "payload"}]` |
| `search(collection, query_vector, limit, score_threshold, filter_conditions)` | 余弦相似度搜索，返回 `[{"id", "score", "payload"}]` |
| `delete(collection, point_ids)` | 删除指定向量点 |
| `collection_exists(name)` | 检查集合是否存在 |
| `count(collection)` | 返回集合中点数量 |

业务代码仅依赖此接口，不感知底层实现。未来可切换为 pgvector 或其他引擎。

### Qdrant 实现

文件：`qdrant_store.py`

- `QdrantVectorStore(VectorStore)`：对接 Qdrant 向量数据库
- 通过 `settings.qdrant_url` 连接，距离度量使用 `Distance.COSINE`
- 支持 payload 过滤（`FieldCondition` + `MatchValue`）
- 当前用于文档 chunk 向量检索与记忆检索

---

## 数据库迁移（Alembic）

- 迁移脚本目录：`backend/alembic/versions/`
- 迁移配置：`backend/alembic.ini` + `backend/alembic/env.py`
- 常用命令：
  - `alembic revision --autogenerate -m "描述"` — 生成迁移脚本
  - `alembic upgrade head` — 升级到最新版本
  - `alembic downgrade -1` — 回滚一个版本

注意（AGENTS.md §4.15）：`alembic/env.py` 中的 `from alembic import context` 是 Alembic 运行时注入的全局对象，不能直接 `python alembic/env.py` 运行，必须通过 `alembic` CLI 命令调用。

---

## 关键文件索引

| 文件 | 职责 |
|---|---|
| `__init__.py` | 模块说明与架构概览 |
| `engine.py` | 异步引擎 + `async_session_factory` 会话工厂 |
| `base.py` | ORM 基类 `Base` 与公共 Mixin（主键/时间戳/多租户） |
| `redis.py` | Redis 客户端初始化与循环感知单例 |
| `vector_store.py` | `VectorStore` 抽象基类（ABC） |
| `qdrant_store.py` | Qdrant 向量存储实现 |
| `models/__init__.py` | 模型统一 re-export（Alembic 入口） |
| `models/agent_role.py` | Agent 角色 ORM 模型 |
| `models/docker_host.py` | Docker 主机与密钥 ORM 模型 |
| `models/document.py` | 文档 ORM 模型 |
| `models/event.py` | 事件 ORM 模型 |
| `models/meeting.py` | 会议主表/辅助/标签 ORM 模型 |
| `models/memory.py` | 三层记忆 ORM 模型（Raw/Feature/Profile） |
| `models/message.py` | 消息 ORM 模型 |
| `models/observability.py` | 成本记录 ORM 模型 |
| `models/user.py` | API Key 与用户偏好 ORM 模型 |
