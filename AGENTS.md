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
10. **如果要碰异步/数据库/Docker/测试/编排器代码**，根据 §4 类别索引读 `docs/pitfalls.md` 对应章节。
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
- [ ] 若改了 ORM 模型，确认 `app/dao/db_init.py` 的 DDL 与模型字段一致（尤其是新增列/默认值/JSONB）
- [ ] 若改了 API 路由，确认所有路径都在前端 `vite.config.ts` 的 proxy 列表和 `nginx.conf` 中
- [ ] **若新增/修改了函数，确认有对应单元测试且测试 import 了真实函数**（§5.7.1）
- [ ] **若修改了配对函数（hash/verify、encode/decode、create/verify），确认有往返测试**（§5.7.3）
- [ ] **若修改了认证/安全代码，确认 `test_password_hash.py` 通过 + 手动 curl 登录返回 200**（§5.7.4）
- [ ] **确认新增测试无反模式**：无逻辑副本、无 `try/except:pass`、无空断言、无被测函数自身被 mock（§5.7）
- [ ] **确认测试不是纯快乐路径**：每个测试文件至少 1 个非正向测试（异常/边界/越权/并发/极限/降级，§5.7.9）

### 2.2 前端
- [ ] `cd frontend && npx eslint .` → 无新增 error（warnings 遵循现有宽松策略）
- [ ] `cd frontend && npx tsc -b --noEmit` → **0 errors**
- [ ] `cd frontend && npm run build` → 构建成功（CI 会跑）
- [ ] 若改了路由，确认 `App.tsx` 中有对应 `<Route>`，`nginx.conf` 有 fallback
- [ ] **若新增/修改了组件或 hook，确认有对应测试且测试 import 了真实组件**（§5.7.1）
- [ ] **确认前端测试无 `.not.toThrow()` 作为唯一断言**（§5.7.2）

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

> 26 个踩坑子节已迁移到 `docs/pitfalls.md`（按类别分组，P1-P26）。
> 本节只保留类别索引——根据当前任务类型，读对应类别即可。

| 类别 | pitfalls.md 章节 | 何时读 |
|------|-----------------|--------|
| 异步/事件循环 | P1-P2 | 改 asyncio 代码、遇到事件循环报错 |
| Docker/部署 | P3-P4 | 改 Dockerfile/compose、Playwright 依赖 |
| 数据库/ORM | P5-P10 | 改 ORM 模型、DDL、多租户、Alembic |
| 测试 | P11-P14, P27 | 写/改测试、fixture、断言、测试质量 |
| CI/Git | P15-P17 | 提交、推送、hook 问题 |
| 编排器 | P18-P20 | 改 runner/nodes/门禁 |
| 文档质量 | P21-P22 | 写文档、回应代码审查 |
| 杂项 | P23-P26 | 前端 TS/ESLint、import 取舍、Alembic env |

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

- Core 表（meetings、messages、events、users 等）加列必须考虑：迁移脚本（alembic）、`db_init.py` DDL、所有 DAO、schema 层、前端类型。
- 扩展字段优先走 `meetings.metadata JSONB`（ADR-002），以插件名为顶级键命名空间。
- 禁止跨插件写入 metadata（插件隔离）。
- DDL 变更必须考虑已有数据（默认值、NULL 处理、回滚策略）。

### 5.7 测试纪律（硬性规则，不可绕过）

> 本节规则是强制性的。违反任何一条等同于违反工程规范，CI 有权拒绝合并。
> 历史教训：`verify_password` 段数检查 bug（4 段 vs 5 段）导致所有登录 401，
> 该函数零测试覆盖。`test_role_matching.py` 测试逻辑副本而非真实函数。
> 这些不是个例，是系统性测试失效。

#### 5.7.1 测试必须验证真实代码

- **禁止测试逻辑副本**。测试必须 `import` 并调用真实的被测函数，不允许在测试文件中重新实现一份"保持一致"的逻辑。如果被测函数变更，副本不会自动更新，测试通过但真实代码可能有 bug。
  - 错误：`def _match_role(role_str): ...  # 从 nodes.py 提取的匹配逻辑`
  - 正确：`from app.orchestrator.nodes import _match_role`
- **禁止 mock 被测函数本身**。mock 只能用于被测函数的依赖（数据库、外部 API、LLM）。如果被测函数被 mock 了，测试验证的是 mock 行为而非真实代码。
- **测试必须 import 真实模块路径**，不能通过 `sys.path` hack 或动态加载绕过正常 import 链。

#### 5.7.2 测试必须有有意义断言

- **每个测试函数至少一个断言**。无断言的测试函数（仅调用函数不验证结果）不算测试，必须删除或补全断言。
- **禁止 `assert True` / `pass` / 空函数体**作为测试。测试通过必须有可验证的原因。
- **禁止 `.not.toThrow()` 作为唯一断言**（前端）。必须跟具体的 DOM/状态/返回值断言。"没崩溃"不等于"功能正确"。
- **断言必须验证具体值**，不能只验证类型或存在性。`assert result is not None` 太弱，应改为 `assert result.status == "active"`。
- **异常测试必须用 `pytest.raises` / `expect().toThrow()`**，禁止 `try/except: pass` 吞掉异常后继续执行。吞掉异常意味着你不知道函数是否抛了预期的异常。

#### 5.7.3 配对函数必须有往返测试

以下配对函数类型，提交时必须附带"正向验证通过 + 反向验证拒绝"的往返测试：

| 配对类型 | 示例 | 必须覆盖 |
|---------|------|---------|
| hash/verify | `hash_password` / `verify_password` | 正确密码通过 + 错误密码拒绝 |
| encode/decode | `_b64url_encode` / `_b64url_decode` | 往返一致 + 格式校验 |
| create/verify | `create_jwt` / `verify_jwt` | 有效 token 通过 + 篡改 token 拒绝 + 过期 token 拒绝 |
| encrypt/decrypt | 任何加解密对 | 往返一致 + 密钥错误拒绝 |
| serialize/deserialize | `model_dump` / `model_validate` | 往返一致 + 格式错误拒绝 |

**没有往返测试的配对函数，禁止合并。** 这是 `verify_password` 401 bug 的直接预防措施。

#### 5.7.4 关键安全函数必须有专项测试

以下函数是认证/安全的心脏，必须有独立的测试文件覆盖：

- `app/auth.py`：`hash_password` / `verify_password` / `create_jwt` / `verify_jwt` / `authenticate_user`
- `app/plugins/builtin/auth/middleware.py`：Cookie 解析、token 提取
- `app/plugins/builtin/auth/csrf.py`：CSRF token 生成与验证
- `app/tenants/service.py`：租户隔离（跨租户数据不可见）

新增安全相关函数时，同步新增对应测试文件。无测试的安全函数禁止合并。

#### 5.7.5 测试禁止依赖外部状态

- 测试禁止依赖外网（Bing/OpenAI 等）。必须 mock 或走 stub。
- 测试禁止依赖执行顺序。每个 test 必须独立可运行（`pytest -p no:randomly` 随机顺序也能过）。
- 测试用例中的数据必须自包含，不要依赖其他测试留下的数据。
- Flaky 测试（偶发失败）必须修，不能简单 `@pytest.mark.skip` 绕过。
- **`@pytest.mark.skip` / `skipif` 是技术债务，不是解决方案**。每个 skip 必须在注释中说明：(1) 为什么跳过 (2) 什么条件下恢复运行 (3) 恢复的责任人。模块级 skip（整个文件跳过）必须在 `docs/pitfalls.md` 或 issue 中有对应记录。

#### 5.7.6 测试必须能检测代码回归

- **测试必须在被测代码出 bug 时失败**。如果一个测试无论代码是否正确都能通过，它不是测试，是噪音。验证方法：故意改坏被测代码（如把 `==` 改成 `!=`），确认测试失败。
- **Bug 修复必须先加失败用例**。先写一个能复现 bug 的测试（此时应失败），再修复代码（此时应通过）。禁止"先修后测"。
- **禁止通过削弱断言来让测试通过**。如果测试失败，应该修代码或修测试断言值（需 grep 确认真实返回值），不能把 `assert x == 5` 改成 `assert x is not None` 来强行通过。

#### 5.7.7 测试代码质量等于生产代码质量

- 测试文件必须通过 `ruff check` 和 `ruff format`。
- 测试函数命名必须与断言一致（`test_xxx_has_strength_weak` 不能断言 `"none"`）。
- 测试必须有 docstring 说明验证的场景（一句话即可）。
- 测试中禁止硬编码 magic number 而不说明来源（如 `assert len(result) == 7  # 7 个角色`）。

#### 5.7.8 测试执行时机（何时必须跑测试）

| 时机 | 必须执行的操作 | 验证标准 |
|------|--------------|---------|
| 新增/修改后端函数 | Docker 容器内跑相关测试文件 | 0 failed |
| 新增/修改前端组件 | `npx vitest run` 相关测试文件 | 0 failed |
| 修改认证/安全代码 | 跑 `test_password_hash.py` + 手动 curl 登录验证 | 登录返回 200 |
| 修改 ORM 模型 | 跑全量后端测试（模型变更影响面大） | 0 failed |
| `git commit` 前 | pre-commit hook（ruff/mypy/tsc/eslint） | 0 errors |
| `git push` 前 | pre-push hook（Docker CI 一致性） | 0 failed |
| 后端代码变更后部署 | `docker compose up -d --build backend`（必须重建镜像） | 容器 healthy |

#### 5.7.9 禁止"快乐路径唯一测试"（多维度测试强制要求）

> 大模型和 Agent 天然擅长写正向测试——给定正常输入，断言正常输出。
> 但正向测试通过 ≠ 功能正确。项目的系统性 bug（阶段跳过、角色丢失、并发竞争、
> 证据缺失）全部发生在正向测试覆盖的"正常路径"之外。
> **只写快乐路径的测试等同于没有测试。**

**强制维度覆盖**：每个新增/修改的函数或模块，除正向测试外，必须至少覆盖以下维度中的 **2 项**（安全/认证类函数必须覆盖"异常 + 越权"）：

| 维度 | 含义 | 典型场景 |
|------|------|---------|
| 边界值 | 输入在极限/临界点 | 空列表、单元素、最大长度、off-by-one、零/负数 |
| 异常路径 | 被测代码应抛错或降级 | LLM 返回 `success=False`、网络超时、格式错误、缺字段 |
| 权限/越权 | 跨用户/跨租户数据隔离 | 用户 A 访问用户 B 的会议、未认证请求、过期 token |
| 并发竞争 | 多线程/协程同时访问 | `asyncio.gather` 并发写 `shared_state`、`compute` 单例竞态 |
| 极限条件 | 超大输入或高负载 | 100+ claims、50+ conflicts、10K 字符 topic、空 `team_config` |
| 回退/降级 | 主流程失败后的兜底路径 | LLM 不可用走 StubLLM、RAG 检索失败走空证据、Cython `.so` 缺失走 `.py` |

**判定标准**（Code Review 时逐项检查）：

1. **每个测试文件至少 1 个非正向测试**。纯 happy-path 测试文件禁止合并。
2. **Stub/Mock 必须有失败分支**。StubCompute 不能只返回 `success=True`，必须覆盖 `success=False` 和格式异常。
3. **状态机/路由测试必须验证非法跳转被拒绝**。不能只测"正确跳转"，必须测"非法跳转被拦截"（如 INTRA_TEAM 不能直接到 EVIDENCE_CHECK）。
4. **并发模块必须有并发测试**。使用 `asyncio.gather` 或 `ThreadPoolExecutor` 模拟并发，断言结果一致性或竞态安全。
5. **有兜底逻辑的函数必须测兜底分支**。`try/except`、`if not x: fallback`、`or default` 等兜底路径必须有对应测试。

**反模式（禁止）**：
- 只测正常输入 + 正常输出，不测异常输入
- Stub 只返回成功，不返回失败
- 只测"能跳到下一阶段"，不测"不能跳过阶段"
- 并发模块只有串行测试
- `assert result is not None` 作为唯一断言（§5.7.2 已禁止，这里重申）

**正面模式（鼓励）**：
- 参数化测试覆盖边界值：`@pytest.mark.parametrize("input,expected", [...])`
- Stub 支持 `mode` 参数切换成功/失败/超时
- 测试非法操作被拒绝：`with pytest.raises(...)` 或断言返回错误码
- 并发测试：`await asyncio.gather(*[worker() for _ in range(N)])` + 断言最终状态一致

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
| `docs/pitfalls.md` | **高频踩坑清单**（26 条，按类别分组，从 AGENTS.md §4 拆出） |
| `docs/design/design-principles.md` | 11 条固化设计原则（RAG五原则、借调三问法、MVP三问等） |
| `docs/design/adr/001-015` | 架构决策记录（插件化/JSONB/插件分级/钩子/排序/JWT/配额/sections 迁移/论点提纯/会话检查点/状态机契约/动态工作流/prompt回归测试） |
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
3. **看踩坑清单**：`docs/pitfalls.md` 里记录了 26 个高频坑和修复方式。
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

---

> 本文件最后更新：2026-07-30（§4 拆分到 `docs/pitfalls.md`，26 个子节改为 P1-P26 按类别分组；§9 精简为指针指向 session-checkpoint skill；§0 添加 SKILL_REGISTRY.md 和 pitfalls.md 引用；§6 文档索引添加 pitfalls.md 和 SKILL_REGISTRY.md；§7 引用更新为 pitfalls.md。体积从 684 行/46.8KB 精简到 ~270 行/~18KB，减少 60%）。若发现新的高频坑，追加到 `docs/pitfalls.md` 对应类别并更新本文件 §4 索引。
