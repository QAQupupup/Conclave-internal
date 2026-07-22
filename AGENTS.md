# AGENTS.md — Conclave 项目 AI 助手指南

> 本文件是 AI 编码助手（Cursor / Trae / Windsurf / Copilot / Claude Code 等）在本项目工作时的**第一入口**。开始工作前必须阅读本文件。
>
> 本文件只放"实战纪律"和"踩坑清单"。完整的工程规范见 `PROJECT_CONVENTIONS.md`（唯一权威规范），设计原则见 `docs/design/design-principles.md`，ADR 见 `docs/design/adr/`，UI 规范见 `backend/app/skills/ui_design_system.yaml`。

---

## 0. 开始工作前 30 秒

1. 读 `PROJECT_CONVENTIONS.md` 第 1、4、8 节（部署原则、提交规范、预提交卡点）。
2. 读本文件全文（下面所有章节）。
3. 如果要改 UI，读 `backend/app/skills/ui_design_system.yaml`。
4. 如果要改架构/数据模型，读 `docs/design/adr/` 下相关 ADR。
5. 如果要写修复报告，读 `docs/RETROSPECTIVE_CONVENTIONS.md`。
6. 开始编码前，用 `git status` 确认工作区干净，避免无关文件混入提交。
7. **如果要写/改文档（README/ADR/待办）**，必须先读 §4.16（文档真实性核查）。每一条事实性声明必须 grep 核验，禁止凭记忆写文档。
8. **如果要回应代码审查/外部评审**，必须先读 §4.17（问题评估与绕过检查）。逐条 grep 核验问题是否真实存在，禁止"声明式修复"。

---

## 0.5 AI 助手执行纪律（强制）

> 本节是对 PROJECT_CONVENTIONS.md §1.1（Docker Compose 优先）的 AI 助手执行细则。
> **违反这些规则等同于违反工程规范。**

### 0.5.1 命令执行无需请示

用户已明确授权：执行命令前**无需**弹出"是否允许执行"的确认，可以直接运行。
例外：涉及 `git push`、`git reset --hard`、`docker system prune -a`、`rm -rf` 系统级删除等不可逆操作，仍需简要说明影响后再执行。

### 0.5.2 所有 lint/typecheck/test 必须在 Docker 容器内执行

**禁止**在 Windows/macOS/Linux 宿主机直接运行以下命令：
- `pytest` / `python -m pytest`
- `ruff check` / `ruff format`（作为最终验证）
- `mypy`
- `npm run build` / `npx tsc` / `npx eslint`（作为最终验证）
- `python main.py` / `uvicorn` / `npm run dev`（启动服务）

**正确做法**：
- 后端 lint/typecheck：`docker compose -f docker-compose.test.yml run --rm backend-test sh -c "ruff check app ... && mypy ..."`
- 后端测试：`docker compose -f docker-compose.test.yml up --build --exit-code-from backend-test`
- 前端构建/测试：通过对应 docker compose 服务或容器内命令执行
- 启动开发环境：`docker compose up -d --build`

**允许在宿主机执行的命令**（仅限快速反馈，**不能替代容器内验证**）：
- `python -m py_compile <file>` 纯语法检查
- `git status` / `git diff` / `git log` / `git add`
- `ls` / `dir` / `Get-ChildItem` / `cat` / `type` 文件查看
- `docker compose config` 配置校验
- `pip install` 到虚拟环境仅供辅助脚本使用，**不能**用来跑项目测试

### 0.5.3 提交卫生

- 提交前必须在 Docker 容器内跑过 ruff/mypy/pytest 三个检查全部通过
- 禁止把临时文件（`__pycache__`、`.pyc`、`.pytest_cache`、本地虚拟环境、个人笔记）提交到仓库
- 提交信息必须遵循 Conventional Commits，scope 使用 `backend`/`frontend`/`docker`/`plugins` 等

---

## 1. 技术栈速查

| 层 | 技术 | 关键约束 |
|---|---|---|
| 后端 | Python 3.12 + FastAPI + asyncio + SQLAlchemy (async) | asyncio 原生，禁止阻塞调用 |
| 数据库 | PostgreSQL + pgvector + Redis + Qdrant | 元数据扩展走 JSONB `meetings.metadata`，禁止随意加核心列 |
| 前端 | React 18 + TypeScript + Vite + Ant Design | 入口 `app.html`（非 `index.html`），路径别名 `@ → src/` |
| 测试 | pytest + pytest-asyncio + Vitest + Playwright | 集成测试必须走 Docker Compose |
| 部署 | Docker Compose（多阶段构建强制） | 禁止本地直接 `python main.py` / `npm run dev` 跑服务 |
| 镜像源 | pip 清华 TUNA / npm npmmirror / apt 清华 / Docker 华为 SWR | 所有依赖必须国内源 |

---

## 2. 提交前必做清单（Pre-Flight Checklist）

**每次 `git commit` 前必须逐项确认，不得跳过：**

> **Pre-commit hook 已激活**：`.git/hooks/pre-commit` 会自动运行 ruff check + ruff format --check（后端）和 tsc + eslint（前端）。
> Hook 安装：`bash scripts/install-hooks.sh`（首次克隆仓库后执行一次）。
> 如 hook 未安装，以下手动检查必须逐项执行。

### 2.1 后端
- [ ] `cd backend && python -m ruff check app conclave_core tests` → **0 errors**
- [ ] `cd backend && python -m ruff format --check app conclave_core tests` → **0 files need reformatting**
- [ ] `cd backend && python -m mypy --config-file pyproject.toml app conclave_core` → **0 新增 errors**（mypy 2.3.0 本地显示 0 errors，见 §4.18，不得新增）
- [ ] 若改了 ORM 模型，确认 `app/dao/db_init.py` 的 DDL 与模型字段一致（尤其是新增列/默认值/JSONB）
- [ ] 若改了 API 路由，确认所有路径都在前端 `vite.config.ts` 的 proxy 列表和 `nginx.conf` 中

### 2.2 前端
- [ ] `cd frontend && npx eslint .` → 无新增 error（warnings 遵循现有宽松策略）
- [ ] `cd frontend && npx tsc -b --noEmit` → **0 errors**
- [ ] `cd frontend && npm run build` → 构建成功（CI 会跑）
- [ ] 若改了路由，确认 `App.tsx` 中有对应 `<Route>`，`nginx.conf` 有 fallback

### 2.3 集成验证
- [ ] `docker compose -f docker-compose.test.yml config` → 配置合法
- [ ] `docker compose -f docker-compose.test.yml up --build --exit-code-from backend-test` → 所有测试 pass
- [ ] 本地快速验证可用 `docker compose up -d --build` 启动 dev 环境 + 手动冒烟

### 2.4 提交卫生
- [ ] `git status` 确认没有混入个人临时文件（简历、导出脚本、html 报告、`Qwen*/`、`docs/audits/` 产物等）
- [ ] `git diff --cached` 检查暂存区内容，确认只包含本次变更
- [ ] `.gitignore` 中**禁止添加任何个人信息相关规则**（如姓名、简历、个人文档关键词）
- [ ] 不要把个人测试数据、临时脚本、下载文件放入仓库

---

## 3. 如何提交代码

### 3.1 Commit Message（Conventional Commits，强制）

格式：
```
<type>(<scope>): <中文描述>

[可选 body，说明为什么这样改、踩了什么坑]

[可选 footer，如 Refs: docs/retrospectives/2026-xx-xx-xxx.html]
```

允许的 `type`（严格限定，禁止自造）：
- `feat` 新功能
- `fix` Bug 修复
- `refactor` 重构（不改功能）
- `docs` 文档
- `test` 测试
- `chore` 构建/工具/依赖
- `perf` 性能优化
- `style` 代码风格（不影响逻辑）
- `ci` CI/CD 变更

`scope` 常用值：`backend`、`frontend`、`docker`、`orchestrator`、`agents`、`tools`、`db`、`auth`、`docs`。

**示例**：
```
fix(events): 修复并发发布事件导致 seq 逆序的问题

publish 时并发调用 save_event，虽然 DB seq 单调递增，但
内存历史追加顺序受 async 调度影响，导致 e2e 测试中出现
seq 39->38 逆序。修复：append 后按 seq 排序。
```

### 3.2 修复报告归档（P0/P1 Bug / 系统性修复必须）

- 位置：`docs/retrospectives/YYYY-MM-DD-{slug}.html`
- 必须标注 commit 区间（起始 → 结束）
- 必须通过 html-report skill 生成 HTML
- commit message footer 引用：`Refs: docs/retrospectives/2026-xx-xx-xxx.html`
- 规则详见 `docs/RETROSPECTIVE_CONVENTIONS.md`

### 3.3 推送

- 当前主干分支：`main`（V3 重构分支已合并）
- 推送前本地跑过 2.1/2.2/2.3 检查
- `git push origin <branch-name>`，不要 force push 到已共享分支

---

## 4. 高频踩坑清单（血泪教训）

> 这些坑都踩过，每次出现都导致 CI 红或生产 Bug。**写代码时主动避开。**

### 4.1 asyncio 事件循环（最常见大坑）

**症状**：`RuntimeError: ... got Future <Future pending> attached to a different loop`、测试中 `new_context()` 挂死、引擎 dispose 报错。

**根因**：模块加载时创建的 `asyncio.Lock() / Semaphore() / Event() / Queue()` 会绑定到第一个事件循环，测试场景中 `asyncio.run()` 每次创建新循环，单例对象持有的原语绑定到旧循环。

**规则**：
1. **模块级禁止直接实例化 asyncio 原语**。必须用 `app/lazy_asyncio.py` 提供的 `LazyLock / LazySemaphore`，它们在首次访问时绑定当前循环、循环变化时自动重建。
2. **持有 asyncio 原语的单例（BrowserPool / PlaywrightWebSearch / Engine 等）getter 必须循环感知**：保存创建时的 loop 引用，`get()` 时检测 `loop.is_closed()` 或 `loop is not current_loop`，如是则重建。参考 `app/db/engine.py::_ensure_engine()`、`app/tools/playwright_search.py::get_playwright_search()`。
3. **不要在同步代码中调用 `asyncio.run(engine.dispose())` 去释放绑定到其他循环的引擎**。直接丢弃引用让 GC 回收即可。
4. **测试 fixture 必须重置单例**：在 `conftest.py` 的 fixture 中清理 browser_pool、playwright_search、network clients 等模块级单例，避免跨测试泄漏。

### 4.2 Docker Playwright 浏览器依赖

**症状**：`error while loading shared libraries: libglib-2.0.so.0: cannot open shared object file`、Playwright 启动崩溃、测试超时。

**规则**：
1. 多阶段构建中，Playwright 运行时依赖（libglib2.0-0、libnss3、libatk1.0-0、libgbm1、libasound2、libxshmfence1、libgtk-3-0 等）**必须装在最终运行阶段（work 阶段）**，不能只装在 playwright builder 阶段。
2. Debian Bookworm 用 `libasound2`（不是 `libasound2t64`，那是 Trixie 包名）。装错包名会导致 apt-get 整批失败且不报错退出。
3. 测试环境默认 `CONCLAVE_WEB_SEARCH_MODE=stub`，避免 Playwright/外网超时。需要真实搜索的测试加 `pytest.mark.skipif(not os.environ.get("CONCLAVE_RUN_WEBSEARCH_TESTS"))`。

### 4.3 事件总线 seq 顺序

**症状**：`test_e2e_full_meeting_with_logging` 断言 `seqs == sorted(seqs)` 失败，出现逆序如 39→38。

**根因**：`publish()` 中并发 `await save_event()` 虽然 DB 返回单调递增 seq，但协程恢复顺序受调度影响，`history.append(event)` 顺序与 seq 不一致。

**规则**：`history.append(event)` 之后必须 `history.sort(key=lambda e: e.seq)`。永远不要依赖 append 顺序。

### 4.4 Mock 函数签名兼容

**症状**：`TypeError: _deep_think() got an unexpected keyword argument 'override_mode'`、mock 断言失败。

**规则**：
1. 测试中 mock 异步函数时，签名用 `async def mock(*args, **kwargs)` 或 `**_kwargs` 吞掉多余参数，防止生产代码加参数后测试崩溃。
2. 断言 mock 调用次数/参数时，断言"至少包含"而不是"第一个参数就是 X"，因为管线前面可能插入新的 LLM 调用（如 `classify_intent_async` 在 clarify 之前）。

### 4.5 ORM 模型与 DDL 一致性

**症状**：`init_db()` 报错 `column "xxx" of relation "meetings" does not exist`。

**根因**：新增/修改 ORM 字段后，忘记同步 `app/dao/db_init.py` 中的 CREATE TABLE DDL。

**规则**：改 ORM 模型时必须同步改 `db_init.py`；JSONB metadata 是扩展槽（ADR-002），非核心字段优先塞 metadata，不要随便加表列。

### 4.6 测试认证绕过

测试环境需要同时设置：
- `APP_ENV=test`
- `CONCLAVE_TEST_DISABLE_AUTH=1`

缺一不可。少一个会返回 401/403。

### 4.7 TypeScript `Error cause`

`new Error("msg", { cause: err })` 需要 `tsconfig.json` 的 `target >= ES2022`。当前项目已设为 ES2022，不要回退到 ES2020/ES2021。

### 4.8 ESLint 规则宽松策略

`frontend/eslint.config.js` 对现有代码启用了较宽松规则（no-explicit-any、no-unused-vars、react-hooks/exhaustive-deps 等都是 off/warn）。
**规则**：
- 不要为了"更干净"突然把这些规则调成 error，会导致几百个历史遗留报错让 CI 红。
- 新代码自觉遵守，但规则级别保持现状。
- 新增 ESLint 规则必须一次性修复所有存量问题，不能留下半红状态。

### 4.9 Docker Compose 端口与命名空间

| 环境 | 命名空间 | 前端 | 后端 | Postgres | Redis | Qdrant |
|---|---|---|---|---|---|---|
| dev | conclave-dev | 5173 | 8000 | 5432 | 6379 | 6333 |
| oss | conclave-oss | 5174 | 8001 | 5433 | 6380 | 6335 |
| test | conclave-test | — | — | 5434 | 6381 | 6337 |

改端口必须三处一致：代码、Dockerfile、compose yml。

### 4.10 多租户外键与 TRUNCATE CASCADE 锁超时

**症状**：测试 fixture 中 `TRUNCATE TABLE events RESTART IDENTITY CASCADE` 超时挂死。

**根因**：新增多租户外键（`fk_*_tenant → tenants(id)`）后，TRUNCATE CASCADE 需要获取所有相关表的 ACCESS EXCLUSIVE 锁，与异步引擎残留连接产生锁等待。

**规则**：
1. 测试 fixture 清理数据用 `DELETE FROM table` + `ALTER SEQUENCE ... RESTART WITH 1` 代替 `TRUNCATE CASCADE`。
2. 所有业务表外键统一用 `ON DELETE SET NULL`，避免级联删除导致意外数据丢失。
3. 后台任务/启动恢复等跨租户操作必须用 `create_system_tenant_ctx()` 包裹，否则 tenant_filter 会 fail-closed 返回 FALSE。

### 4.11 pytest-xdist 多进程测试隔离

**症状**：pytest-xdist 并行跑测试时出现 `relation "xxx" does not exist`、数据交叉污染、Redis key 冲突。

**根因**：多个 worker 进程共享同一个 PG 数据库/Redis DB/Qdrant collection，并发 DDL/DML 产生竞态。

**规则**：
1. conftest.py 已内置 `_apply_xdist_isolation()`：每个 worker 自动使用独立 PG 库（`conclave_test_gwN`）、Redis DB（`N%16`）、Qdrant collection（`conclave_chunks_gwN`）。
2. 不使用 `client` fixture 的测试（直接调 Runner/DAO）必须确保 session 级 `_ensure_db_initialized` fixture 已建表。
3. 模块级单例（bus、engine、agent 缓存）在 xdist 下天然隔离（每个 worker 独立进程），但同一 worker 内测试仍需 `_reset_state` 清理。
4. 并行数由 `-n auto` 自动检测 CPU 核心数；如需固定数量用 `-n 2`/`-n 4`。

### 4.12 SQLAlchemy 模型与 raw SQL 表混用时 FK 声明陷阱

**症状**：`Base.metadata.create_all()` 抛出 `sqlalchemy.exc.NoReferencedTableError: Foreign key associated with column 'X.tenant_id' could not find table 'tenants' with which to generate a foreign key`。

**根因**：`tenants` 等插件表由 `ensure_tenants_table()` 通过 raw SQL `CREATE TABLE IF NOT EXISTS` 创建，未注册到 SQLAlchemy `Base.metadata`。在 ORM 模型中声明 `ForeignKey("tenants.id")` 后，`create_all()` 排序表依赖时找不到被引用表，直接崩溃。

**规则**：
1. 对于 raw SQL 创建的表（如 tenants、由插件管理的表），**不要**在 SA ORM 模型中声明 `ForeignKey(...)`。
2. 外键约束统一由 raw SQL `ALTER TABLE ... ADD CONSTRAINT ... REFERENCES table(id) ON DELETE SET NULL` 在表创建后添加（参见 `app/tenants/service.py::ensure_business_tables_tenant_id()`）。
3. SA 模型中仅声明列类型和 `index=True`，注释说明外键由迁移统一添加。
4. 新增 ORM 模型前先确认对应模块是否已有 raw SQL DDL。如果有，要么统一迁移到 ORM，要么完全不建 ORM 模型，切勿混用导致 metadata 污染。

### 4.13 多租户隔离 Checklist（强制）

为任何资源表添加/修改多租户支持时，必须逐项确认：

1. 表已加入 `app/tenants/service.py::_BUSINESS_TABLES`（自动迁移加列）
2. INSERT 时填充 `tenant_id = current_tenant_id()`
3. SELECT 列表加 `WHERE tenant_id = :tid`（系统资源继承场景用 `OR tenant_id IS NULL`）
4. UPDATE/DELETE 加 WHERE tenant_id 条件，防止跨租户操作
5. GET by ID 必须校验 tenant_id，不能仅按 ID 查询
6. 不在 SA 模型中对 raw SQL 表声明 ForeignKey（见 §4.12）
7. 测试覆盖：创建两个租户 → 各插入数据 → 互相查询不到对方数据

**教训**：Phase 1b 为所有业务表加了 tenant_id 列和 ALTER TABLE 外键，但多个模块（key_store、docker_hosts、net_auth、documents）的 DAO/路由层忘记实际使用该列进行过滤，导致跨租户数据泄露。参见修复报告 `docs/retrospectives/2026-07-21-multitenant-isolation-and-settings-ux.html`。

### 4.14 函数内 import 与模块级 import 的取舍

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

### 4.15 Alembic env.py 的 context 注入

**症状**：直接运行 `python alembic/env.py` 报错 `ImportError: cannot import name 'context'` 或 `ModuleNotFoundError`。

**根因**：`from alembic import context` 中的 `context` 不是 alembic 包的普通模块，而是 Alembic 框架在运行迁移时通过 `alembic.ini` 配置注入的全局对象（类似 Flask 的 `g`）。独立运行时该对象不存在。

**规则**：
1. `alembic/env.py` **必须通过 `alembic upgrade head` / `alembic revision` 等 CLI 命令调用**，不能直接 `python alembic/env.py`。
2. 不要为了"修复"这个 import 错误而把 `context` 改成其他写法，那会破坏 alembic 迁移。
3. IDE 中显示红色波浪线是正常的（静态分析无法识别 alembic 的运行时注入），可加 `# noqa: I001` 抑制 ruff 误报。

### 4.16 文档真实性核查（README/CHANGELOG/ADR 与代码对齐）

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

### 4.17 问题评估与绕过检查（禁止"声明式修复"）

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

### 4.18 CI 稳定性纪律（禁止"红 CI 提交"）

**症状**：GitHub CI 失败率居高不下，每次 push/PR 后 CI 红灯，开发者习惯性忽略 CI 结果，导致 CI 形同虚设。

**根因**：
1. Pre-commit hook 未安装/未激活，本地零卡点，所有问题涌入 CI
2. mypy 存在历史遗留 errors，CI 的 mypy 步骤必然失败，开发者形成"CI 红是正常的"错误习惯（现已设为 `continue-on-error: true` + 版本对齐到 2.3.0）
3. ruff format 未在本地执行，67 个文件格式不规范，CI 的 `ruff format --check` 必然失败
4. CI 分支触发配置过时（引用已合并的 `refactor/v3-manager-agent-runtime` 分支）
5. **ruff 版本漂移**：本地 ruff 版本与 CI（`requirements.lock`）不一致，格式化结果不同，本地通过但 CI 失败
6. **依赖冲突未在本地暴露**：`requirements.lock` 中依赖版本冲突（如 `websockets==12.0` vs `uvicorn[standard]` 需 `>=13.0`），Windows pip 静默忽略，Linux CI 失败

**规则（强制，违反等同违反工程规范）**：
1. **Pre-commit hook 必须激活**。首次克隆仓库后执行 `bash scripts/install-hooks.sh`。Hook 会自动运行 ruff check + ruff format --check（后端）和 tsc + eslint（前端），任何一项失败阻止 commit。
2. **禁止提交已知会导致 CI 红的代码**。提交前必须确认：
   - `ruff check` 通过（0 errors）
   - `ruff format --check` 通过（0 files need reformatting）
   - `mypy` 不引入**新的** errors（CI 中 mypy 已设为 `continue-on-error` + 版本对齐到 2.3.0，不得新增）
3. **mypy 历史遗留 errors 是已知存量**（此前约 25 个，分布在 13 个文件），CI 中 mypy 步骤已设为 `continue-on-error: true`，不阻塞 CI。mypy 版本已从 1.10.0 对齐到 2.3.0（与本地一致），本地 mypy 2.3.0 显示 0 errors。如 CI 中 mypy 2.3.0 也通过，可在后续移除 `continue-on-error`。但每次提交不得新增 mypy errors——新增的必须当场修复。
4. **CI 分支触发配置必须与当前主干分支一致**。当前主干为 `main`，CI 触发分支为 `main`。如主干分支变更，必须同步更新 `.github/workflows/ci.yml`。
5. **`--no-verify` 跳过 hook 仅限紧急情况**（如修复 CI 本身故障），正常开发不得使用。使用后必须在后续 commit 中补回被跳过的检查。
6. **CI 红灯必须在 24 小时内修复**。不允许 CI 长期红灯继续开发。如果 CI 红灯是历史遗留（如 mypy），应在 CI 配置中标注 `continue-on-error` 而非放任不管。
7. **ruff 和 mypy 版本必须三处一致**（`requirements.lock` → `.pre-commit-config.yaml` `rev` → 本地安装版本）。修改 ruff/mypy 版本时必须同步更新这三处。Pre-commit hook 会自动校验本地 ruff 版本与 `requirements.lock` 是否一致，不一致时阻止提交并提示安装正确版本。mypy 虽不在 hook 中运行，但版本不一致同样会导致本地通过 CI 失败。
8. **依赖冲突必须在本地验证**。修改 `requirements.txt` / `requirements.lock` 后，必须运行 `pip install --dry-run -r requirements.lock` 验证无冲突。Pre-commit hook 已内置此检查（`requirements-lock-validate`）。
9. **ruff 配置变更时必须全量检查**。当 `requirements.lock` 或 `pyproject.toml` 变更时，Pre-commit hook 会自动对全部文件执行 ruff check + format，而非仅检查暂存文件——因为版本/规则变更可能影响所有文件的格式。
10. **pre-push Docker CI 一致性验证**。推送前自动在 Docker 容器中运行与 CI 完全相同的 ruff/mypy 检查（`scripts/docker-ci-check.sh`），确保"本地通过 = CI 通过"。Docker 未运行时自动跳过（不阻塞推送），但 CI 仍会检查。首次运行 ~30s（拉镜像 + pip install），后续 ~5s（pip cache volume 命中）。手动执行：`bash scripts/docker-ci-check.sh`。

**双层 Hook 防护体系**：

**[pre-commit] 秒级本地检查**（`.git/hooks/pre-commit`，由 `scripts/install-hooks.sh` 生成）：
- 不依赖 `pre-commit` pip 包，直接调用 `ruff` 和 `npx tsc`/`npm run lint`
- 不运行 pytest（需要 PostgreSQL/Redis，违反 §0.5.2，由 CI 的 `backend-integration-tests` job 负责）
- `.pre-commit-config.yaml` 保留作为 `pre-commit` 包的配置（`rev` 必须与 `requirements.lock` 中 ruff 版本一致）
- 三层防护：
  1. **版本校验**：提交前校验本地 ruff 版本 == `requirements.lock` 版本，不一致直接阻止提交
  2. **配置变更全量检查**：`requirements.lock` / `pyproject.toml` 变更时，对全部文件执行 ruff check + format
  3. **常规暂存文件检查**：正常提交时只检查暂存文件（ruff check + format + tsc + eslint + compose 校验）

**[pre-push] Docker CI 一致性验证**（`.git/hooks/pre-push`，由 `scripts/install-hooks.sh` 生成）：
- 脚本：`scripts/docker-ci-check.sh`
- 镜像：`swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/python:3.12-slim`（与项目 Dockerfile 一致）
- 用同一个 `requirements.lock` 安装 ruff/mypy，运行与 CI 完全相同的命令
- pip 缓存卷 `conclave-ci-pip-cache` 跨次运行复用，加速 pip install
- Docker 未运行时自动跳过（不阻塞推送，CI 仍会检查）
- mypy 与 CI 一致设为 `continue-on-error`（warnings 不阻塞推送）
- 手动执行：`bash scripts/docker-ci-check.sh`

**参考修复**：本次 CI 审查修复了 5 个 ruff check errors、67 个 ruff format 文件、1 个新增 mypy error、CI 分支触发过时、pre-commit hook 未安装。后续追加修复：websockets 依赖冲突（12.0→13.0）、RUF009+UP038 规则忽略、ruff 版本对齐（0.5.0→0.15.22 三处同步）、mypy 版本对齐（1.10.0→2.3.0 + continue-on-error）、pre-commit hook 三层防护（版本校验+全量检查+暂存检查）、pre-push Docker CI 一致性验证（彻底杜绝版本漂移）、qdrant_store.py mypy 类型修复。

---

## 5. 防止工程失控（工程纪律）

### 5.1 改动范围控制

- **一次提交只做一件事**。修 CI 就只修 CI，不要顺手重构不相关模块，不要顺手改 UI。
- **大改前先开 ADR**：如果要引入新架构/新依赖/新范式，先在 `docs/design/adr/` 写一篇 ADR（Accepted 后再动手），不要边写边设计。
- **单次 PR 控制在 400 行以内**（不含 lock 文件/生成代码）。超过就拆。

### 5.2 禁止"AI 凭感觉编码/写文档/评估问题"（Anti-Vibe-Coding）

**编码**：
- 不要凭"应该是这样吧"写代码。**读现有实现 → 理解数据流 → 改最小范围 → 跑测试验证**。
- 不要"先写了再说，等测试报错再修"。先理解函数签名、调用链、异常路径。
- 不要为了消一个类型错误就加 `# type: ignore` 或 `as any`。先理解为什么类型不对，治本。
- 不要批量自动修复 lint 错误然后提交。手工检查每个自动修复是否改变语义。

**写文档/评估问题（见 §4.16 §4.17）**：
- 不要凭记忆/推测写 README/ADR/待办。每一条事实性声明必须 grep 核验。
- 不要凭"应该是这个默认值"写配置说明。`grep config.py` 确认实际默认值。
- 不要凭"评审说的应该对"就认领问题。先 grep 核验问题是否真实存在，再决定认可/部分认可/不认可。
- 不要用"已记录待办"绕过可当场修复的问题。能当场修就当场修。
- 写完文档/待办后，用 grep 自查一遍每一条声明是否与代码一致。

### 5.3 禁止引入未授权依赖

- 后端加 pip 包：先确认 `requirements.txt` 中没有替代，且包维护活跃、license 兼容。
- 前端加 npm 包：优先用 React/Ant Design 原生能力，包大小 > 50KB gzipped 要慎重。
- **禁止用任何绕过 Playwright/浏览器指纹的库**，禁止用未审核的爬虫/注入工具。
- 加依赖后必须更新 lock 文件（`requirements.txt` 或 `package-lock.json`）。

### 5.4 配置与硬编码

- 环境变量集中在 `app/config.py` 或 `docker-compose*.yml`，**禁止硬编码 URL、Key、端口、路径**。
- 超时、重试次数、批大小等"魔数"必须加注释说明为什么是这个值，或抽到常量。
- LLM 温度严格按 ADR/design-principles：clarify/cross_team/evidence_check/arbitrate=0.0，intra_team=0.3，produce=0.1。

### 5.5 前端 UI 红线（参考 ui_design_system.yaml）

- 禁止：大面积渐变、3D 效果、重阴影（opacity > 0.1）、text-shadow、`!important`、动画 width/height、z-index=9999。
- 允许：4-8px 圆角、极轻阴影（0.04-0.06）、0.15s 颜色/透明度/transform 过渡。
- 品牌色：沉稳靛蓝 `#335c8e`。糖果色点缀 < 5% 面积。
- 中英文之间加半角空格。
- 列表倒序（最新在上，`ORDER BY created_at DESC`）。

### 5.6 数据模型红线

- Core 表（meetings、messages、events、users 等）加列必须考虑：迁移脚本（alembic）、`db_init.py` DDL、所有 DAO、schema 层、前端类型。
- 扩展字段优先走 `meetings.metadata JSONB`（ADR-002），以插件名为顶级键命名空间。
- 禁止跨插件写入 metadata（插件隔离）。
- DDL 变更必须考虑已有数据（默认值、NULL 处理、回滚策略）。

### 5.7 测试纪律

- **新增功能必须加测试**。Bug 修复先加能复现 bug 的失败用例，再修复。
- 测试禁止依赖外网（Bing/OpenAI 等）。必须 mock 或走 stub。
- 测试禁止依赖执行顺序。每个 test 必须独立可运行。
- 测试用例中的数据必须自包含，不要依赖其他测试留下的数据。
- Flaky 测试（偶发失败）必须修，不能简单 `@pytest.mark.skip` 绕过。

### 5.8 回退策略

- 改坏了就回滚，不要"我再改一下就好"无限叠加 patch。
- 复杂改动优先开 feature branch，验证通过再合并。
- 提交粒度要小，保证每个 commit 都能回退到可工作状态。

---

## 6. 文档索引

| 文档 | 用途 |
|---|---|
| `PROJECT_CONVENTIONS.md` | **唯一权威工程规范**（部署/构建/镜像源/提交/卡点） |
| `AGENTS.md` | 本文件，AI 助手实战纪律（就是你正在读的） |
| `docs/design/design-principles.md` | 11 条固化设计原则（RAG五原则、借调三问法、MVP三问等） |
| `docs/design/adr/001-008` | 架构决策记录（插件化/JSONB/插件分级/钩子/排序/JWT/配额等） |
| `docs/RETROSPECTIVE_CONVENTIONS.md` | 修复报告归档规范（HTML 格式、commit 区间、13 种错误模式） |
| `docs/conclave-sandbox-directory-standard.md` | 沙箱目录规范 |
| `docs/report-layout-spec.md` | 报告布局 Spec 规范 |
| `backend/app/skills/code_conventions.yaml` | 代码生成正面规范（API 设计、安全、Docker） |
| `backend/app/skills/ui_design_system.yaml` | UI 设计系统（色板、排版、形状、CSS 反模式） |
| `backend/app/skills/communication_style.yaml` | Agent 发言风格（中文、方括号标签、禁止 emoji 等） |
| `backend/app/skills/deliverable_quality.yaml` | 产出验收标准（critical/high 等级） |
| `.pre-commit-config.yaml` | 预提交卡点配置 |
| `.github/workflows/ci.yml` | CI 流水线定义（6 个 job） |

---

## 7. 遇到问题时

1. **先搜后问**：用 grep/ripgrep 搜错误信息、函数名，看现有代码怎么处理的。
2. **看 ADR**：架构/数据模型问题 90% 在 `docs/design/adr/` 里有答案。
3. **看历史修复报告**：`docs/retrospectives/` 里记录了 13 种典型错误模式和修复方式。
4. **最小复现**：遇到 bug 先写最小复现脚本/测试，不要在大流程里猜。
5. **不要硬绕**：遇到 asyncio 循环/数据库连接/Playwright 挂死这类底层问题，先看本文件第 4 节。

---

## 8. PowerShell / Windows 注意事项

本项目主要在 Windows（PowerShell）下开发：

- 命令链接用 `;`，**不要用 `&&`**（PowerShell 不支持）。
- 路径含空格必须用单引号包裹：`cd 'C:\Users\Some User\project'`。
- `Get-Content`、`Select-Object`、`Select-String` 是 PowerShell 等价的 cat/head/grep。
- 容器内是 Linux，shell 脚本用 bash 语法。
- `.gitattributes` 已配置行尾：`.sh`/`Dockerfile*` 强制 LF，`.ps1`/`.bat`/`.cmd` 保持 CRLF。
- **docker compose run 输出捕获陷阱**：PowerShell 下 `docker compose run` 的 stdout 会被 PowerShell 当作 stderr 处理（`NativeCommandError`），导致 `2>&1` 和 `Out-File` 捕获不到容器内 pytest 输出。解决方案：用 `Start-Process -RedirectStandardOutput` + `-RedirectStandardError` 分别重定向，或直接用 `docker run` 替代 `docker compose run`。

---

> 本文件最后更新：2026-07-22（§4.18 新增规则 7-10 + 双层 Hook 防护体系、ruff 0.5.0→0.15.22 三处对齐、mypy 1.10.0→2.3.0 对齐 + continue-on-error、pre-commit hook 三层防护、pre-push Docker CI 一致性验证、qdrant_store.py 类型修复）。若发现新的高频坑，追加到第 4 节并更新日期。
