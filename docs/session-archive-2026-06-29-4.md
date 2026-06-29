# 会话归档 2026-06-29（第四次）

## 概述

针对系统审查发现的结构性缺漏，完成安全闭环和可靠性闭环两个优先级的修复。6 个重大缺漏全部修复，56 个回归测试通过。

## 完成的工作

### 安全闭环（commit `2b89176`）

修复 3 个致命/严重安全缺漏：

**1. API 认证中间件**（`middleware.py` + `main.py`）
- `CONCLAVE_API_TOKEN` 环境变量控制，未设置则不认证（开发模式）
- 支持 `Authorization: Bearer <token>` 和 `?token=<token>` 两种方式
- `/health`、`/docs` 等公开路径免认证

**2. 沙箱 host 降级改拒绝**（`sandbox.py`）
- 默认拒绝在宿主机执行用户代码
- `CONCLAVE_SANDBOX_ALLOW_HOST=1` 才允许降级（仅开发）
- Docker 不可用时返回 `exit_code=127` + 安全拒绝信息

**3. 命令注入防护 + 文件上传安全**（`workspace.py` + `documents.py`）
- 精确匹配黑名单改为 11 种正则模式匹配（`rm -rf /`、`mkfs`、`curl|bash`、`eval`、`nc` 反弹 shell 等）
- 文件上传：10MB 大小限制 + 扩展名白名单（.md/.markdown/.txt）+ 文件名安全化（路径穿越防护）

### 可靠性闭环（commit `f9720f1`）

修复 6 个严重/高级可靠性缺漏：

**1. 事件总线持久化**（`events.py` + `db.py`）
- `publish` 时写入 SQLite `events` 表，seq 用 DB 自增
- `replay`/`history` 优先内存，内存空则从 SQLite 恢复
- 进程重启后 WebSocket 重连可回放全部历史事件

**2. RUNNING 会议崩溃恢复**（`runner.py` + `main.py` lifespan）
- 启动时扫描 `status=running` 的会议
- 标记为 `paused`，用户可手动 `resume` 继续
- 通过 `recover_crashed_meetings()` 在 lifespan 中调用

**3. `_states` 线程安全**（`runner.py`）
- `_states_lock = threading.RLock()`
- `get_state`/`set_state` 加锁，防止竞态条件

**4. LLM 熔断器**（`llm.py`）
- `CircuitBreaker`：连续失败 5 次 → open → 60s 后 half_open → 恢复 closed
- open 状态直接降级 Stub，不浪费时间重试
- 成功时 `record_success`，失败时 `record_failure`
- `/health` 暴露熔断器状态

**5. 健康检查完善**（`main.py`）
- 检查 SQLite 连通性、Qdrant 可达性、Docker daemon 可用性、熔断器状态
- 返回 `ok` 或 `degraded` + 详细 `checks` 字典

**6. LLM 降级强制提示**（`nodes.py`）
- 会议 `DONE` 时检查 `confidence_flags`
- 有 `fallback` 阶段时发 `meeting.fallback_warning` 事件
- 前端可监听此事件展示降级警告

## Commit 历史

| Commit | 内容 |
|---|---|
| `f9720f1` | fix(reliability): 可靠性闭环——事件持久化+崩溃恢复+熔断器+健康检查+降级提示 |
| `2b89176` | fix(security): 安全闭环——API认证+沙箱降级拒绝+命令注入防护+文件上传安全 |
| `d44e726` | docs: 归档 2026-06-29 第三次 |
| `f4b369c` | refactor: P1-13 EvidenceCollector 抽取 |
| `6c42be5` | refactor: P0-6 角色画像统一到 ROLE_LIBRARY |
| `358e1d8` | fix: P1-9 produce schema 强类型校验 |

## 测试验证

| 闭环 | 测试数 | 结果 |
|---|---|---|
| 安全闭环 | 38 | 全部通过 |
| 可靠性闭环 | 56（含 role_matching + role_library） | 全部通过 |

健康检查端点验证：
```json
{
  "status": "degraded",
  "checks": {
    "sqlite": "ok",
    "qdrant": "error: ConnectError",
    "docker": "ok",
    "llm_circuit": "closed"
  }
}
```

## 修复的缺漏清单

| 缺漏 | 维度 | 严重性 | 修复 commit |
|---|---|---|---|
| API 完全无认证 | 安全 | 致命 | `2b89176` |
| 沙箱 host 降级执行用户代码 | 安全 | 致命 | `2b89176` |
| 命令注入黑名单可绕过 | 安全 | 严重 | `2b89176` |
| 文件上传无安全限制 | 安全 | 严重 | `2b89176` |
| 事件总线纯内存，重启丢失 | 持久化 | 严重 | `f9720f1` |
| `_states` 无锁竞态条件 | 并发 | 严重 | `f9720f1` |
| RUNNING 会议重启后卡死 | 持久化 | 严重 | `f9720f1` |
| 无熔断器，LLM 宕机雪崩 | 容错 | 高 | `f9720f1` |
| LLM 降级到 stub 仍标记 DONE | 容错 | 严重 | `f9720f1` |
| 健康检查不检查依赖 | 可观测 | 中高 | `f9720f1` |

## 新增环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `CONCLAVE_API_TOKEN` | 空 | API 认证 token，未设置则不认证 |
| `CONCLAVE_SANDBOX_ALLOW_HOST` | 空 | 允许沙箱降级到宿主机（=1 开启，仅开发） |
| `CONCLAVE_CORS_ORIGINS` | `*` | CORS 允许的源，逗号分隔 |

## 剩余缺漏

以下缺漏未在本轮修复（优先级低于安全和可靠性）：
- Docker socket 挂载风险（需改为 Docker-in-Docker 或远程 Docker daemon）
- 记忆系统不持久化（架构演进中期目标）
- 无 metrics 暴露（需 Prometheus 集成）
- 议题路由未实现（下一步产品功能）
- 无产出物修订循环（需新增 control signal）
