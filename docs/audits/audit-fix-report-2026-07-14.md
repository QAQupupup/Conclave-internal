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

## 三、未完成项 (后续迭代)

| 项目 | 说明 | 风险 |
|---|---|---|
| stage_runners 反向依赖 nodes/ | 需提取 borrow/evidence/produce 辅助函数到独立模块 | 中 (函数移动可能遗漏闭包变量) |
| produce 阶段完整迁移 | produce_node ~400 行逻辑需拆分为 Planner + 后处理 | 高 (涉及沙箱执行和 Docker 部署) |
| nodes/*.py 中的 compute.think() 替换为 execute_think() | 7 个 node 文件 + runner.py | 低 (薄包装,行为一致) |
| 481 处内联样式提取 | 36 个文件,需逐文件处理 | 低 (渐进式) |
| 前端 useWebSocket 测试 | 需 Mock WebSocket,测试重连/批处理/清理 | 中 |
| 前端核心组件测试 (ChatPanel/AgentGraph/WorkspacePanel) | 需 React Testing Library + mock | 中 |
| LLM 硬编码参数在 nodes/ 中的使用 | nodes/ 中的 compute.think 调用仍直接使用 settings | 低 |
| Docker socket 安全加固 | 考虑 docker-socket-proxy | 中 |
| L2 网络隔离网络层强制执行 | 需 iptables/ebpf 规则 | 高 |
| 安全模块测试 (sandbox/prompt_injection/middleware) | 安全关键模块无测试 | 高 |
| 依赖版本锁定 (pip-compile/Poetry) | 当前全部使用 >= | 中 |
| 前端工具链版本降级 (TS6/Vite8/ESLint10) | 过于激进 | 中 |

---

## 四、Git 提交历史

```
4951464 test(frontend): add tests for meetingReducer and format utils
8ec91d3 refactor(frontend): split 4809-line index.css into semantic modules
c3902d6 perf(frontend): implement code splitting with React.lazy and manualChunks
a459f59 refactor(agents): add execute_think unified entry point and sync proto
c265c74 refactor(orchestrator): implement MeetingManager core methods
03231bb refactor(db): unify to single db_legacy layer, remove dead ORM code
504f9d2 refactor(agents): extract hardcoded LLM parameters to config
```

每一步均可独立 `git revert`,遵循 Conventional Commits 规范。
