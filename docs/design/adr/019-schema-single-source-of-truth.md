# ADR-019: Schema 单一真相收敛（Alembic 全托管）

## 状态

Accepted — 2026-09-07

裁决记录（用户逐点裁决，3 项均采纳推荐项）：
- D1「Schema 应用器」→ 采纳 **Alembic 全托管**
- D2「迁移链处理」→ 采纳 **重生成完整基线**
- D3「原生建表函数」→ 采纳 **纳入 Alembic**

---

## 背景与问题

### 现状：schema 由三条轨道并行管理，零单一真相

本 ADR 撰写时经 grep/psql 逐项核验，建表实际由三条独立路径完成：

| 轨道 | 建了什么 | 事实（核验方式） |
|---|---|---|
| `Base.metadata.create_all()` | 全部 32 张 ORM 表 | `main.py` lifespan 与 `conftest.py` 均调用（`app/db/README.md` §「ORM 模型一览」列 14 模型，实际注册到 metadata 的表达到 32 张） |
| 原生 `ensure_*` 函数 | `users`（`app/auth::_init_users_table`）、`tenants` + 业务表 `tenant_id` 回填（`app/tenants/service.py::ensure_tenants_table` / `ensure_business_tables_tenant_id`）、`tenant_members`/`user_settings`/`system_settings`/`casbin_rule`（`app/rbac/migrations.py::ensure_rbac_tables`）、`net_auth_requests`（`app/net_auth::init_auth_table`） | `conftest.py` 步骤 1/3/3.5/3.6/5 显式调用 |
| Alembic 迁移 0001-0008 | 仅 **17 / 32** 张表（`op.create_table` 共 17 处） | `backend/alembic/versions/` 逐个 grep；`entrypoint.sh` 无 alembic、CI 无 alembic、`main.py` 不调 alembic → **从未被执行** |

### 政策声明与实际机制脱节

`docs/sql-development-rules.md` 已明文（§1.3、§5.1）：

> 「模型是唯一的 schema 真相」「改表结构只能走 Alembic」「任何表结构变更只能走 Alembic」。

但实际执行器是 `create_all` + 原生 `ensure_*`，Alembic 迁移链残缺且从不运行。文档说的是 A，代码做的是 B/C——这是本次事故的根。

### 触发本次修复的事故链

1. ADR-017 给 `MeetingModel` 新增 `project_id`/`issue_id` 列，只在迁移 0007/0008 里加了列；
2. `create_all()` 只建新表、**不给已有表加列**，且 Alembic 迁移从不自动执行；
3. dev 库的 `meetings` 表停留在旧结构，缺这两列；
4. 启动时 `recover_crashed_meetings` 按 ORM 模型 `SELECT` 带出这两列 → `column meetings.project_id does not exist` → 后端 unhealthy。

> 摸查中还发现更深漂移：旧 dev 库 `meetings` 的 `status`/`schema_version`/`created_at` 是 `text` 而非 ORM 的 `VARCHAR`/`integer`/`timestamptz`——这是 `db_init.py` 时代手写 DDL 的残留（`db_init.py` 已于 2026-09 删除）。

---

## 决策

| # | 决策 | 理由 | 被推翻的替代方案 |
|---|------|------|-----------------|
| D1 | **Alembic 成为唯一 schema 应用器**：启动执行 `alembic upgrade head` 建表/升级，从启动路径移除 `create_all` 建表 | 唯一真相满足版本化、可回滚、可 fail-fast，且对齐 SQL 守则 §5.1 既有声明 | 「维持 create_all + 人工迁移」——改动小但本次缺列事故根源仍在；「自造启动 diff 补列」——等于重造 Alembic |
| D2 | **重生成一条完整 baseline 迁移**，覆盖全部 32 张表 + 原生表，废弃残缺的 0001-0008 旧链 | 旧链只覆盖 17/32 表且从未执行，逐条补齐审计成本高、易遗漏 | 「逐条补齐旧链」——历史保留但易遗漏 |
| D3 | **原生 `ensure_*` 表纳入 Alembic**：转 ORM 模型或写入 baseline 迁移，启动不再跑这些建表逻辑 | 消除第二条建表路径，实现真单一真相 | 「保留原生幂等逻辑」——改动小但仍是第二条路径 |
| D4 | 测试 `conftest.py` 保留 `create_all` 快速建表 + TRUNCATE（不切 alembic） | 测试高频重建，`create_all` 更快；正确性由「baseline 迁移产物 == create_all 产物」不变式 + CI 卡点兜底 | 「测试也走 alembic」——一致但 conftest 重构大、每 worker 升级慢；推迟到 Phase 2 评估 |

---

## 分阶段实施

| Phase | 内容 | 验收标准 |
|---|---|---|
| **Phase 1（MVP）** | ① 重生成完整 baseline 迁移（含 32 ORM 表 + users/tenants/tenant_members/user_settings/system_settings/casbin_rule/net_auth_requests 等原生表 + `tenant_id` 回填等价 DDL）；② `main.py` 启动切为程序化 `alembic upgrade head`，移除 `create_all` 与原生 `ensure_*` 建表调用；③ 废弃旧 0001-0008（删除文件或 `down_revision=None` 的新链替代） | 空库跑 `alembic upgrade head` 得到 32 表，且 `schema_verify` 0 硬错误；`docker compose up -d --build` 后端 healthy |
| **Phase 2** | 评估并落地测试路径一致性：决定 `conftest` 保留 `create_all` 还是切 alembic；加 CI 卡点「空库 `alembic upgrade head` 产物 == `create_all` 产物」 | CI 新增 job 通过；测试套件在容器内 ruff+mypy+pytest 全绿 |
| **Phase 3** | 发布流程强制「模型变更必须带 migration」：pre-commit/pre-push 卡点 + CI 校验 ORM 元数据 vs Alembic head 无不匹配 | 模型改动但无对应迁移时 CI 红，阻断合并 |

---

## 风险评估

| 风险 | 影响 | 概率 | 缓解（护栏） |
|---|---|---|---|
| baseline 迁移漏表/漏列，`alembic upgrade head` 产物 ≠ `create_all` 产物 | 高——生产/空白环境缺表，运行期崩溃 | 中 | Phase 1 验收硬性要求「两者对齐 + schema_verify 0 硬错误」；Phase 2 CI 卡点持续兜底 |
| 原生 `ensure_*` 表转 ORM 时，raw SQL 依赖的 `ForeignKey` 语义丢失（README §「ForeignKey 陷阱」：raw SQL 表靠 `ensure_business_tables_tenant_id` 加外键） | 中——外键缺失、级联行为变化 | 中 | baseline 迁移内显式写出等价 `ADD CONSTRAINT ... FOREIGN KEY ... ON DELETE ...`，与现状 raw ALTER 逐条对照 |
| 程序化在 async lifespan 里跑 alembic（env.py 用 `asyncio.run`）触发事件循环冲突 | 高——启动卡死 | 中 | 复用 `env.py` 现有异步在线模式，或在线程/子进程中隔离执行；落进 Phase 1 实现，用 `docker compose up` 实测 |
| `notifications` 等按需建表模块（不在 32 表清单、在 `_LEGACY_RAW_TABLES` 白名单） | 低——首次使用时为空 | 低 | 保留其按需建表，纳入 schema_verify 白名单，暂不迁移 |

正确性判定：本 ADR 不涉及共享并发写或增量重建，属「单一真相收敛」而非「并发正确性」场景，故无需时序推演；核心正确性风险是「baseline 产物 == 现状 create_all 产物」这一不变式，已用 Phase 1 验收 + Phase 2 CI 双护栏把风险收敛为可检测。

---

## 工程红线

- [x] 新表带 `tenant_id` + DAO 多租户隔离（baseline 迁移中的原生表已被 `ensure_business_tables_tenant_id` 回填逻辑覆盖，迁移中保留等价 DDL）
- [x] 大产物只存 `content_ref` 指针——本 ADR 不新增业务表，只收敛既有 schema，不触碰字段语义
- [x] 与既有 ADR 一致性：不改变 ADR-002 JSONB metadata 扩展约定、ADR-012 检查点架构；仅替换「建表执行器」
- [x] 不得再往 `_LEGACY_RAW_TABLES` 白名单新增条目（SQL 守则 §5.3 残留红线）

---

## 测试策略

- 单元/集成：容器内一次性跑 `ruff check` + `mypy` + `pytest`（避免反复起容器），覆盖 `main.py` 启动路径与 `conftest` 建库路径不变式
- 专项：Phase 1 验收用空库 `alembic upgrade head` 后调 `verify_schema_consistency(raise_on_error=True)` 断言 0 硬错误
- 回归：`test_p0_regression.py` 涉及 DB 初始化的用例在切 alembic 后必须仍绿

---

## 定稿前验证清单

- [x] 每条事实性声明已 grep/psql 核验（P21）：三轨职责、17/32 表差、entrypoint 无 alembic、原生 ensure 函数位置与调用点
- [x] 三个可推翻点（D1/D2/D3）已获用户裁决并记录在状态节
- [x] 决策表编号连续 D1-D4，新增为追加
- [x] Phase 拆分含测试策略
- [x] 状态生命周期：Proposed → Accepted（附裁决记录）