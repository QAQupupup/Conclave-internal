# Conclave 高频踩坑清单（血泪教训）

> 本文件从 AGENTS.md §4 拆出，按类别分组。AGENTS.md 只保留类别索引和触发条件。
>
> 这些坑都踩过，每次出现都导致 CI 红或生产 Bug。**写代码时主动避开。**
>
> **篇幅纪律**：每条不超过 1.5KB。超出时将详细背景/修复历史拆到 `docs/retrospectives/` 或专门文档。

---

## 类别索引

| 类别 | 包含子节 | 何时读 |
|------|---------|--------|
| [异步/事件循环](#异步事件循环) | P1, P2 | 改 asyncio 代码、遇到事件循环报错 |
| [Docker/部署](#docker部署) | P3, P4 | 改 Dockerfile/compose、Playwright 依赖 |
| [数据库/ORM](#数据库orm) | P5, P6, P7, P8, P9, P10 | 改 ORM 模型、DDL、多租户、Alembic |
| [测试](#测试) | P11, P12, P13, P14, P27 | 写/改测试、fixture、断言 |
| [CI/Git](#cigit) | P15, P16, P17 | 提交、推送、hook 问题 |
| [编排器](#编排器) | P18, P19, P20 | 改 runner/nodes/门禁 |
| [文档质量](#文档质量) | P21, P22 | 写文档、回应代码审查 |
| [杂项](#杂项) | P23, P24, P25, P26 | 前端 TS/ESLint、import 取舍、Alembic env |
| [AI 助手文件操作纪律（PowerShell）](#ai-助手文件操作纪律powershell) | P28, P29 | 用 PowerShell 改记忆文件/vault 指针/配置等关键文件 |

---

## 异步/事件循环

### P1. asyncio 事件循环（最常见大坑）

**症状**：`RuntimeError: ... got Future <Future pending> attached to a different loop`、测试中 `new_context()` 挂死、引擎 dispose 报错。

**根因**：模块加载时创建的 `asyncio.Lock() / Semaphore() / Event() / Queue()` 会绑定到第一个事件循环，测试场景中 `asyncio.run()` 每次创建新循环，单例对象持有的原语绑定到旧循环。

**规则**：
1. **模块级禁止直接实例化 asyncio 原语**。必须用 `app/lazy_asyncio.py` 提供的 `LazyLock / LazySemaphore`，它们在首次访问时绑定当前循环、循环变化时自动重建。
2. **持有 asyncio 原语的单例（BrowserPool / PlaywrightWebSearch / Engine 等）getter 必须循环感知**：保存创建时的 loop 引用，`get()` 时检测 `loop.is_closed()` 或 `loop is not current_loop`，如是则重建。参考 `app/db/engine.py::_ensure_engine()`、`app/tools/playwright_search.py::get_playwright_search()`。
3. **不要在同步代码中调用 `asyncio.run(engine.dispose())` 去释放绑定到其他循环的引擎**。直接丢弃引用让 GC 回收即可。
4. **测试 fixture 必须重置单例**：在 `conftest.py` 的 fixture 中清理 browser_pool、playwright_search、network clients 等模块级单例，避免跨测试泄漏。

### P2. 事件总线 seq 顺序

**症状**：`test_e2e_full_meeting_with_logging` 断言 `seqs == sorted(seqs)` 失败，出现逆序如 39→38。

**根因**：`publish()` 中并发 `await save_event()` 虽然 DB 返回单调递增 seq，但协程恢复顺序受调度影响，`history.append(event)` 顺序与 seq 不一致。

**规则**：`history.append(event)` 之后必须 `history.sort(key=lambda e: e.seq)`。永远不要依赖 append 顺序。

---

## Docker/部署

### P3. Docker Playwright 浏览器依赖

**症状**：`error while loading shared libraries: libglib-2.0.so.0: cannot open shared object file`、Playwright 启动崩溃、测试超时。

**规则**：
1. 多阶段构建中，Playwright 运行时依赖（libglib2.0-0、libnss3、libatk1.0-0、libgbm1、libasound2、libxshmfence1、libgtk-3-0 等）**必须装在最终运行阶段（work 阶段）**，不能只装在 playwright builder 阶段。
2. Debian Bookworm 用 `libasound2`（不是 `libasound2t64`，那是 Trixie 包名）。装错包名会导致 apt-get 整批失败且不报错退出。
3. 测试环境默认 `CONCLAVE_WEB_SEARCH_MODE=stub`，避免 Playwright/外网超时。需要真实搜索的测试加 `pytest.mark.skipif(not os.environ.get("CONCLAVE_RUN_WEBSEARCH_TESTS"))`。

### P4. Docker Compose 端口与命名空间

| 环境 | 命名空间 | 前端 | 后端 | Postgres | Redis | Qdrant |
|---|---|---|---|---|---|---|
| dev | conclave-dev | 5173 | 8000 | 5432 | 6379 | 6333 |
| oss | conclave-oss | 5174 | 8001 | 5433 | 6380 | 6335 |
| test | conclave-test | — | — | 5434 | 6381 | 6337 |

改端口必须三处一致：代码、Dockerfile、compose yml。

---

## 数据库/ORM

### P5. ORM 模型与 DDL 一致性（单一真相源）

**症状**：新增/修改 ORM 字段后，数据库报错 `column "xxx" of relation "meetings" does not exist`。

**根因**：建表 DDL 与 ORM 模型分处维护，字段变更只改了一侧，双源漂移。

**规则**（`db_init.py` 手写 DDL 已于 2026-08 废弃，`init_db()` 现为 no-op 兼容壳，仅为兼容旧调用点保留）：
1. 建表统一单入口：有 ORM 模型的表走 `Base.metadata.create_all()`；增量 schema 变更走 Alembic 迁移（`backend/alembic/versions/`）。
2. 改 ORM 模型必须同步生成 Alembic 迁移（`alembic revision --autogenerate` + 人工 review diff），禁止手写 CREATE TABLE。
3. 少数 legacy 表（users/tenants/rbac 相关/notifications/net_auth_requests 等）仍由各模块 `ensure_*_table()` / `init_auth_table()` 函数 raw SQL 建表：改这些表必须同步改对应 ensure 函数 DDL 与所有 raw SQL INSERT（见 `docs/sql-development-rules.md` §5）。
4. JSONB metadata 是扩展槽（ADR-002），非核心字段优先塞 metadata，不要随便加表列。

### P6. 多租户外键与 TRUNCATE CASCADE 锁超时

**症状**：测试 fixture 中 `TRUNCATE TABLE events RESTART IDENTITY CASCADE` 超时挂死。

**根因**：新增多租户外键（`fk_*_tenant → tenants(id)`）后，TRUNCATE CASCADE 需要获取所有相关表的 ACCESS EXCLUSIVE 锁，与异步引擎残留连接产生锁等待。

**规则**：
1. 测试 fixture 清理数据用 `DELETE FROM table` + `ALTER SEQUENCE ... RESTART WITH 1` 代替 `TRUNCATE CASCADE`。
2. 所有业务表外键统一用 `ON DELETE SET NULL`，避免级联删除导致意外数据丢失。
3. 后台任务/启动恢复等跨租户操作必须用 `create_system_tenant_ctx()` 包裹，否则 tenant_filter 会 fail-closed 返回 FALSE。

### P7. SQLAlchemy 模型与 raw SQL 表混用时 FK 声明陷阱

**症状**：`Base.metadata.create_all()` 抛出 `sqlalchemy.exc.NoReferencedTableError: Foreign key associated with column 'X.tenant_id' could not find table 'tenants' with which to generate a foreign key`。

**根因**：`tenants` 等插件表由 `ensure_tenants_table()` 通过 raw SQL `CREATE TABLE IF NOT EXISTS` 创建，未注册到 SQLAlchemy `Base.metadata`。在 ORM 模型中声明 `ForeignKey("tenants.id")` 后，`create_all()` 排序表依赖时找不到被引用表，直接崩溃。

**规则**：
1. 对于 raw SQL 创建的表（如 tenants、由插件管理的表），**不要**在 SA ORM 模型中声明 `ForeignKey(...)`。
2. 外键约束统一由 raw SQL `ALTER TABLE ... ADD CONSTRAINT ... REFERENCES table(id) ON DELETE SET NULL` 在表创建后添加（参见 `app/tenants/service.py::ensure_business_tables_tenant_id()`）。
3. SA 模型中仅声明列类型和 `index=True`，注释说明外键由迁移统一添加。
4. 新增 ORM 模型前先确认对应模块是否已有 raw SQL DDL。如果有，要么统一迁移到 ORM，要么完全不建 ORM 模型，切勿混用导致 metadata 污染。

### P8. 多租户隔离 Checklist（强制）

为任何资源表添加/修改多租户支持时，必须逐项确认：

1. 表已加入 `app/tenants/service.py::_BUSINESS_TABLES`（自动迁移加列）
2. INSERT 时填充 `tenant_id = current_tenant_id()`
3. SELECT 列表加 `WHERE tenant_id = :tid`（系统资源继承场景用 `OR tenant_id IS NULL`）
4. UPDATE/DELETE 加 WHERE tenant_id 条件，防止跨租户操作
5. GET by ID 必须校验 tenant_id，不能仅按 ID 查询
6. 不在 SA 模型中对 raw SQL 表声明 ForeignKey（见 P7）
7. 测试覆盖：创建两个租户 → 各插入数据 → 互相查询不到对方数据

**教训**：Phase 1b 为所有业务表加了 tenant_id 列和 ALTER TABLE 外键，但多个模块（key_store、docker_hosts、net_auth、documents）的 DAO/路由层忘记实际使用该列进行过滤，导致跨租户数据泄露。参见修复报告 `docs/retrospectives/2026-07-21-multitenant-isolation-and-settings-ux.html`。

### P9. ORM 模型导出与 Alembic 一致性

**症状**：`alembic upgrade head` 不创建 `audit_logs` 表，因为 `AuditLogModel` 未在 `app/db/models/__init__.py` 中导出，Alembic 无法注册到 `Base.metadata`。

**根因**：新增 ORM 模型后只在定义文件中创建了类，忘记在 `__init__.py` 的 `__all__` 和 import 中添加。Alembic 通过 `from app.db.models import *` 注册模型到 metadata，未导出的模型不会被注册。

**规则**：
1. **新增 ORM 模型后，必须在 `app/db/models/__init__.py` 中同时添加 import 和 `__all__` 条目**。
2. **同步更新 `alembic/env.py` 的显式导入列表**（env.py 使用 `from app.db.models import (...)` 而非 `import *`，需要逐个列出）。
3. **验证方式**：`grep -n "class.*Model.*Base" app/db/models/*.py` 列出所有模型类，与 `__init__.py` 的 `__all__` 和 `alembic/env.py` 的导入列表交叉比对。
4. **raw SQL 创建的表不建 ORM 模型**（见 P7），只有通过 `Base.metadata.create_all()` / Alembic 管理的表才需要。

### P10. db_legacy shim 迁移纪律

**症状**：`from app.db_legacy import xxx` 的调用链中多了一层无意义的 re-export，增加代码导航成本和 IDE 跳转层级。

**根因**：`db_legacy.py` 原本是直接实现数据库操作的模块，后来所有函数迁移到 `app.dao.*` 子模块，`db_legacy.py` 变成纯 shim。但调用方未同步更新 import 路径。

**规则**：
1. **新代码禁止 `from app.db_legacy import`**，直接使用 `from app.dao.xxx import yyy`。
2. **迁移 shim 时按 dao 子模块分组 import**：`meeting_dao`、`meeting_aux_dao`、`message_dao`、`event_dao`、`agent_role_dao`、`preference_dao`、`tag_dao`、`db_init`。
3. **函数内 import 保持原位置**：如果原来是函数内 import（避免循环依赖），迁移后仍然是函数内 import。
4. **shim 文件保留不删除**：可能有外部代码或插件引用，后续单独清理。

---

## 测试

### P11. Mock 函数签名兼容

**症状**：`TypeError: _deep_think() got an unexpected keyword argument 'override_mode'`、mock 断言失败。

**规则**：
1. 测试中 mock 异步函数时，签名用 `async def mock(*args, **kwargs)` 或 `**_kwargs` 吞掉多余参数，防止生产代码加参数后测试崩溃。
2. 断言 mock 调用次数/参数时，断言"至少包含"而不是"第一个参数就是 X"，因为管线前面可能插入新的 LLM 调用（如 `classify_intent_async` 在 clarify 之前）。

### P12. 测试认证绕过

测试环境需要同时设置：
- `APP_ENV=test`
- `CONCLAVE_TEST_DISABLE_AUTH=1`

缺一不可。少一个会返回 401/403。

### P13. pytest-xdist 多进程测试隔离

**症状**：pytest-xdist 并行跑测试时出现 `relation "xxx" does not exist`、数据交叉污染、Redis key 冲突。

**根因**：多个 worker 进程共享同一个 PG 数据库/Redis DB/Qdrant collection，并发 DDL/DML 产生竞态。

**规则**：
1. conftest.py 已内置 `_apply_xdist_isolation()`：每个 worker 自动使用独立 PG 库（`conclave_test_gwN`）、Redis DB（`N%16`）、Qdrant collection（`conclave_chunks_gwN`）。
2. 不使用 `client` fixture 的测试（直接调 Runner/DAO）必须确保 session 级 `_ensure_db_initialized` fixture 已建表。
3. 模块级单例（bus、engine、agent 缓存）在 xdist 下天然隔离（每个 worker 独立进程），但同一 worker 内测试仍需 `_reset_state` 清理。
4. 并行数由 `-n auto` 自动检测 CPU 核心数；如需固定数量用 `-n 2`/`-n 4`。

### P14. 测试断言必须 grep 核验代码真实返回值

**症状**：`test_common_knowledge_has_strength_weak` 断言 `strength=="weak"`，但 `_make_common_knowledge_evidence()` 实际返回 `"none"`，CI 红。属于"测试本身写错了"，不是代码 bug。

**根因**：写/改测试时凭印象填断言值，未运行代码确认实际返回值，属于 Anti-Vibe-Coding 在测试领域的具体表现。

**规则**：
1. 新增/修改测试断言前，**必须读被测函数源码确认返回值**，或先跑一次看实际输出，禁止凭"应该是 weak 吧"填值。
2. 测试名必须与断言一致（函数叫 `test_xxx_has_strength_weak` 却断言 `"none"` 属于自相矛盾）。
3. 修复 CI 失败时，先判断是"代码错"还是"测试错"：grep 被测函数实际返回值，不要一律改代码去迎合错误的测试。

---

## CI/Git

### P15. CI 稳定性纪律（禁止"红 CI 提交"）

**症状**：CI 反复失败，开发者习惯性忽略 CI 结果。

**根因**：版本漂移（本地 ruff/mypy 与 CI `requirements.lock` 不一致）、依赖冲突（Windows pip 静默忽略）、pre-commit hook 未安装。详细背景和修复历史见 `docs/ci-stability-guide.md`。

**规则（强制）**：
1. **Pre-commit + pre-push hook 必须激活**。`bash scripts/install-hooks.sh`。
2. **禁止提交已知会导致 CI 红的代码**：ruff check 0 errors、ruff format 0 files need reformatting、mypy 不新增 errors。
3. **mypy 设为 `continue-on-error`**（CI 中），版本已对齐到 2.3.0。不得新增 errors。
4. **CI 分支触发必须与主干一致**（当前 `main`）。
5. **`--no-verify` 仅限紧急情况**，后续 commit 必须补回检查。
6. **CI 红灯 24 小时内必须修复**。
7. **ruff/mypy 版本三处一致**：`requirements.lock` → `.pre-commit-config.yaml` `rev` → 本地安装版本。
8. **依赖冲突必须本地验证**：`pip install --dry-run -r requirements.lock`。
9. **ruff 配置变更时全量检查**：`requirements.lock`/`pyproject.toml` 变更时 hook 自动全量 ruff check + format。
10. **pre-push Docker CI 一致性验证**：`scripts/docker-ci-check.sh`，Docker 未运行时自动跳过。

**双层 Hook 速查**：pre-commit 秒级检查（版本校验+暂存文件）、pre-push Docker 检查（CI 环境一致性验证）。详见 `docs/ci-stability-guide.md`。

### P16. PowerShell + 中文 Commit Message 编码问题

**症状**：`git commit -m "中文消息"` 在 PowerShell 中静默失败（exit code 1，无错误输出），但同样的消息在 Git Bash 中正常。

**根因**：PowerShell 对内联中文字符串的编码处理与 git 的预期不一致，导致 commit message 传递失败。不是 hook 的问题（hook 本身通过了）。

**规则**：在 PowerShell 中提交中文 commit message 时，**必须用 `-F` 文件方式**，不要用 `-m` 内联。

```bash
# 错误（PowerShell 中会静默失败）
git commit -m "fix(rag): 修复多路召回并发问题"

# 正确（写入文件再引用）
git commit -F commit-msg.txt
```

**参考**：commit `2348664` 的提交过程中发现并确认。

### P17. Git Hook 在 PowerShell 下的 stdout 文件描述符问题

**症状**：`git push`（或 `git commit`）时 hook 脚本报错 `echo: write error: Bad file descriptor`，导致 hook 误报失败、推送被阻止。在 Git Bash 或 Linux 下正常。

**根因**：Git hooks 的 stdout 在 PowerShell/Git Bash 环境下可能被 Git 用于协议通信（尤其 pre-push hook 从 stdin 读取 ref 信息），向 stdout 写入 `echo` 时 fd 无效或被关闭，触发 `Bad file descriptor`。`set -e` 使脚本在 echo 失败时立即退出。

**规则**：
1. 所有 Git hook 脚本（pre-commit、pre-push 及其调用的子脚本）必须在开头加 `exec >&2`，将所有诊断输出重定向到 stderr。
2. Hook 的 stdout 仅用于 Git 协议通信，诊断信息（echo、ruff/mypy 输出等）一律走 stderr。
3. 在 Docker 容器内执行的检查命令（ruff/mypy）输出通过 docker 继承的 fd 自然流向 stderr，无需额外重定向。
4. 编写新 hook 时遵循此规则，避免 PowerShell 用户每次 push 都要 `--no-verify`。

**参考**：scripts/docker-ci-check.sh、scripts/install-hooks.sh 均已添加 `exec >&2`。

---

## 编排器

### P18. cross_team 门禁 claim_refs 不能信任 LLM 返回的 ID

**症状**：cross_team 阶段门禁硬校验误判"所有角色 claims 未被冲突引用"，导致管线无限回流 intra_team，无法进入 evidence_check。

**根因**：LLM（含 StubLLM）返回的 `conflicts[].sides[].claim_id` 是它编造的字符串（如 `claim-1`），而 `run_intra_team` 在运行时给 claims 分配的是 UUID（`claim-{uuid4().hex[:8]}`），两者永远对不上。代码直接 `referenced_claims.update(refs)` 把这些假 ID 加进集合，后续按真实 claim ID/文本匹配时交集为空。

**规则**：
1. 处理 LLM 返回的 `claim_refs` 时，**必须先过滤掉不在 team_conclusions 中的 ID**，不能直接信任。
2. ID 匹配零命中时，**必须回退到 side_a/side_b/summary 文本双向子串匹配**（`text[:20] in ct` 或 `ct[:20] in text`）。
3. 测试用的 StubCompute 如果 intra_team 和 cross_team 由不同分支返回 claims，**必须保证两边文本有子串重叠**，否则硬校验会判定未引用。
4. sides[] 数组格式要规范化为 side_a/side_b 字段，再从 sides[].text 提取文本、从 sides[].claim_id 提取 claim_refs。

### P19. plan_intra_team 必须对角色名做规范化

**症状**：中文角色名（如"安全专家""后端工程师"）传入 plan_intra_team 时，去重集合 `seen_normalized_roles` 和门禁 `target_roles` 匹配失效，导致同一规范角色被重复创建任务、supplement 模式漏处理目标角色。

**根因**：`state.team_config` 由 LLM 生成，可能包含中文/英文/混合写法的角色名；而 run_intra_team 内部用 Role 枚举值（`product_architect`/`engineer` 等）作为 key。planner 直接用原始字符串做去重和集合判断，两边 key 空间不一致。

**规则**：plan_intra_team/plan_cross_team 遍历 role_def 时，**必须调用 `match_role(raw_role)` 映射到规范枚举值**，用规范值做去重、supplement 过滤、任务角色字段。无匹配时再 fallback 到原始值。

### P20. 质量门禁终态设置时序

**症状**：自我迭代 Loop 失效，`Runner.run()` 的 `while not is_terminal(state)` 循环在 produce 阶段后就退出，质量门禁评估永远不执行。同时 `auto_iterate=False` 时 while 循环无限重跑 produce 导致死循环。

**根因**：`stage_runners.py::run_produce()` 在 produce 阶段结束时就设置 `state.status = MeetingStatus.DONE`，导致 `is_terminal(state)` 返回 True，Runner 主循环退出。质量门禁代码在 `is_terminal()` 检查之后，永远不会被执行。

**规则**：
1. **终态 DONE 只能在质量门禁评估后设置**。阶段 runner（`run_clarify`/`run_intra_team`/`run_produce` 等）不应设置 DONE，只设置 `state.stage` 标识当前阶段已完成。
2. **Runner.run() 负责所有终态转换**：质量门禁通过 → DONE；质量未达标但 `auto_iterate=False` → DONE（需人工确认）；质量未达标且达到迭代上限 → DONE；节点异常 → FAILED。
3. **auto_iterate=False 时必须设置终态退出循环**，否则 `should_iterate=True` 会导致 while 循环无限重跑 produce。
4. **测试断言同步更新**：直接调用 `produce_node()` / `run_produce()` 的测试应断言 `status == RUNNING`（非 DONE），DONE 由 Runner 设置。

---

## 文档质量

### P21. 文档真实性核查（README/CHANGELOG/ADR 与代码对齐）

**症状**：README 中描述的功能/路径/文件/配置与实际代码严重脱节，出现"力导向图"（实际不存在）、`AgentGraph.tsx`（文件不存在）、`/api/meetings`（实际无 `/api` 前缀）、"OAuth"（代码无任何引用）、"默认模型 Qwen2.5-72B"（实际 DeepSeek-V3.2）等失实描述。导致新成员/评审者被误导，PR 评审失去参照系。

**根因**：文档与代码分头演进，代码改了文档没同步；或文档先行描述了"计划做"的功能，后来功能未实现/改名/删除，但文档未回滚；或 AI 助手凭记忆/推测补写文档，未 grep 核验。

**规则（强制，违反等同违反工程规范）**：
1. **写文档时每一条事实性声明必须 grep 核验**。包括但不限于：文件路径、类名/函数名、API 路径、配置项默认值、依赖库名、枚举值、按钮文案、端口号。
   - 文件存在性：`Glob` 扫描实际目录结构，不要凭记忆列文件树。
   - API 路径：`grep -n "@router\.\|APIRouter\|prefix=" backend/app/routers/`。
   - 配置默认值：`grep -n "Field\|_env\|default=" backend/app/config.py`。
   - 枚举值：`grep -n "class.*Enum\|=\s*\""` 在 enums.py。
   - 前端按钮文案：`grep -n "按钮文案"` 在 frontend/src/。
2. **区分"已实现"和"计划做"**。文档中描述计划功能必须显式标注"计划中/TODO/未实现"，不能用现在时陈述（"支持 X" 暗示已实现）。
3. **README 项目结构树必须用 Glob 扫描生成**，不要手写。手写的文件树几乎必然过时。
4. **V3/重构章节的"已完成"vs"后续工作"必须基于代码实际状态**。迁移已完成的工作必须从"后续工作"移到"已完成"，不能留在待办列表制造假象。
5. **文档变更 commit 必须在 message 中列出核验方式**（如"验证方式: grep + Glob 逐条核对"），便于审查者追溯。
6. **定期全量审查**：每次大版本合并后，对 README/ADR/CHANGELOG 做一次全量核对，修正失实描述。

**反面案例（本次事件）**：
- README 写"力导向拓扑图" → 实际无 d3-force、无相关依赖、AgentGraph.tsx 不存在
- README 写"OAuth" → grep -ri oauth 零结果
- README 写"每次调用新建 AsyncClient" → 实际 `_get_client()` 已实现懒加载单例
- README 写 V3"核心业务迁移到 PostgreSQL"为后续工作 → 实际已完成（10+ ORM 模型）
- API 表路径全部带 `/api` 前缀 → 实际路由无全局前缀

**参考修复**：commit `41b1439` 及之前 7 个 docs commit，逐条 grep 核验后修正。

### P22. 问题评估与绕过检查（禁止"声明式修复"）

**症状**：面对代码审查/外部评审指出的问题，AI 助手直接"认领"问题并写进待办/修复报告，但实际未 grep 核验问题是否真实存在。导致：
- 把不存在的"问题"写进 README 待办（如"Embedding 客户端未用单例"——实际已用单例）
- 用"已记录到待办"绕过立即修复（问题明明可以当场修，却推到未来）
- 对评审意见"全盘接受"而不客观校正其中的事实性错误

**根因**：AI 助手倾向"讨好"评审者，遇到批评就认领，缺乏"先验证再回应"的纪律；或为快速结束对话，用"已记录待办"代替实际修复。

**规则（强制）**：
1. **收到问题清单时，必须逐条 grep 核验后再回应**。对每一条声明给出"已验证存在/不存在/部分准确"的判定，附上核验证据（文件:行号 + grep 命令）。
2. **禁止"声明式修复"**：不能只写"已修复"或"已记录待办"就结束，必须展示实际代码改动或 grep 核验结果。
3. **问题可当场修复的必须当场修**，不要推到"待办"。只有以下情况允许记待办：
   - 修复需要引入新依赖/新架构（需开 ADR）
   - 修复影响范围超过单次 PR 400 行限制
   - 修复依赖尚未就绪的外部条件（如 gRPC stub 等待 protobuf 定义）
4. **对评审意见要客观校正，不要全盘接受**。评审者也会犯事实性错误（如 DeepSeek 误判"SQLite 持久化"——实际已是 PostgreSQL）。校正时必须给出代码证据，区分"认可/部分认可/不认可"。
5. **待办项必须有可验证的验收标准**。"改进 RAG"不是合格待办，"实现 HyDE 检索策略，新增 test_hyde_retrieval.py 验证"才是。
6. **README/待办中的每一条缺陷描述必须经过代码核验**，不能凭印象写。写完待办后回头用 grep 自查一遍。

**反面案例（本次事件）**：
- 声明"Embedding 客户端未用连接池单例" → grep 核验发现 `_get_client()` 已实现单例 → 声明错误，已修正
- 声明"mypy 22 个历史遗留错误" → 实际未在当前环境重新跑 mypy 验证，数字可能过时 → 应标注"基于历史验证，需重新跑确认"
- 对 DeepSeek 评审"全盘认可"其中 RAG B- 评级 → 实际 ContextManager 的窗口预算管理是 DeepSeek 未识别的加分项，应客观补充

---

## 杂项

### P23. TypeScript `Error cause`

`new Error("msg", { cause: err })` 需要 `tsconfig.json` 的 `target >= ES2022`。当前项目已设为 ES2022，不要回退到 ES2020/ES2021。

### P24. ESLint 规则宽松策略

`frontend/eslint.config.js` 对现有代码启用了较宽松规则（no-explicit-any、no-unused-vars、react-hooks/exhaustive-deps 等都是 off/warn）。
**规则**：
- 不要为了"更干净"突然把这些规则调成 error，会导致几百个历史遗留报错让 CI 红。
- 新代码自觉遵守，但规则级别保持现状。
- 新增 ESLint 规则必须一次性修复所有存量问题，不能留下半红状态。

### P25. 函数内 import 与模块级 import 的取舍

**症状**：代码审查发现大量 `from xxx import yyy` 写在函数体内，而非文件头部。

**规则**：
1. **默认放在模块级**（文件开头）。Python 的 import 是幂等的，模块级 import 不会重复加载。
2. **仅在以下情况允许函数内 import**：
   - 存在循环依赖（A import B，B import A）——用函数内 import 打破循环
   - 重依赖延迟加载（如 `cryptography.fernet`、`playwright`）——仅在首次使用时加载，减少冷启动时间
   - 可选依赖（如 `grpc`，未安装时降级）——在 try/except 中 import
3. **重构前必须验证无循环依赖**：用 `grep -r "from app.xxx" backend/app/` 检查目标模块是否反向引用当前模块。无反向引用则安全提到模块级。
4. **禁止"习惯性函数内 import"**：不要因为"不确定有没有循环依赖"就全部塞到函数里。这会导致 import 重复执行、IDE 跳转失效、代码可读性下降。

**参考**：`app/services/key_store.py` 已完成模块级 import 重构（commit `b21ec1f`），验证无循环依赖。

### P26. Alembic env.py 的 context 注入

**症状**：直接运行 `python alembic/env.py` 报错 `ImportError: cannot import name 'context'` 或 `ModuleNotFoundError`。

**根因**：`from alembic import context` 中的 `context` 不是 alembic 包的普通模块，而是 Alembic 框架在运行迁移时通过 `alembic.ini` 配置注入的全局对象（类似 Flask 的 `g`）。独立运行时该对象不存在。

**规则**：
1. `alembic/env.py` **必须通过 `alembic upgrade head` / `alembic revision` 等 CLI 命令调用**，不能直接 `python alembic/env.py`。
2. 不要为了"修复"这个 import 错误而把 `context` 改成其他写法，那会破坏 alembic 迁移。
3. IDE 中显示红色波浪线是正常的（静态分析无法识别 alembic 的运行时注入），可加 `# noqa: I001` 抑制 ruff 误报。

### P27. 测试质量失效（假绿测试与覆盖盲区）

**症状**：CI 全绿但生产环境频繁出 bug。典型表现：
- `verify_password` 段数检查 bug（4 段 vs 5 段）导致所有登录 401，但该函数零测试覆盖
- `test_role_matching.py` 在测试文件中重新实现 `_match_role` 逻辑副本，而非 import 真实函数
- `test_memory.py:589` 测试函数无任何 `assert` 语句，仅调用函数
- `test_stats.py:116` 用 `try/except: pass` 吞掉异常，测试通过但未验证任何结果

**根因**：测试规则只要求"必须加测试"，但未约束测试质量。导致：
1. 测试逻辑副本代替真实代码 import → 被测代码变更时测试不更新，假绿
2. 无断言或弱断言（`assert True` / `.not.toThrow()`）→ 测试永远通过，检测不到回归
3. `try/except: pass` 吞异常 → 即使被测函数抛错，测试也绿
4. 配对函数（hash/verify）无往返测试 → 一侧改了格式，另一侧不知道
5. `@pytest.mark.skip` 无追踪 → 跳过的测试永远不运行，成为永久盲区

**规则（强制，对应 AGENTS.md §5.7）**：

1. **禁止测试逻辑副本**。必须 `import` 真实函数，不能在测试中重新实现。反面案例：`test_role_matching.py:10-30`。
2. **每个测试函数至少一个有意义的断言**。无断言的测试必须删除或补全。反面案例：`test_memory.py:589-600`。
3. **禁止 `try/except: pass` 在测试体中吞异常**。预期异常用 `pytest.raises`。反面案例：`test_stats.py:116-122`。
4. **配对函数（hash/verify、encode/decode、create/verify）必须有往返测试**：正向通过 + 反向拒绝。这是 `verify_password` bug 的直接预防措施。
5. **关键安全函数（auth.py、middleware.py、csrf.py）必须有专项测试文件**。无测试的安全函数禁止合并。
6. **`@pytest.mark.skip` 必须标注原因、恢复条件、责任人**。模块级 skip 必须在本文件或 issue 中有记录。
7. **Bug 修复必须先写失败用例**。先复现 bug（测试红），再修复（测试绿）。禁止"先修后测"。
8. **禁止通过削弱断言强行通过**。`assert x == 5` 失败时不能改成 `assert x is not None`。
9. **测试必须能检测回归**：故意改坏被测代码，确认测试失败。永远通过的测试是噪音。
10. **测试命名必须与断言一致**。`test_xxx_has_strength_weak` 不能断言 `"none"`（见 P14）。

**验证清单（提交前自查）**：
- [ ] 新增测试是否 `import` 了真实被测函数？（grep 检查 import 行）
- [ ] 每个测试函数是否有至少一个 `assert` / `expect`？
- [ ] 是否有 `try/except: pass` 在测试体中？
- [ ] 配对函数是否有往返测试？
- [ ] 被测函数本身是否被 mock？（应为否）
- [ ] 故意改坏代码，测试是否失败？（抽检）

---

## AI 助手文件操作纪律（PowerShell）

### P28. 关键文件截断事故（PowerShell 非终结错误 + 行切片写盘）

**症状**：更新 `project_memory.md` 顶部指针后，文件被截断为 5 行，后续所有章节（Hard Constraints 尾部、Engineering Conventions、Lessons Learned）丢失，且本地无任何备份可恢复。

**事故链**（2026-09-04，完整记录见 vault 检查点 `20260904-0303-projectid-isolation-d11-d13-committed.md` 事故记录节）：
1. 编辑工具对 Trae 记忆路径有作用域限制（PathScopeExceed），改用 PowerShell 脚本替换文件头部指针块。
2. 第一版脚本含中文常量：PowerShell 5 按系统 ANSI（GBK）读取 .ps1，中文乱码导致解析失败（见 P29）。
3. 第二版脚本改为纯 ASCII 逻辑 + 行切片拼接（新头部行 + `$lines[5..($lines.Length-1)]`）。切片返回 `Object[]`，`List[string].AddRange()` 抛 `MethodArgumentConversionInvalidCast`。
4. **该异常是非终结错误**：脚本未设 `$ErrorActionPreference='Stop'`，继续执行后续 `WriteAllLines`——只写入了前 5 行，原文件其余内容全部丢失。
5. 恢复排查：记忆目录无备份、卷影副本不可用（WMI 初始化失败）、编辑器本地历史无记录、vault 原文层无全文引用。最终仅能从会话上下文逐字恢复部分内容，丢失章节如实标注、禁止凭空补写。

**根因**：
1. PowerShell 中 .NET 方法调用异常默认是**非终结错误**，脚本带伤继续执行后续写操作——这是数据丢失的直接原因。
2. 行切片拼接写盘（只写部分行 + 拼接剩余行）天然有全量丢失风险，任何一步失败都会写出残缺文件。
3. 关键文件修改前无备份，事故后无恢复源。

**规则（强制）**：
1. **关键文件（记忆文件、vault 指针、配置文件）修改前必须先备份**：复制原文件到工作目录再动手。
2. **优先整文件读写，禁止无校验的行切片拼接**：`ReadAllText → String.Replace → 校验 Contains 成功 → WriteAllText`。替换未命中时必须中止，不得降级写部分内容。
3. **PowerShell 写盘脚本必须设 `$ErrorActionPreference = 'Stop'`**，且写盘前校验所有中间结果（数组长度、替换命中、内容非空）。
4. **写盘后必须验证**：读回文件确认长度合理 + 地标行存在（如章节标题）。
5. **恢复纪律**：事故后按"目录备份 → 卷影副本 → 编辑器本地历史 → vault/会话上下文"顺序排查恢复源；只能逐字恢复有出处的内容，丢失部分如实标注"丢失待补"，**禁止凭空补写**（对齐 P21 文档真实性）。

### P29. PowerShell 5 读取 .ps1 脚本的中文编码解析错误

**症状**：含中文常量的 .ps1 脚本报 `Unexpected token` 解析错误，错误信息中的中文显示为乱码（如 `涓嬩竴姝ワ細`）。

**根因**：PowerShell 5 对无 BOM 的 .ps1 按系统 ANSI（中文 Windows 为 GBK）读取；UTF-8 编码的中文被按 GBK 解析后乱码，引号/括号配对被打断，触发解析错误。与 P16（git commit -m 中文）同源不同面。

**规则**：
1. **脚本与数据分离**：中文内容写入独立的 UTF-8 文本文件（用编辑工具写，编码可控），.ps1 只保留纯 ASCII 逻辑，读数据文件处理。
2. 备选：.ps1 保存为 UTF-8 **with BOM**（PowerShell 5 认 BOM）。但跨工具写 BOM 不可靠，优先用规则 1。
3. PowerShell 7+ 默认 UTF-8 无此问题，但本项目环境是 PowerShell 5，按最严格规则执行。

---

> 本文件从 AGENTS.md §4 拆出于 2026-07-30。子节编号从原 §4.x 改为 P1-P26，内容不变。
> AGENTS.md §4 现在只保留类别索引，按需指向本文件。
> P27 新增于 2026-08-01，对应 AGENTS.md §5.7 测试纪律硬性规则。
> P28/P29 新增于 2026-09-04，源自 project_memory.md 截断事故（新类别"AI 助手文件操作纪律"）。
