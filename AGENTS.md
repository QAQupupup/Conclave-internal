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

### 2.1 后端
- [ ] `cd backend && python -m ruff check app conclave_core tests` → **0 errors**
- [ ] `cd backend && python -m mypy --config-file pyproject.toml app conclave_core` → **0 errors**
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

- 当前主开发分支：`refactor/v3-manager-agent-runtime`
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

---

## 5. 防止工程失控（工程纪律）

### 5.1 改动范围控制

- **一次提交只做一件事**。修 CI 就只修 CI，不要顺手重构不相关模块，不要顺手改 UI。
- **大改前先开 ADR**：如果要引入新架构/新依赖/新范式，先在 `docs/design/adr/` 写一篇 ADR（Accepted 后再动手），不要边写边设计。
- **单次 PR 控制在 400 行以内**（不含 lock 文件/生成代码）。超过就拆。

### 5.2 禁止"AI 凭感觉编码"（Anti-Vibe-Coding）

- 不要凭"应该是这样吧"写代码。**读现有实现 → 理解数据流 → 改最小范围 → 跑测试验证**。
- 不要"先写了再说，等测试报错再修"。先理解函数签名、调用链、异常路径。
- 不要为了消一个类型错误就加 `# type: ignore` 或 `as any`。先理解为什么类型不对，治本。
- 不要批量自动修复 lint 错误然后提交。手工检查每个自动修复是否改变语义。

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

---

> 本文件最后更新：2026-07-20（Phase 1b 多租户数据模型完成：tenants 表、User-Tenant 关联、核心业务表 tenant_id 列、JWT claims 集成、ContextVar、DAO 层自动过滤、默认租户迁移；Phase 0 插件框架 + Phase 1a Auth CORE 插件已完成）。若发现新的高频坑，追加到第 4 节并更新日期。
