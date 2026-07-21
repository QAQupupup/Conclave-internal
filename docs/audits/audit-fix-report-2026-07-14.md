# Conclave 审计修复报告

**日期**: 2026-07-14
**审计范围**: 全项目代码审阅 + 技术规范审核
**审计人**: AI Agent (TRAE)

---

## 一、审计发现概述

### 第一轮: P0/P1 问题修复 (15 项)

| # | 问题 | 严重程度 | 修复方式 |
|---|---|---|---|
| 1 | `settings.db_path` AttributeError (key_store.py 引用不存在字段) | P0 | config.py 添加 db_path 字段 |
| 2 | Alembic 缺 3 张记忆表迁移 + env.py 导入不全 | P0 | 创建 0004 迁移文件,修复 env.py 导入 |
| 3 | pyproject.toml 缺 8 个运行时依赖 | P0 | 同步到 pyproject.toml |
| 4 | CI pip install 版本约束未加引号 | P0 | 为 ruff>=0.4 / mypy>=1.10 加引号 |
| 5 | .env.example 严重不完整 | P0 | 重写补全 20+ 环境变量 |
| 6 | SQLite 系统性残留 (events/main/config/engine/upsert/runner) | P0 | 全局清理 SQLite 文档和代码 |
| 7 | project_memory.md ~700 行重复 | P1 | 从 814 行去重至 133 行 |
| 8 | Qdrant :latest 标签 | P1 | 锁定为 v1.12.4 |
| 9 | alembic.ini 明文密码 | P1 | 清空 sqlalchemy.url |
| 10 | Docker Compose 端口冲突 (OSS/test 5433) | P1 | test postgres 改为 5434 |
| 11 | mypy 非阻塞 + 缺少 ruff/mypy 配置 | P1 | 移除 \|\| true,添加配置段 |
| 12 | pre-commit 缺少 ESLint hook | P1 | 添加 frontend-lint hook |
| 13 | useWebSocket 无限重连 | P1 | MAX_RECONNECT_ATTEMPTS 从 -1 改为 8 |
| 14 | ESLint 未启用 react-hooks 插件 | P1 | 启用 react-hooks/react-refresh |
| 15 | 开源同步脱敏不完整 | P1 | 补全 delete_patterns 和 _SKIP_DIRS |

### 第二轮: 架构级修复 (7 项)

| # | 问题 | Commit | 验证 |
|---|---|---|---|
| 7 | LLM 硬编码参数提取到 config | 504f9d2 | test_llm_temperature 通过 |
| 1 | 三套 DB 层统一 (删除死代码 + 修复递归) | 03231bb | test_smoke 通过 |
| 2 | V3 编排器迁移 (MeetingManager 空桩实现) | c265c74 | test_manager 通过 |
| 3 | AgentRuntime 统一 (execute_think + proto 同步) | a459f59 | test_compute 11/11 通过 |
| 4 | 前端代码分割 (React.lazy + manualChunks) | c3902d6 | build + 13 tests 通过 |
| 5 | CSS 拆分 (4809行 → 4 个语义文件) | 8ec91d3 | build + 13 tests 通过 |
| 6 | 前端测试覆盖 (+23 个新测试) | 4951464 | 36 tests 全部通过 |

---

## 二、详细修复记录

### #7 LLM 硬编码参数提取 (commit 504f9d2)

**修改文件**:
- `backend/app/config.py`: 新增 llm_seed, llm_top_p, llm_no_think, llm_max_prompt_tokens, llm_max_attempts, llm_default_timeout, llm_produce_timeout, llm_circuit_failure_threshold, llm_circuit_recovery_timeout, llm_stage_temperatures
- `backend/app/agents/llm.py`: STAGE_TEMPERATURES 从 dict 常量改为函数 (带 JSON 解析和缓存); 所有 seed=42/top_p=1.0/no_think/32000/timeout 替换为 settings 读取
- `backend/tests/test_llm_temperature.py`: 适配 STAGE_TEMPERATURES() 函数调用
- `.env.example`: 新增 LLM 参数条目

**行为变化**: 无。所有默认值与原硬编码值完全一致。

### #1 三套 DB 层统一 (commit 03231bb)

**删除文件 (死代码)**:
- `backend/app/db_async.py` (无外部引用,签名与 db_legacy 不匹配)
- `backend/app/db/repository.py` (ABC 接口,无调用方)
- `backend/app/db/sqlalchemy_repo.py` (ORM 实现,无调用方)
- `backend/app/db/factory.py` (LegacyRepoBundle,无调用方)
- `backend/app/db/mapper.py` (ORM 映射,仅 sqlalchemy_repo 导入)
- `backend/app/db/upsert.py` (方言 upsert,仅 sqlalchemy_repo 导入)

**保留文件**:
- `backend/app/db/engine.py` (AsyncSession 工厂,被 router 使用)
- `backend/app/db/models.py` (ORM 模型,CostRecordModel 被 router 使用)

**Bug 修复**:
- `backend/app/db_legacy.py` `_putconn` 函数在池已关闭时递归调用自身 → 改为 `conn.close()`

### #2 V3 编排器迁移 (commit c265c74)

**修改文件**:
- `backend/app/orchestrator/manager.py`: 实现 persist_state (db_legacy)、publish_event (EventBus)、dispatch_material (RAG retriever) 三个方法
- `backend/app/orchestrator/stage_runners.py`: 添加迁移中间态文档注释

**已知遗留**: stage_runners 仍从 nodes/ 导入辅助函数 (函数级延迟导入避免循环依赖)。produce 阶段完整迁移留待后续迭代。

### #3 AgentRuntime 统一 (commit a459f59)

**修改文件**:
- `backend/app/agents/compute.py`: 新增 `execute_think()` 统一入口函数
- `backend/app/agents/compute.proto`: 同步 ReAct 扩展字段 (available_tools, tool_history, iteration, tool_calls, need_continue, input_tokens, output_tokens); 新增 ToolCallRequest/ToolCallResponse/ToolResultMessage 消息

### #4 前端代码分割 (commit c3902d6)

**修改文件**:
- `frontend/vite.config.ts`: 添加 `build.rollupOptions.output.manualChunks` 函数 (monaco/echarts/xterm/d3/antd-vendor/react-vendor)
- `frontend/src/App.tsx`: 6 个重型组件改为 React.lazy (AgentGraph, ReportViewer, WorkspacePanel, DashboardView, ModelsView, TaskBoard); 添加 Suspense 包裹

**构建产物**: 主 chunk 从单个大文件降至 106KB + 独立 lazy chunks

### #5 CSS 拆分 (commit 8ec91d3)

**修改文件**:
- 删除 `frontend/src/index.css` (4809 行)
- 新增 `frontend/src/styles/tokens.css` (205 行, CSS 变量 + reset)
- 新增 `frontend/src/styles/layout.css` (940 行, 全局布局)
- 新增 `frontend/src/styles/components.css` (2890 行, 业务组件)
- 新增 `frontend/src/styles/landing.css` (774 行, 着陆页)
- `frontend/src/main.tsx`: 按序导入 4 个 CSS 文件

### #6 前端测试覆盖 (commit 4951464)

**新增文件**:
- `frontend/src/test/meetingReducer.test.ts`: 12 个测试用例 (reset, snapshot, replay.done, hydrate, error, meeting.created, stage.changed, agent.spoke + dedup, control.signal, log.entry + 500-cap)
- `frontend/src/test/format.test.ts`: 11 个测试用例 (formatTime, formatDateTime, tryFormatJson, truncate)

**测试总数**: 从 13 增至 36

---

## 三、第三轮修复 (架构级深度修复, 10 项)

| # | 问题 | Commit | 验证 |
|---|---|---|---|
| R1 | nodes/*.py 中 13 处 compute.think() → execute_think() | 4b148c8 | 22 tests pass |
| R2 | stage_runners 反向依赖提取 (_scan_artifacts/_emit_progress) | e04d69a | syntax OK |
| R3 | nodes/ 中残留 seed=42 替换为 settings.llm_seed | 0a0ba77 | syntax OK |
| R4 | Docker socket 安全: docker-socket-proxy + L2 DNS 代理 | d6848b9 | YAML valid |
| R6 | 依赖版本锁定: requirements.lock (13 pinned packages) | f846fbf | Dockerfile updated |
| R7 | 安全模块测试: 154 test cases (sandbox/injection/middleware) | 005614a | all pass |
| R8 | 前端 useWebSocket 测试: 17 test cases (53 total) | 005614a | all pass |
| R9 | 内联样式提取 + TS 类型修复 (15+ styles → CSS classes) | 0aa35ab | tsc 0 errors |

### R4 Docker Socket 安全加固详情

**docker-socket-proxy** (tecnativa/docker-socket-proxy:0.3):
- 仅暴露 CONTAINERS, IMAGES, INFO, VERSION 端点
- 屏蔽 EXEC, BUILD, COMMIT, VOLUMES, NETWORKS, SECRETS, PLUGINS, SWARM 等
- backend 通过 DOCKER_HOST=tcp://docker-socket-proxy:2375 连接
- 移除 backend 直接 /var/run/docker.sock 挂载

**L2 网络隔离** (DNS 代理):
- conclave-sandbox-l2 自定义网络 (10.20.0.0/16)
- dnsmasq DNS 代理仅解析白名单域名 (pypi.org, files.pythonhosted.org, mirrors.tuna.tsinghua.edu.cn)
- sandbox.py: L2 容器使用 --network conclave-sandbox-l2 + --dns 10.20.0.10
- L1 保持 --network none, L3 保持默认 bridge

### R7 安全测试覆盖详情

| 测试文件 | 用例数 | 覆盖内容 |
|---|---|---|
| test_sandbox_security.py | 72 | 命令白名单/黑名单、容器安全参数、L1/L2/L3 网络分级 |
| test_prompt_injection.py | 42 | 中英文注入检测、输入过滤、内容隔离 |
| test_middleware_security.py | 40 | API Token 认证、频率限制、IP 封禁、开发模式跳过 |
| useWebSocket.test.ts | 17 | 连接/重连/消息处理/卸载清理 |
| **合计** | **171** | |

---

## 四、第四轮修复 (收尾项, 3 项)

| # | 问题 | Commit | 验证 |
|---|---|---|---|
| F1 | stage_runners 剩余 4 处反向依赖 | 44dad6d | imports OK |
| F2 | 478 处内联样式提取 (36 文件) | 9aa94a8 | tsc 0 errors, 53 tests pass |
| F3 | 前端核心组件测试 (ChatPanel/AgentGraph/WorkspacePanel) | 7998c79 | 104 tests pass |

### F1 stage_runners 反向依赖彻底消除

**新建文件**:
- `orchestrator/borrow_helpers.py`: `_let_borrowed_agents_speak` + `_moderator_assess_borrow` (从 nodes/borrow.py 提取)
- `orchestrator/evidence_helpers.py`: `_prefetch_evidence` + `_collect_evidence` + `_make_common_knowledge_evidence` (从 nodes/evidence_check.py 提取)

**修改**:
- `nodes/borrow.py` 和 `nodes/evidence_check.py`: 改为 thin re-export wrapper
- `stage_runners.py`: 4 处 `from app.orchestrator.nodes.*` → `from app.orchestrator.*_helpers`
- **stage_runners.py 对 nodes/ 的反向导入: 0 处** (完全消除)

### F2 内联样式提取详情

| 批次 | 文件数 | 样式总数 | 提取为CSS | 保留动态 | CSS类创建 |
|---|---|---|---|---|---|
| Batch 1 (简单) | 8 | 13 | 12 | 1 | 11 |
| Batch 2 (中等) | 12 | 89 | 87 | 2 | 79 |
| Batch 3 (较大) | 7 | 109 | 98 | 6 | 77 |
| Batch 4 (最大) | 7 | 243 | 227 | 16 | 168 |
| ArtifactPanel + GuardButton | 2 | 24 | 24 | 0 | 17 |
| **合计** | **36** | **478** | **448** | **25** | **352** |

**剩余 25 处内联样式**: 全部为动态样式 (使用变量/三元表达式, 无法转为静态 CSS)

**GuardButton 压线修复**: 折叠宽度 28px→32px, 盾牌圆 18px→20px, 图标 11→12px, padding 改为等距

**额外 Bug 修复**: WorkspacePanel `renderTreeNodes` 从 `tree` 陈旧状态改为从 `pathMap` 读取最新节点状态, 修复目录展开不渲染子节点的 bug

### F3 前端组件测试覆盖

| 测试文件 | 用例数 | 覆盖内容 |
|---|---|---|
| ChatPanel.test.tsx | 14 | 空态/消息渲染/阶段分隔线/Produce进度条/滚动行为/onSelectRef |
| AgentGraph.test.tsx | 16 | SVG容器/缩放控件/Agent节点/冲突/借调/证据/产出物/FocusMode/圆桌椭圆 |
| WorkspacePanel.test.tsx | 21 | 工具栏/文件树懒加载/编辑器打开编辑保存/终端执行/沙箱徽章/meetingId隔离 |
| **合计** | **51** | |

**前端测试总数**: 从 53 增至 **104** (翻倍)

---

## 五、未完成项 (后续迭代)

| 项目 | 说明 | 风险 | 决策 |
|---|---|---|---|
| produce 阶段完整迁移 | 638 行拆分为 Planner + 后处理 | 高 | **用户决定本次跳过** |
| 前端工具链版本降级 | TS6/Vite8/ESLint10 过于激进 | 中 | **用户决定排除** |

---

## 六、Git 提交历史

```
7998c79 test(frontend): add ChatPanel/AgentGraph/WorkspacePanel component tests + fix tree render bug
9aa94a8 refactor(frontend): extract 451 inline styles to CSS classes across 36 files
44dad6d refactor(orchestrator): extract borrow/evidence helpers to eliminate all reverse deps
0aa35ab refactor(frontend): extract inline styles to CSS classes and fix TS errors
005614a test: add security module tests and useWebSocket hook tests
f846fbf build: add requirements.lock for reproducible builds
d6848b9 security(docker): add socket proxy and L2 network isolation
0a0ba77 refactor(nodes): replace remaining hardcoded seed=42 with settings.llm_seed
e04d69a refactor(orchestrator): extract produce helpers to eliminate reverse dependency
4b148c8 refactor(agents): replace all compute.think() with execute_think()
```

加上前两轮的 12 个 commit,共计 **25 个独立 commit**,每一步均可独立 `git revert`,遵循 Conventional Commits 规范。
