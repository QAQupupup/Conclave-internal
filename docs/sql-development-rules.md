# SQL 开发守则（SQL Development Rules）

> 本文是指引 Conclave 项目所有数据库操作开发的**强制守则**，AI 助手与人类开发者同此约束。
> 读写任何 DB 代码、改 ORM 模型、写查询/分页/批量写入/迁移前，先读本文件。
>
> 配套文档：`AGENTS.md`（实战纪律入口）、`docs/pitfalls.md` P5-P10（数据库踩坑）、
> `backend/app/db/README.md`（数据层架构）、`backend/app/db/schema_verify.py`（schema 一致性校验）。

---

## 0. 标签体系

每条规则标注一个级别标签，含义如下。同一规则可能同时有多个标签（如"红线 + 警告"）。

| 标签 | 含义 | 违反后果 |
|---|---|---|
| 【绝对禁止】 | 违反即 Bug 或安全事故 | CI / Code Review 直接拦截 |
| 【红线】 | 默认禁止，仅白名单场景可豁免 | 豁免必须注释理由 |
| 【警告】 | 允许，但需注意边界条件 | 不豁免，只提醒 |
| 【倾向】 | 默认优先选这个做法 | 有更优理由可替换 |
| 【建议】 | 优化项，按需启用 | 不强制 |

每条规则固定带三要素：**为什么不用 / 风险点 / 何时才可用**。

---

## 1. 模型定义（Entity）

### 1.1 统一 SQLAlchemy 2.0 async ORM【倾向】【红线】

- **为什么**：ORM 的参数绑定天然防 SQL 注入；单源真相（模型即 schema）；类型安全 + 可读性。
- **风险点**：极端性能场景不如手写 SQL 灵活，但本项目的查询量级远未到需要手写优化的程度。
- **何时才可用原生 SQL**：见 §6 白名单，其余一律 ORM。

所有数据库访问必须经 `AsyncSession` + `select()/insert()/update()/delete()`。**禁止**在业务层直接 `text()`（原生 SQL 兜底见 §6）。

```python
# 正确
async with async_session_factory() as session:
    result = await session.execute(select(MeetingModel).where(MeetingModel.id == meeting_id))
    meeting = result.scalar_one_or_none()

# 错误——业务层裸 text()
row = await session.execute(text("SELECT * FROM meetings WHERE id = :id"), {"id": meeting_id})
```

### 1.2 禁用 relationship【红线】

- **为什么**：`relationship` 是隐式惰性加载的根源——业务代码一访问 `meeting.tags` 就悄悄发一条 SQL，调用方无感知，极易 N+1；JSON 序列化时会触发 lazy load 或无限递归。
- **风险点**：不用 relationship 需要手写 join，代码略多，但查询成本变得**显式可见可控**。
- **何时才可用**：**永远不用**。跨表关联一律显式 `join` / 左连接（见 §2.2）。

**处置约定（已存在的历史 relationship，遵循"先注释不删除"）**：

- `MeetingModel.messages / events / tags`、`MessageModel.meeting`、`EventModel.meeting`、`DocumentModel.meeting` 等已有 `relationship` 声明，**注释掉、不删除**，且 `back_populates` 必须**成对一起注释**，否则 SQLAlchemy mapper 配置会因找不到对面报错。
- 新增模型**一律不写** `relationship` / `back_populates`。
- 外键约束仍保留（`ForeignKey`），这是数据库层完整性，与 ORM 关系对象是两回事。

### 1.3 模型是唯一的 schema 真相【红线】

- **为什么**：项目历史上同时存在 ORM 模型 + `db_init.py` 手写 DDL 两套 schema，字段改了要同步两处，易漂移。
- **风险点**：双源漂移会导致"ORM 声明了列但 DB 不存在"或类型不匹配，运行期才爆。
- **现状**：双源已取消——`db_init.py` 手写 DDL 2026-08 废弃、2026-09 文件删除。模型是唯一 schema 真相，改表结构只能走 Alembic 迁移（见 §5），禁止手写 CREATE TABLE。

`db/models/` 里的 `MeetingModel`、`MessageModel`、`EventModel` 等 15 张表模型已齐全，DAO 层必须使用它们，而非当前 `dao/` 下 `text()` 手写 SQL 的模式。

---

## 2. 查询（Query）

### 2.1 禁止 SELECT *【绝对禁止】

- **为什么**：列膨胀、无法命中覆盖索引、前端契约不稳定、传输浪费。
- **风险点**：`SELECT *` 拿回来的列数/顺序随表结构漂移，隐式依赖列顺序的代码会静默错位。
- **何时才可用**：**永远不用**。ORML 下 `select(MeetingModel)` 是安全等价（列由模型显式声明，不是通配符）；但若只取部分列，必须 `select(MeetingModel.id, MeetingModel.topic)` 显式列出。

### 2.2 禁止大表 join 大表【红线】

- **为什么**：大表笛卡尔积/全连接导致内存溢出、慢查询、锁表。
- **风险点**：两个大表 join 即使有索引，中间结果集也可能爆炸。
- **何时才可用**：大表关联必须先**过滤后 join**（子查询先截断数据量），或改用 `EXISTS`/`IN` 子查询替代 join。小表 join 小表、小表 join 大表（带索引）允许。

```python
# 正确——子查询先过滤大表，再 join
sub = (
    select(MessageModel.id)
    .where(MessageModel.meeting_id == meeting_id)
    .order_by(MessageModel.created_at.desc())
    .limit(100)
    .subquery()
)
stmt = select(MessageModel).join(sub, MessageModel.id == sub.c.id)

# 正确——用 exists 替代 join
stmt = select(MeetingModel).where(
    exists().where(MessageModel.meeting_id == MeetingModel.id)
)
```

### 2.3 禁止 ALL 全量关联 / 全量匹配【红线】

- **为什么**：`ALL` 子查询、无谓词的全表扫描/全量 `in_()` 会把整个结果集拉回内存逐条比对。
- **风险点**：数据量增长后从"慢"变成"OOM"。
- **何时才可用**：聚合/统计必须全扫时改用数据库端 `count()`/`sum()`/窗口函数下推，而非 Python 循环。

### 2.4 空间换时间：查询与计算下推数据库【倾向】

- **为什么**：把过滤、join、分组、聚合、排序都交给数据库，减少网络往返和 Python 计算，还能利用索引。
- **风险点**：过重的单条 SQL 会让 DB 变瓶颈；极端复杂逻辑才考虑拆到应用层。
- **何时才可用**：默认下推。只有"数据库算不动、应用算更快"（如需要业务规则判断的复杂计算）才提回应用层，且需注释原因。

### 2.5 窗口函数【建议】

- **为什么**：`func.row_number().over()`、`func.rank()`、`func.sum(...).over()` 一条 SQL 搞定"每组 TopN / 排名 / 累计"，替代低效的 Python 循环。
- **风险点**：无需求场景时引入是过度设计。
- **何时才可用**：**当前无场景，先不用**。出现"每组取前 N""排名""累计占比"等需求时再启用，并列入 §6 原生 SQL 白名单（窗口函数 ORM 表达较繁琐）。

---

## 3. 写入（Write）

### 3.1 批量插入分批【红线】

- **为什么**：一次性提交大事务会导致 binlog 过大、数据库主线程阻塞、行级锁竞争与幻读，影响并发查询。
- **风险点**：单条 `INSERT ... VALUES (...), (...), ...` 过大，或一个事务内 `add_all` 几十万行。
- **何时才可用**：**默认每批 ≤ 1000 行**（对齐 PostgreSQL 常用批量阈值），分批提交；跨批共用一个会话但每批独立 `commit`。

```python
# 正确——分批
BATCH = 1000
for i in range(0, len(rows), BATCH):
    chunk = rows[i : i + BATCH]
    await session.execute(
        insert(MeetingTagModel).values(chunk)  # 多行 VALUES，一批 1000
    )
    await session.commit()
```

### 3.2 禁止一次性提交超大事务【绝对禁止】

- **为什么**：同上 3.1，是它的极端形态——超大事务锁持有时间过长，阻塞其他写入，甚至触发主从延迟。
- **风险点**：与 3.1 的差异在于"一个事务包裹了多批 insert 或一个 commit 提交了全部数据"。
- **何时才可用**：**永远不做**。任何"全量重建 / 全量导入"操作必须分批提交，并考虑 `COPY` 或 pg 方言批量接口。

### 3.3 Upsert 用 PostgreSQL 方言【倾向】

- **为什么**：`sqlalchemy.dialects.postgresql.insert(...).on_conflict_do_update()` / `on_conflict_do_nothing()` 是类型安全、可读的 upsert，避免手写 `ON CONFLICT` 字符串。
- **风险点**：需指定 `index_elements` + `set_` 明确冲突键与更新列。
- **何时才可用**：所有 upsert 场景默认用它，不用 `text("INSERT ... ON CONFLICT ...")`。

```python
from sqlalchemy.dialects.postgresql import insert as pg_insert

stmt = pg_insert(MeetingModel).values(*rows)
stmt = stmt.on_conflict_do_update(
    index_elements=[MeetingModel.id],
    set_={col: stmt.excluded[col] for col in ("topic", "status", "stage", "payload")},
)
await session.execute(stmt)
```

### 3.4 禁止 f-string 拼 SQL【绝对禁止】

- **为什么**：`f"INSERT INTO meetings ({col_list}) ..."` 是注入面，且字段名拼错静默失败。
- **风险点**：即使列名当前是内部常量，未来一旦混入外部输入即变注入漏洞（`--` 注释截断、`;` 拼接）。
- **何时才可用**：**永远不用**。ORM 的列对象 + 参数绑定天然规避。原生 SQL 兜底也必须 `text()` + 命名参数绑定（见 §6），绝不用字符串拼接。

> 现存的 `backend/app/dao/meeting_dao.py:75` `sql = f"INSERT INTO meetings ({col_list})..."` 是反例，全量迁移时必须改掉。

---

## 4. 分页（Pagination）

### 4.1 keyset / seek 分页优先【倾向】

- **为什么**：`OFFSET` 越深越慢（数据库要扫过并丢弃前面所有行）；keyset 用 `WHERE id > :last_id` 直接定位，深度稳定 O(1)。
- **风险点**：keyset 依赖有单调递增的排序键（如自增 id / 时间戳 + id 复合）。
- **何时才可用**：默认优先。只有"随机跳页"这类确实无法 keyset 的场景才用 OFFSET。

### 4.2 未传 last_id 时回退 page/size【倾向】

- **为什么**：首屏没有 last_id 游标，只能用页码定位；翻页后从结果里取游标继续 keyset。
- **风险点**：两条路径要统一返回结构，避免上层感知差异。
- **何时才可用**：标准做法。

### 4.3 取 last_id：逻辑中分别查询，不改子查询【倾向】

- **为什么**：子查询取 `last_id` 让单条 SQL 复杂化，且 PostgreSQL 对 OFFSET 子查询优化差；逻辑中"首页按 page/size 查 → 从结果取最后一条 id → 作为下次 last_id"更清晰可控。
- **风险点**：多一次应用层取游标，但代价可忽略。
- **何时才可用**：固定采用逻辑分别查询，不做子查询取游标。

```python
# 翻页范式
async def list_messages_paged(meeting_id, page, size, last_id=None):
    stmt = select(MessageModel).where(MessageModel.meeting_id == meeting_id)
    if last_id is not None:
        stmt = stmt.where(MessageModel.id > last_id)  # keyset
    else:
        stmt = stmt.offset((page - 1) * size)  # 首屏回退 offset
    stmt = stmt.order_by(MessageModel.id).limit(size)
    rows = (await session.execute(stmt)).scalars().all()
    return rows, rows[-1].id if rows else last_id  # 返回供下次 last_id
```

---

## 5. 迁移（Migration）

### 5.1 用 Alembic 增量迁移，取消手写 DDL【红线】

- **为什么**：`db_init.py` 的 `CREATE TABLE IF NOT EXISTS` 无法处理列变更、回滚，`IF NOT EXISTS` 会静默跳过已存在表的字段漂移。
- **风险点**：双源 DDL 漂移（见 §1.3）。
- **何时才可用**：**任何表结构变更只能走 Alembic**。项目已具备 `backend/alembic/env.py` + `versions/`（0001-0006），`compare_type=True` + `compare_server_default=True` 已开启，改模型后：

```bash
# 生成增量迁移（容器内或按 AGENTS.md 规定的方式）
alembic revision --autogenerate -m "描述"
alembic upgrade head
```

### 5.2 合法迁移【红线】

- 新增列：区分 `nullable=True`（可回填）与 `nullable=False`（必须给 `server_default`，否则已有行加列失败）。
- 删列/改类型：先评估是否破坏已有数据，迁移脚本需含回滚思路（downgrade 分支）。
- 迁移脚本**必须人工 review** `autogenerate` 的 diff，不能盲跑——`autogenerate` 对改名/类型变化可能误判。

### 5.3 legacy 表纳入迁移轨道【红线】（2026-08 已完成）

- **为什么**：`schema_verify.py` 的 `_LEGACY_RAW_TABLES` 曾把 `meetings/messages/events` 等白名单跳出了 schema 校验，这些表靠 `db_init.py` 手写 DDL 建表，是双源漂移的重灾区。
- **完成状态**（2026-08）：`meetings/messages/events/user_preferences/meeting_tags/agent_roles/meeting_aux` 等核心表已迁移到 ORM 模型并移出白名单；`db_init.py` 手写 DDL 已废弃，文件已于 2026-09 删除（no-op `init_db()` 及全部调用点一并移除）。白名单现仅保留确无 ORM 模型的表（`net_auth_requests`/`notifications`/`alembic_version`/`casbin_rule` 等，以 `app/db/schema_verify.py` 为准）。
- **残留红线**：新增表优先走 ORM + `create_all()`/Alembic 轨道，**不得**再往 `_LEGACY_RAW_TABLES` 白名单加新条目。

---

## 6. 原生 SQL 例外清单（何时才可用原生 SQL）

> 前提：ORM 是默认。只有以下白名单场景，且性能/表达能力确实受限时，才允许 `text()`。

### 6.1 白名单场景

| 场景 | 说明 |
|---|---|
| 窗口函数 | `ROW_NUMBER() OVER (...)` 等，ORM `func.*.over()` 表达繁琐时可原生 |
| 递归 CTE | `WITH RECURSIVE` 树/图查询 |
| 复杂报表聚合 | 多表聚合、明细+汇总混合，ORM 拼装代价高 |
| pg 方言专属 | 如 `INSERT ... ON CONFLICT`（但更优先用 §3.3 的 pg_insert 方言，不算裸 SQL）、`COPY` 批量导入 |

### 6.2 原生 SQL 硬约束【红线 + 绝对禁止】

- 【绝对禁止】字符串拼接 SQL（f-string、`+`、`%` 格式化）。一律 `text()` + 命名参数绑定。
- 【绝对禁止】直接拼接用户/外部输入到 SQL 任何位置（值、列名、表名、`ORDER BY` 字段）。动态列名/排序字段必须**白名单映射**到已知列对象，不接受任意字符串。
- 【红线】警惕注入向量：`--` 注释截断、`;` 多语句、`'` 引号闭合、`OR 1=1`、UNION 注入。命名参数绑定能让这些失效，前提是**不手动拼字符串**。

```python
# 正确——命名参数绑定
stmt = text("SELECT id, topic FROM meetings WHERE id = :id AND status = :status")
await session.execute(stmt, {"id": meeting_id, "status": status})

# 错误——把外部值拼进 SQL
stmt = text(f"SELECT * FROM meetings WHERE id = '{meeting_id}'")  # 注入风险，禁止
```

### 6.3 为什么这些规则存在（一句话）

关系数据库的"健壮性"取决于三件事：**查询代价显式可见**（禁 relationship / SELECT *）、**写入不阻塞并发**（分批）、**绝不信任输入**（禁拼接 + 参数绑定）。守则里每条禁项背后都是项目里真实踩过或潜在会踩的坑，不是教条。

---

> 本文与 `AGENTS.md` §4「数据库/ORM」类别、`docs/pitfalls.md` P5-P10 配套阅读。
> 新增数据库踩坑，追加到 `docs/pitfalls.md` 对应类别；新增 SQL 开发规则，追加到本文并同步更新 `AGENTS.md` 索引。