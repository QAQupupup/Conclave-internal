# AGENTS.md — Conclave 项目 AI 助手指南

> 本文件是 AI 编码助手（Cursor / Trae / Windsurf / Copilot / Claude Code 等）在本项目工作时的**第一入口**。开始工作前必须阅读本文件。
>
> 本文件只放"实战纪律"和"踩坑索引"。完整的工程规范见 `PROJECT_CONVENTIONS.md`（唯一权威规范），设计原则见 `docs/design/design-principles.md`，ADR 见 `docs/design/adr/`，UI 规范见 `backend/app/skills/ui_design_system.yaml`，踩坑详情见 `docs/pitfalls.md`。

---

## 0. 开始工作前 30 秒

1. 读 `PROJECT_CONVENTIONS.md` 第 1、4、8 节（部署原则、提交规范、预提交卡点）。
2. 读本文件全文（下面所有章节）。
3. **读 `SKILL_REGISTRY.md` 了解可用 Skill**——AI 助手根据任务上下文自动调用相关 Skill，用户无需主动提及。
4. 如果要改 UI，读 `backend/app/skills/ui_design_system.yaml`。
5. 如果要改架构/数据模型，读 `docs/design/adr/` 下相关 ADR。
6. 如果要写修复报告，读 `docs/RETROSPECTIVE_CONVENTIONS.md`。
7. 开始编码前，用 `git status` 确认工作区干净，避免无关文件混入提交。
8. **如果要写/改文档（README/ADR/待办）**，必须先读 `docs/pitfalls.md` P21（文档真实性核查）。每一条事实性声明必须 grep 核验，禁止凭记忆写文档。
9. **如果要回应代码审查/外部评审**，必须先读 `docs/pitfalls.md` P22（问题评估与绕过检查）。逐条 grep 核验问题是否真实存在，禁止"声明式修复"。
10. **如果要碰异步/数据库/Docker/测试/编排器代码**，根据 §4 类别索引读 `docs/pitfalls.md` 对应章节；**任何 DB 读写/查询/分页/迁移代码，先读 `docs/sql-development-rules.md`（SQL 开发守则）**。
11. **新会话恢复上下文**：如果用户说"继续"/"恢复"/"上次说到哪了"，先读 `D:\conclave-knowledge-vault\project-context\current-status.md` 获取最新检查点指针，再读检查点文件恢复上下文（见 §9）。

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
| 前端 | React 19 + TypeScript + Vite + Tailwind CSS v4 + Radix UI + Zustand + TanStack Query | 入口 `app.html`（非 `index.html`），路径别名 `@ → src/` |
| 测试 | pytest + pytest-asyncio + Vitest + Playwright | 集成测试必须走 Docker Compose |
| 部署 | Docker Compose（多阶段构建强制） | 禁止本地直接 `python main.py` / `npm run dev` 跑服务 |
| 镜像源 | pip 清华 TUNA / npm npmmirror / apt 清华 / Docker 华为 SWR | 所有依赖必须国内源 |

---

## 2. 提交前必做清单（Pre-Flight Checklist）

**每次 `git commit` 前必须逐项确认，不得跳过：**

> **双层 Hook 已激活**：pre-commit（秒级 ruff/tsc/eslint）+ pre-push（Docker CI 一致性验证）。
> Hook 安装：`bash scripts/install-hooks.sh`（首次克隆仓库后执行一次）。
> Hook 配置详见 `PROJECT_CONVENTIONS.md` §8，CI 稳定性详见 `docs/ci-stability-guide.md`。
> 如 hook 未安装，以下手动检查必须逐项执行。

### 2.1 后端
- [ ] `cd backend && python -m ruff check app conclave_core tests` → **0 errors**
- [ ] `cd backend && python -m ruff format --check app conclave_core tests` → **0 files need reformatting**
- [ ] `cd backend && python -m mypy --config-file pyproject.toml app conclave_core` → **0 新增 errors**（mypy 2.3.0 本地显示 0 errors，见 `docs/pitfalls.md` P15，不得新增）
- [ ] 若改了 ORM 模型，确认模型字段一致，并通过 Alembic 迁移更新 DDL（`db_init.py` 手写 DDL 已于 2026-08 废弃，建表统一 create_all + Alembic，见 `docs/sql-development-rules.md` §5）
- [ ] 若改了 API 路由，确认所有路径都在前端 `vite.config.ts` 的 proxy 列表和 `nginx.conf` 中
- [ ] **若新增/修改了函数，确认有对应单元测试且测试 import 了真实函数**（`testing-rules` §1）
- [ ] **若修改了配对函数（hash/verify、encode/decode、create/verify），确认有往返测试**（`testing-rules` §3）
- [ ] **若修改了认证/安全代码，确认 `test_password_hash.py` 通过 + 手动 curl 登录返回 200**（`testing-rules` §4）
- [ ] **确认新增测试无反模式**：无逻辑副本、无 `try/except:pass`、无空断言、无被测函数自身被 mock（`testing-rules` §1-2）
- [ ] **确认测试不是纯快乐路径**：每个测试文件至少 1 个非正向测试（异常/边界/越权/并发/极限/降级，`testing-rules` §9）

### 2.2 前端
- [ ] `cd frontend && npx eslint .` → 无新增 error（warnings 遵循现有宽松策略）
- [ ] `cd frontend && npx tsc -b --noEmit` → **0 errors**
- [ ] `cd frontend && npm run build` → 构建成功（CI 会跑）
- [ ] 若改了路由，确认 `App.tsx` 中有对应 `<Route>`，`nginx.conf` 有 fallback
- [ ] **若新增/修改了组件或 hook，确认有对应测试且测试 import 了真实组件**（`testing-rules` §1）
- [ ] **确认前端测试无 `.not.toThrow()` 作为唯一断言**（`testing-rules` §2）

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

遵循 Conventional Commits 规范，完整 type/scope 列表见 `PROJECT_CONVENTIONS.md` §4.1。

格式：`<type>(<scope>): <中文描述>`，body 说明为什么改，footer 用 `Refs:` 引用修复报告。

type: `feat`/`fix`/`refactor`/`docs`/`test`/`chore`/`perf`/`style`/`ci`。scope: `backend`/`frontend`/`docker`/`orchestrator`/`agents`/`tools`/`db`/`auth`/`docs`。

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

## 4. 高频踩坑清单（按需加载）

> 29 个踩坑子节已迁移到 `docs/pitfalls.md`（按类别分组，P1-P29）。
> 本节只保留类别索引——根据当前任务类型，读对应类别即可。

| 类别 | pitfalls.md 章节 | 何时读 |
|------|-----------------|--------|
| 异步/事件循环 | P1-P2 | 改 asyncio 代码、遇到事件循环报错 |
| Docker/部署 | P3-P4 | 改 Dockerfile/compose、Playwright 依赖 |
| 数据库/ORM | P5-P10 | 改 ORM 模型、DDL、多租户、Alembic |
| SQL 开发守则 | `docs/sql-development-rules.md` | 任何 DB 读写/查询/分页/迁移代码，改前必读 |
| 测试 | P11-P14, P27 | 写/改测试、fixture、断言、测试质量 |
| 测试守则 | `docs/testing-rules.md` | 测试纪律全文（五级标签），§5.7 摘要背后 |
| CI/Git | P15-P17 | 提交、推送、hook 问题 |
| 编排器 | P18-P20 | 改 runner/nodes/门禁 |
| 文档质量 | P21-P22 | 写文档、回应代码审查 |
| 杂项 | P23-P26 | 前端 TS/ESLint、import 取舍、Alembic env |
| AI 助手文件操作纪律 | P28-P29 | 用 PowerShell 改记忆文件/vault 指针/配置等关键文件 |

**最常踩的 3 个坑**（每次必读）：
1. **P1 asyncio 事件循环**——改任何 async 代码前必读，是项目最常见大坑
2. **P8 多租户隔离 Checklist**——改任何业务表前必读，漏一个 DAO 就跨租户泄露
3. **P15 CI 稳定性纪律**——提交前必读，ruff/mypy 版本不一致就 CI 红

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
- **单一职责与可读性**：每个函数只做一件事，函数体过长就拆分；类继承关系清晰，函数内部逻辑不可混乱；命名与控制流对人和 LLM 都友好，避免晦涩技巧（2026-09-04 裁决固化的开发规范）。

**写文档/评估问题（见 `docs/pitfalls.md` P21-P22）**：
- 不要凭记忆/推测写 README/ADR/待办。每一条事实性声明必须 grep 核验。
- 不要凭"应该是这个默认值"写配置说明。`grep config.py` 确认实际默认值。
- 不要凭"评审说的应该对"就认领问题。先 grep 核验问题是否真实存在，再决定认可/部分认可/不认可。
- 不要用"已记录待办"绕过可当场修复的问题。能当场修就当场修。
- 写完文档/待办后，用 grep 自查一遍每一条声明是否与代码一致。

### 5.3 禁止引入未授权依赖

- 后端加 pip 包：先确认 `requirements.txt` 中没有替代，且包维护活跃、license 兼容。
- 前端加 npm 包：优先用 Radix UI + Tailwind 原生能力，包大小 > 50KB gzipped 要慎重。
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

- Core 表（meetings、messages、events、users 等）加列必须考虑：Alembic 迁移脚本、所有 DAO、schema 层、前端类型（`db_init.py` 手写 DDL 已于 2026-08 废弃，见 `docs/sql-development-rules.md` §5.3）。
- 扩展字段优先走 `meetings.metadata JSONB`（ADR-002），以插件名为顶级键命名空间。
- 禁止跨插件写入 metadata（插件隔离）。
- DDL 变更必须考虑已有数据（默认值、NULL 处理、回滚策略）。

### 5.7 测试纪律（强制，详见测试守则）

> 测试纪律的完整规则已迁出至 `docs/testing-rules.md`（测试开发守则），本节只留红线摘要索引。
> 违反任何一条等同于违反工程规范，CI 有权拒绝合并。

| 标签 | 摘要 | 完整规则 |
|------|------|---------|
| 【绝对禁止】 | 测试不得用逻辑副本、不得 mock 被测函数本身、无断言测试、`assert True`/空函数、`.not.toThrow()` 作唯一断言、`try/except:pass` 吞异常 | `testing-rules` §1-2 |
| 【红线】 | 配对函数（hash/verify 等）必须有往返测试，无往返测试禁止合并 | `testing-rules` §3 |
| 【红线】 | 关键安全函数（auth.py、auth middleware、csrf、tenants/service）必须有专项测试文件 | `testing-rules` §4 |
| 【红线】 | 测试禁止依赖外部状态（外网/执行顺序/其他测试数据）；skip 是技术债需说明理由 | `testing-rules` §5 |
| 【红线】 | 测试必须在被测代码出错时失败；Bug 修复先加失败用例；禁止削弱断言通过 | `testing-rules` §6 |
| 【绝对禁止】 | 禁止快乐路径唯一测试：每个测试文件至少 1 个非正向测试，新函数须覆盖 ≥2 个非正向维度 | `testing-rules` §9 |

> 测试执行时机（新增/改后端跑容器内测试、改认证跑 `test_password_hash.py`、部署前重建镜像等）见 `docs/testing-rules.md` §8。

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
| `SKILL_REGISTRY.md` | Skill 索引——AI 助手自动发现和调用 Skill 的入口 |
| `docs/pitfalls.md` | **高频踩坑清单**（29 条，按类别分组，从 AGENTS.md §4 拆出） |
| `docs/sql-development-rules.md` | **SQL 开发守则**（五级标签：模型/查询/写入/分页/迁移/原生SQL例外） |
| `docs/testing-rules.md` | **测试开发守则**（五级标签：验证真实代码/断言/往返测试/安全函数/外部状态/回归/快乐路径） |
| `docs/design/design-principles.md` | 11 条固化设计原则（RAG五原则、借调三问法、MVP三问等） |
| `docs/design/adr/001-018` | 架构决策记录（插件化/JSONB/插件分级/钩子/排序/JWT/配额/sections 迁移/论点提纯/会话检查点/状态机契约/动态工作流/prompt回归测试/代码知识图谱/产物链与议题池/代码库理解层） |
| `docs/RETROSPECTIVE_CONVENTIONS.md` | 修复报告归档规范（HTML 格式、commit 区间、13 种错误模式） |
| `docs/ci-stability-guide.md` | CI 稳定性详细指南（双层 Hook 体系、历史修复记录，P15 的补充） |
| `docs/conclave-sandbox-directory-standard.md` | 沙箱目录规范 |
| `docs/report-layout-spec.md` | 报告布局 Spec 规范 |
| `backend/app/skills/code_conventions.yaml` | 代码生成正面规范（API 设计、安全、Docker） |
| `backend/app/skills/ui_design_system.yaml` | UI 设计系统（色板、排版、形状、CSS 反模式） |
| `backend/app/skills/communication_style.yaml` | Agent 发言风格（中文、方括号标签、禁止 emoji 等） |
| `backend/app/skills/deliverable_quality.yaml` | 产出验收标准（critical/high 等级） |
| `.pre-commit-config.yaml` | 预提交卡点配置（`rev` 必须与 `requirements.lock` 一致） |
| `.github/workflows/ci.yml` | CI 流水线定义（6 个 job） |

---

## 7. 遇到问题时

1. **先搜后问**：用 grep/ripgrep 搜错误信息、函数名，看现有代码怎么处理的。
2. **看 ADR**：架构/数据模型问题 90% 在 `docs/design/adr/` 里有答案。
3. **看踩坑清单**：`docs/pitfalls.md` 里记录了 29 个高频坑和修复方式。
4. **看历史修复报告**：`docs/retrospectives/` 里记录了 13 种典型错误模式和修复方式。
5. **最小复现**：遇到 bug 先写最小复现脚本/测试，不要在大流程里猜。
6. **不要硬绕**：遇到 asyncio 循环/数据库连接/Playwright 挂死这类底层问题，先看 `docs/pitfalls.md` 异步/事件循环和 Docker/部署类别。

---

## 8. PowerShell / Windows 注意事项

本项目主要在 Windows（PowerShell）下开发：

- 命令链接用 `;`，**不要用 `&&`**（PowerShell 不支持）。
- 路径含空格必须用单引号包裹：`cd 'C:\Users\Some User\project'`。
- `Get-Content`、`Select-Object`、`Select-String` 是 PowerShell 等价的 cat/head/grep。
- 容器内是 Linux，shell 脚本用 bash 语法。
- `.gitattributes` 已配置行尾：`.sh`/`Dockerfile*` 强制 LF，`.ps1`/`.bat`/`.cmd` 保持 CRLF。
- **docker compose run 输出捕获陷阱**：PowerShell 下 `docker compose run` 的 stdout 会被 PowerShell 当作 stderr 处理（`NativeCommandError`），导致 `2>&1` 和 `Out-File` 捕获不到容器内 pytest 输出。解决方案：用 `Start-Process -RedirectStandardOutput` + `-RedirectStandardError` 分别重定向，或直接用 `docker run` 替代 `docker compose run`。
- **PowerShell 非终结错误陷阱（P28）**：.NET 方法调用异常默认是非终结错误，脚本会带伤继续执行后续写盘操作，曾导致关键记忆文件被截断且无备份可恢复。写盘脚本必须设 `$ErrorActionPreference = 'Stop'`；关键文件修改前先备份；优先整文件读写（`ReadAllText → Replace → 校验命中 → WriteAllText`），禁止无校验的行切片拼接；写盘后读回验证。
- **.ps1 脚本中文编码（P29）**：PowerShell 5 对无 BOM 的 .ps1 按系统 ANSI（GBK）读取，中文常量会乱码并触发解析错误。脚本与数据分离：.ps1 只保留纯 ASCII 逻辑，中文内容写入独立 UTF-8 数据文件。

---

## 9. 会话持久化与跨窗口连续性

> 完整流程见 `session-checkpoint` skill（`.trae/skills/session-checkpoint/SKILL.md`）和 ADR-012。
> 本节只保留快速参考。

**核心机制**：Index+Raw 2 层架构，检查点写入 `D:\conclave-knowledge-vault\`（不进 Git）。

**存档触发**：用户说"存档"/"保存进度"/"checkpoint"/"切换窗口"/阶段性任务完成。
**恢复触发**：用户说"继续"/"恢复"/"上次说到哪了"/"resume"。

**存档 5 步**：生成索引层 `.md` → 生成原文层 `.raw.md` → 更新月度索引 `index.md` → 更新 `current-status.md` 指针 → 更新 `project_memory.md` 顶部指针。

**恢复 3 步**：读 `current-status.md` 获取索引层路径 → 读索引层 + 必读锚点 → 输出恢复摘要，等待确认。

**隐私边界**：会话内容（决策/沟通/待办）不进 Git，只存 vault。`project_memory.md` 只留指针（路径+时间+一句话任务）。

**写盘纪律**：修改 `project_memory.md`、`current-status.md` 等关键文件必须遵守 `docs/pitfalls.md` P28/P29——先备份、整文件读写、PowerShell 设 `$ErrorActionPreference='Stop'`、写后验证。完整规程见 `session-checkpoint` skill「关键文件安全写盘纪律」节。

---

> 本文件最后更新：2026-09-04（修正 DDL 单一真相源收敛后的失真表述：`db_init.py` 手写 DDL 已于 2026-08 废弃，踩坑数 26→29，ADR 范围 001-015→001-018；此前：§4 新增 P28/P29 AI 助手文件操作纪律类别；§5.2 新增单一职责/函数拆分开发规范；§8 新增 PowerShell 非终结错误与 .ps1 中文编码陷阱；§9 新增关键文件安全写盘纪律）。若发现新的高频坑，追加到 `docs/pitfalls.md` 对应类别并更新本文件 §4 索引。
