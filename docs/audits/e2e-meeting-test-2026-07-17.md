# Conclave 端到端会议测试评估报告

**测试时间**: 2026-07-17  
**测试方法**: 通过 HTTP API 创建+运行会议，轮询进度，采集日志/统计/产出  
**测试环境**: Docker Compose（backend + postgres + qdrant + redis + frontend）  
**LLM 配置**: SiliconFlow / DeepSeek-V3.2  

---

## 测试场景

| # | 产出类型 | 议题 | debate_depth |
|---|---------|------|-------------|
| M1 | research_report（调研报告） | 评估2026年国内开源大模型在代码生成领域的技术成熟度与落地可行性 | light |
| M2 | deployable_service（可部署服务） | 设计一个轻量级的 API 健康检查微服务，支持 HTTP/TCP 双探针和告警通知 | light |

---

## 核心发现

### 1. 系统能跑通完整六阶段流程，但速度极慢

M1（调研报告）在测试期间推进到了第 3 阶段 `cross_team`，M2（可部署服务）推进到第 2 阶段 `intra_team`。六阶段流程 `clarify → intra_team → cross_team → evidence_check → arbitrate → produce` 的编排逻辑正确，阶段路由正常工作。

**但单场会议预计需要 10-20 分钟才能完成**，远超可接受的用户等待时间。

### 2. 最大瓶颈：Agent 串行执行 + LLM 延迟过高

```
intra_team 阶段 LLM 调用耗时（M2 可部署服务）：
  运维工程师:      23.6s
  系统架构师:      23.6s
  后端开发工程师:   33.1s
  产品负责人:       39.5s
  security_expert:  33.9s（借调）
  moderator(借调评估): 15.2s
  meta_cognition:    2.3s
  ─────────────────────────
  intra_team 总耗时: ~171s（近 3 分钟，仅一个阶段）
```

**根因**：5 个 Agent 的 LLM 调用是**串行执行**的（一个跑完才跑下一个），而 SiliconFlow API 单次调用延迟 20-40 秒（正常应为 3-8 秒）。5 个 Agent × 30s = 150s，加上 moderator/meta 调用，一个 `intra_team` 阶段就要 3 分钟。

**如果改为并行执行**（`asyncio.gather`），5 个 Agent 同时调用，intra_team 耗时可从 171s 降到 ~40s（取决于最慢的那个）。

### 3. SiliconFlow API 不稳定，导致 StubLLM 降级

M1（调研报告）的 3 个 Agent（技术架构师、开源生态专家、行业应用顾问）在 `intra_team` 阶段全部遭遇 `ReadTimeout`，3 次重试均失败后降级到 `StubLLM`（生成占位假数据）。

```
ERROR: 阶段=intra_team 三次重试全部失败，降级到 StubLLM。最后错误: siliconflow: ReadTimeout:
```

**影响**：降级到 StubLLM 后，Agent 发言内容是模板占位文本，不具备实际分析价值。会议虽然继续推进，但产出质量严重下降。

**建议**：
- 增加 LLM 调用超时时间（当前可能过短）
- 配置备用 Provider（如 DeepSeek 官方、OpenRouter）作为 fallback
- StubLLM 降级时应在会议状态中明确标注，而非静默继续

### 4. Charter（会议章程）产出质量优秀

两场会议的 `clarify` 阶段都产出了高质量 Charter：

**M2（可部署服务）Charter**：
- `clarified_topic`: "设计一个轻量级的 API 健康检查微服务，该服务需支持 HTTP 和 TCP 两种探针类型，并具备告警通知能力。"
- `meeting_goal`: 明确产出 PRD 与 OpenAPI
- `scope`: 6 个精准的讨论范围问题（探针参数、告警渠道、持久化、部署方式、自身可观测性）
- `constraints`: 7 条会议规则（不跨阶段、不重复裁决、借调三问法等）

**M1（调研报告）Charter**：
- `clarified_topic`: 细化为技术能力、生态建设、应用场景适配性、商业化潜力四个维度
- `scope`: 5 个具体评估问题（核心技术指标、生态要素、落地场景、竞争优势）

Clarify 阶段的 LLM 调用虽然慢（20-5869ms 到 20715ms），但产出的 Charter 结构完整、逻辑清晰、问题精准。

### 5. 成本追踪正常工作

20 分钟内共记录 13 次 LLM 调用，成本追踪准确：

| 指标 | 数值 |
|------|------|
| 总调用数 | 13 |
| 平均成本/次 | ~$0.0004 |
| 平均延迟 | ~22s |
| 最大延迟 | 39.5s（产品负责人） |
| 最小延迟 | 2.2s（meta_cognition） |
| 单次最大 token | 3814（security_expert 借调） |
| 模型 | deepseek-ai/DeepSeek-V3.2 |

### 6. Trace 记录系统故障

所有 LLM 调用都输出警告：`record_call 跳过：当前无活跃 trace`。导致 `/meetings/{id}/stats` 的 `llm_trace` 统计全部为 0（total_calls=0, success_rate=N/A）。

**根因**：trace session 未被正确初始化。cost_tracker 能记录（因为它独立于 trace 系统），但 trace 系统的 `record_call` 找不到活跃的 trace session。

### 7. Summary 端点 ImportError

```
ImportError: cannot import name '_extract_artifact_summary' from 'app.db_legacy'
```

`/meetings/{id}/summary` 端点返回 500，导致前端无法获取会议摘要。

### 8. Redis 健康检查误报

`/health` 报告 `redis: error: ConnectionError`，但从容器内直接 `redis.ping()` 成功。Redis 实际可用（事件总线、WebSocket 正常工作），但健康检查的连接方式有 bug。

---

## 性能数据汇总

| 指标 | M1（调研报告） | M2（可部署服务） |
|------|---------------|-----------------|
| 创建耗时 | 0.12s | 1.37s |
| clarify 阶段 | ~3s（首次 poll 已完成） | ~3s（首次 poll 已完成） |
| 进入 intra_team | +66.9s | ~10min（含 ReadTimeout 重试） |
| intra_team 推进 | 3 条消息 / 6 论断 | 4 条消息 / 12 论断 |
| 进入 cross_team | ~170s（从 intra_team 开始） | 未到达 |
| 测试截止状态 | running（cross_team） | running（intra_team） |
| Charter 质量 | 优秀 | 优秀 |
| LLM 降级次数 | 3 次（StubLLM） | 0 次 |
| 总 LLM 调用 | ~7 次 | ~10 次 |

---

## 问题优先级

| 优先级 | 问题 | 影响 | 建议修复方式 |
|--------|------|------|-------------|
| **P0** | Agent 串行执行 | 单阶段 3 分钟，全流程 10-20 分钟 | `intra_team`/`cross_team` 阶段用 `asyncio.gather` 并行调用各 Agent |
| **P0** | SiliconFlow ReadTimeout | 3 个 Agent 降级 StubLLM，产出无价值 | 增加超时时间 + 配置备用 Provider fallback |
| **P1** | Trace 记录故障 | llm_trace 统计全为 0，无法审计 LLM 质量 | 修复 trace session 初始化逻辑 |
| **P1** | Summary 端点 ImportError | 前端无法获取会议摘要 | 修复 `_extract_artifact_summary` 导入 |
| **P2** | Redis 健康检查误报 | 状态显示 degraded，实际正常 | 修复健康检查的 Redis 连接方式 |
| **P2** | StubLLM 降级无感知 | 用户不知道产出是假数据 | 降级时在会议状态/事件中标注 |

---

## 总体评估

**系统架构是健全的**——六阶段编排、角色配置、借调机制、成本追踪、Charter 生成都是正确的设计。Charter 产出的质量证明了 clarify 阶段的 prompt 工程做得很好。

**核心问题是性能**——Agent 串行执行 + LLM API 延迟，导致单场会议需要 10-20 分钟。如果把 Agent 改为并行执行，配合更稳定的 LLM Provider，单场会议可以压缩到 3-5 分钟，达到可接受的用户体验。

**可靠性需要加强**——StubLLM 静默降级是最危险的：会议看起来在正常推进，但产出实际是假数据。用户完全无感知。必须在降级时明确标注。

---

*测试脚本: `meeting_test.py` | 测试会议 ID: `mtg-ab975a9bb147`（调研）、`mtg-8940bece5f16`（可部署服务）*
