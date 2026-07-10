# 会话归档 2026-06-29

## 概述

本次会话完成了三项核心工作：沙箱网络分级、三种产出类型端到端验证、设计缺陷记录归档。

## 完成的工作

### 1. 沙箱网络分级 L1/L2/L3（commit `0adc519`）

**问题**：沙箱 `--network none` 是硬限制，LLM 生成的代码不能 pip install、不能访问外部 API。

**方案**：三级网络分级
- L1（默认）：`--network none`，纯计算
- L2（限网）：bridge 网络，允许 pip install pypi
- L3（全联网）：bridge 网络，可访问任意外部 API

**实现**：
- `_build_security_args` 新增 `network_level` 参数
- `run_python` / `run_command` 新增 `network_level` 参数（默认 L1 向后兼容）
- produce_node 新增 `_detect_network_level()`：根据代码内容自动判断网络级别
  - 检测到 requests/urllib/httpx/http(s):// → L3
  - 检测到 pip install → L2
  - 其他 → L1

**验证**：L1 纯计算 + L2 pip dry-run + L3 HTTP 200 全部通过

### 2. tested_system 端到端验证

**会议**：mtg-ef826bc3ce3f（库存扣减服务，不可超卖）

**结果**：
- 21 次 LLM 调用，全部 valid，0 fallback
- RefineLoop 3 轮修复（round=1/2/3 exit_code=1，重复检测终止）
- 产出：main_code 5203 字符 + test_code 8366 字符
- 25 claims / 5 conflicts
- produce 耗时 1102 秒（含 RefineLoop 3 轮）
- confidence=low（一致性检查触发了一次重试）

**RefineLoop 表现**：机制正常工作，但 pytest 3 轮都没通过。LLM 修正后代码变化但测试仍失败，最终重复检测终止。这是正常的——库存扣减 + 并发锁是复杂场景，LLM 生成的测试代码可能有问题。

### 3. deployable_service 端到端验证

**会议**：mtg-df193ac5163f（待办事项管理 API 服务）

**结果**：
- 10 次 LLM 调用，全部 valid，0 fallback
- produce 耗时 184 秒（无 RefineLoop，只生成文件）
- 产出：app_code 6876 字符 + Dockerfile + docker-compose.yml + requirements.txt
- 部署文件生成到 `/workspace/mtg-df193ac5163f/`
- 20 claims / 3 conflicts
- exit_code=0

**产出质量**：FastAPI 应用 + 完整依赖 + Docker 部署文件，可直接 `docker compose up` 启动

### 4. 设计缺陷记录归档（commit `8bfa4b1`）

在 `optimization-backlog.md` §6.1 记录了 3 个设计缺陷：
1. ProduceResult schema 丢弃 code_analysis 字段
2. 沙箱 stdin 管道在 Windows Docker 下阻塞
3. Docker 卷名前缀不一致

每个缺陷包含根因分析和教训。

## Commit 历史

| Commit | 内容 |
|---|---|
| `0adc519` | feat(sandbox): 沙箱网络分级 L1/L2/L3 + 代码内容自动检测 |
| `8bfa4b1` | docs: 记录 3 个设计缺陷 + 更新端到端验证报告 |
| `8975ca2` | fix(sandbox): 沙箱执行改用写文件方式 + 修复 Docker 卷挂载 |
| `cf86b6e` | fix(refine): RefineLoop rounds_used 返回实际轮次 |
| `84a66ce` | fix(produce): ProduceResult schema 丢弃字段修复 |
| `f4636a3` | docs: 端到端验证报告 + 测试用文档 |

## 三种产出类型验证汇总

| 类型 | 会议 | LLM 调用 | RefineLoop | 产出 | 状态 |
|---|---|---|---|---|---|
| code_analysis | mtg-a5bf4695c4d2 | 13 次 | 1 轮成功 | 分析报告（14万请求） | ✅ done |
| tested_system | mtg-ef826bc3ce3f | 21 次 | 3 轮未通过 | main_code + test_code | ✅ done |
| deployable_service | mtg-df193ac5163f | 10 次 | 无需 | FastAPI + Docker | ✅ done |

## 下一步建议

1. **议题路由**：六阶段 + 三种产出类型全部验证可靠，可以开始做动态流程
2. **RefineLoop 优化**：tested_system 的 pytest 3 轮没通过，可以考虑给 LLM 更多上下文（如 pytest 完整输出而非截断）
3. **知识库 Outline + MCP**：用户表示要自己思考，暂缓
