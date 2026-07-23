# Conclave 评估框架设计

> 目标：在投入 API 预算前，把评估所需的前期工作全部准备好。
> 包括：评估维度、测试数据集、评分器、统计方法、基础设施。
> 实际跑评估时只需 `python -m eval.run` 一条命令。

## 0. 核心问题

Conclave 目前处于 "flying blind" 状态：
- 所有测试用 StubLLM（固定返回），从未测过真实 LLM 输出质量
- 回归系统只记数字指标（调用次数、延迟），不评估输出语义质量
- 换 prompt / 换模型 / 改编排逻辑后，不知道变好还是变差
- 不知道系统边界：什么类型的议题能处理好，什么处理不好

## 1. 评估维度（按六阶段拆解）

### 1.1 Clarify（议题澄清）

| 维度 | 评分方式 | 权重 |
|---|---|---|
| 议题复述准确性 | LLM-judge: 原始议题 vs clarified_topic 语义一致性 (0-1) | 20% |
| 关键问题质量 | LLM-judge: key_questions 是否覆盖核心争议点 (0-1) | 30% |
| 团队配置合理性 | LLM-judge: team_config 角色是否匹配议题领域 (0-1) | 20% |
| 复杂度路由准确性 | 精确匹配: 预期 complexity vs 实际 complexity | 30% |

### 1.2 IntraTeam（队内论点）

| 维度 | 评分方式 | 权重 |
|---|---|---|
| 论点相关性 | LLM-judge: claims 是否与议题相关 (0-1) | 30% |
| 证据标注准确性 | LLM-judge: evidence_ref 类型标注是否正确 (fact/assumption/constraint) | 25% |
| 风险标注准确性 | 精确匹配: 预期 risk_level vs 实际 (engineer 角色) | 20% |
| 角色视角一致性 | LLM-judge: claims 是否符合角色视角 (architect 重价值/边界, engineer 重可行性/风险) | 25% |

### 1.3 CrossTeam（冲突检测）

| 维度 | 评分方式 | 权重 |
|---|---|---|
| 冲突检出率 (Recall) | 精确匹配: 预期冲突数 vs 实际检出数 (召回率) | 35% |
| 冲突精确率 (Precision) | 人工标注: 实际检出冲突中真实冲突的比例 | 25% |
| 冲突类型准确性 | 精确匹配: factual/preference/scope 分类准确率 | 20% |
| 冲突摘要质量 | LLM-judge: summary 是否准确概括双方分歧 (0-1) | 20% |

### 1.4 EvidenceCheck（证据对照）

| 维度 | 评分方式 | 权重 |
|---|---|---|
| 论点区分度 | LLM-judge: 双方论点是否真正对立，而非伪冲突 (0-1) | 15% |
| 论点质量 | LLM-judge: 论点是否有逻辑支撑、是否切中议题核心 (0-1) | 20% |
| 证据利用质量 | LLM-judge: 有证据时正确引用，无证据时诚实标注 (0-1) | 15% |
| 裁决归因清晰度 | LLM-judge: arbitrate 是否说明基于哪些论点得出结论 (0-1) | 15% |
| 置信度自评准确性 | 精确匹配: 无证据时是否主动降级 confidence 为 low | 15% |
| 论点互补性 | LLM-judge: 双方论点是否互补而非纯粹对立，能否合并出更优解 (0-1) | 20% |

### 1.5 Arbitrate（仲裁裁决）

| 维度 | 评分方式 | 权重 |
|---|---|---|
| 裁决合理性 | LLM-judge: verdict 是否基于证据做出合理裁决 (0-1) | 35% |
| 理由充分性 | LLM-judge: rationale 是否引用了具体证据 (0-1) | 25% |
| 论点综合质量 | LLM-judge: 裁决是否提取了双方最有价值的部分，而非简单判输赢 (0-1) | 25% |
| 门禁触发信号 | 过程信号: 首轮 pass=1.0, supplement后pass=0.6, re_examine=0.3, 达上限=0.1 | 15% |

### 1.6 Produce（产出物）

| 维度 | 评分方式 | 权重 |
|---|---|---|
| PRD 完整性 | 检查: title/goal/scope/assumptions/constraints 字段非空率 | 30% |
| API 端点合理性 | LLM-judge: api_endpoints 是否覆盖核心功能 (0-1) | 30% |
| OpenAPI 规范性 | 静态检查: YAML 语法 + OpenAPI 3.0 schema 校验 | 20% |
| 产出一致性 | LLM-judge: 产出物是否与前面讨论结论一致 (0-1) | 20% |

## 2. 测试数据集设计

### 2.1 数据集分层（共 50 个测试用例）

**Tier 1: 基础能力验证（10 个）**
- 目的：验证系统在标准场景下的基本功能
- 特征：议题明确、2 个角色、预期有 1-2 个冲突、flow_plan=full
- 用途：回归测试基线（每次改动必跑）

**Tier 2: 边界探测（20 个）**
- 目的：探测系统能力边界
- 子类：
  - 简单议题（5 个）：预期 flow_plan=simple，跳过中间阶段
  - 无冲突议题（5 个）：预期 cross_team 检出 0 冲突
  - 多角色议题（5 个）：3-4 个角色，测试复杂编排
  - 长文档议题（5 个）：上传 10K+ 文档，测试 RAG 召回

**Tier 3: 压力测试（10 个）**
- 目的：测试极端场景下的鲁棒性
- 子类：
  - 模糊议题（3 个）：议题描述不清晰，测试 clarify 能力
  - 高冲突议题（3 个）：预期 5+ 冲突，测试编排压力
  - 跨领域议题（2 个）：需要领域知识（安全/数据/设计）
  - 对抗性议题（2 个）：刻意构造矛盾论点，测试证据检索+仲裁

**Tier 4: 回归保护集（10 个）**
- 目的：从 Tier 1-3 中选取稳定通过的用例，作为回归基线
- 特征：Pass@3 全通过，方差小
- 用途：每次 PR 必跑，防止退化

### 2.2 测试用例结构

每个测试用例是一个 JSON 文件：

```json
{
  "case_id": "tier1-tech-blog-platform",
  "tier": 1,
  "category": "standard",
  "topic": "开发一个技术博客平台，支持 Markdown 编辑、标签分类、全文搜索",
  "uploaded_docs": [
    {
      "filename": "requirements.md",
      "content": "# 需求文档\n## 核心功能\n- Markdown 编辑器\n- 标签系统\n- Elasticsearch 全文搜索\n## 约束\n- 预算有限，不能用付费搜索服务\n- 需要支持 10 万篇文章"
    }
  ],
  "expected": {
    "clarify": {
      "complexity": "full",
      "min_key_questions": 2,
      "expected_roles": ["product_architect", "engineer"]
    },
    "cross_team": {
      "min_conflicts": 1,
      "max_conflicts": 3,
      "expected_conflict_types": ["preference", "scope"]
    },
    "arbitrate": {
      "all_conflicts_resolved": true,
      "min_rationale_length": 20
    },
    "produce": {
      "must_have_fields": ["title", "goal", "scope"],
      "min_api_endpoints": 2
    }
  },
  "notes": "标准技术选型冲突：Elasticsearch vs 替代方案（预算约束）"
}
```

### 2.3 数据集生成策略

**Phase 1: 人工种子用例（10 个）**
- 手写 10 个覆盖核心场景的用例 + 预期输出
- 这些是"黄金集"，用于校准 LLM-judge

**Phase 2: LLM 辅助扩展（40 个）**
- 用 LLM 基于种子用例生成更多变体
- 人工审核 + 修正预期输出
- 确保领域覆盖：Web 开发、数据工程、安全架构、产品设计

**Phase 3: 真实会议回放（可选）**
- 从真实使用中选取有代表性的会议
- 脱敏后加入数据集

## 3. 评分器（Grader）设计

### 3.1 三种 Grader 类型

**Type A: 精确匹配 Grader**
- 适用：complexity 路由、冲突类型分类、supports 方向、risk_level
- 实现：预期值 vs 实际值，exact match
- 输出：0 或 1（二值）

**Type B: 字段检查 Grader**
- 适用：PRD 完整性、字段非空、YAML 语法
- 实现：静态检查（非 LLM）
- 输出：通过字段数 / 总字段数

**Type C: LLM-as-Judge Grader**
- 适用：语义质量（论点相关性、裁决合理性、摘要质量）
- 实现：用独立 LLM 实例评分（不与被测系统共用配置）
- Prompt 模板：
  ```
  你是一个会议分析质量评估专家。请评估以下输出的质量。

  议题：{topic}
  预期：{expected_description}
  实际输出：{actual_output}

  评分维度：{dimension}
  评分标准：
  - 1.0: 完全符合预期，质量优秀
  - 0.7: 基本符合，有小瑕疵
  - 0.4: 部分符合，有明显不足
  - 0.0: 不符合预期或无效输出

  请只输出一个 0-1 之间的数字，保留一位小数。
  ```
- 输出：0.0 - 1.0（连续值）
- 一致性校验：每个 LLM-judge 评分跑 3 次，取中位数

### 3.2 Grader 可靠性保障

**LLM-judge 一致性**：
- 每个评分跑 3 次，如果 3 次的标准差 > 0.2，标记为"不可靠评分"
- 不可靠评分不纳入统计，单独列出供人工审核
- 定期用人工标注校准 LLM-judge（每 50 个用例抽 10 个人工复核）

**Grader 独立性**：
- LLM-judge 用独立 API key 和模型（避免被测系统和评分器互相影响）
- 推荐用 Claude 3.5 Sonnet 或 GPT-4o 做 judge（能力 >= 被测模型）

## 4. 统计方法

### 4.1 核心指标

| 指标 | 公式 | 含义 |
|---|---|---|
| Pass@1 | 1 次运行通过的任务数 / 总任务数 | 单次通过率 |
| Pass@3 | 3 次运行中至少 1 次通过的任务数 / 总任务数 | 稳定性 |
| 阶段通过率 | 该阶段通过的任务数 / 总任务数 | 定位短板 |
| 平均得分 | 所有维度加权得分的平均值 | 综合质量 |
| 评分方差 | 同一用例多次运行得分的标准差 | 稳定性 |
| Token 消耗 | 总 input + output tokens | 成本 |
| 延迟 P50/P95 | 所有任务延迟的第 50/95 百分位 | 性能 |

### 4.2 "通过"的定义

一个测试用例"通过"的条件：
- low_confidence_flagged（无证据时必须降级置信度）精确匹配必须通过
- LLM-judge Grader 平均得分 >= 0.7（不要求所有维度全部通过，允许个别维度波动）
- 门禁决策达上限时强制通过的情况记为"低置信度通过"
- 无 fallback 调用（StubLLM 降级）
- 无异常/超时

### 4.3 置信度评估

**系统级置信度**：
- Pass@1 的 95% 置信区间（Wilson 区间）：`p ± 1.96 * sqrt(p(1-p)/n)`
- 50 个用例时：如果 Pass@1 = 80%，置信区间为 [67%, 89%]
- 结论需要 ±10% 以内的变化才有统计显著性

**用例级置信度**：
- 同一用例跑 5 次，通过率作为该用例的"可置信度"
- 可置信度 < 60% 的用例标记为"不稳定用例"
- 不稳定用例占比 > 20% 时，系统整体可置信度低

### 4.4 回归判定规则

| 场景 | 判定 | 动作 |
|---|---|---|
| Pass@1 下降 > 5% | 回归 | 阻止合并 |
| 某阶段通过率下降 > 10% | 阶段回归 | 需要解释原因 |
| 平均得分下降 > 0.1 | 质量退化 | 需要解释原因 |
| Token 消耗增加 > 20% | 成本退化 | 需要优化 |
| 以上均未触发 | 通过 | 可合并 |

## 5. 基础设施设计

### 5.1 目录结构

```
backend/eval/
├── dataset/                    # 测试数据集
│   ├── tier1/                  # 基础能力验证 (10 个)
│   │   ├── tech-blog-platform.json
│   │   ├── user-auth-system.json
│   │   └── ...
│   ├── tier2/                  # 边界探测 (20 个)
│   │   ├── simple-faq-bot.json
│   │   ├── no-conflict-doc.json
│   │   └── ...
│   ├── tier3/                  # 压力测试 (10 个)
│   │   ├── vague-topic.json
│   │   ├── high-conflict.json
│   │   └── ...
│   └── tier4/                  # 回归保护集 (10 个，软链接到 tier1-3)
├── graders/                    # 评分器
│   ├── __init__.py
│   ├── exact_match.py          # Type A: 精确匹配
│   ├── field_check.py          # Type B: 字段检查
│   └── llm_judge.py            # Type C: LLM-as-Judge
├── runners/                    # 执行器
│   ├── __init__.py
│   ├── case_runner.py          # 单用例执行
│   ├── suite_runner.py         # 批量执行
│   └── replay_runner.py        # 回放执行
├── stats/                      # 统计分析
│   ├── __init__.py
│   ├── metrics.py              # 指标计算
│   ├── confidence.py           # 置信区间
│   └── regression.py           # 回归判定
├── reports/                    # 评估报告输出
│   └── (自动生成)
├── config.yaml                 # 评估配置
└── run.py                      # 入口: python -m eval.run
```

### 5.2 评估配置 (config.yaml)

```yaml
# 被测系统配置
target:
  llm_model: "deepseek-chat"          # 被测 LLM
  llm_base_url: "https://api.deepseek.com"
  embedding_model: "bge-m3"
  reranker_model: "BAAI/bge-reranker-v2-m3"

# 评分器配置
judge:
  model: "claude-3-5-sonnet"          # LLM-judge 模型（必须 >= 被测模型）
  base_url: "https://api.anthropic.com"
  api_key_env: "JUDGE_API_KEY"        # 独立 API key
  judge_runs: 3                       # 每个评分跑 3 次取中位数
  unreliable_threshold: 0.2           # 标准差 > 0.2 标记不可靠

# 执行配置
execution:
  pass_k: 3                           # Pass@3
  max_concurrent: 3                   # 并发数（避免 rate limit）
  per_case_timeout: 300               # 单用例超时 5 分钟
  retry_on_timeout: true              # 超时重试 1 次

# 统计配置
stats:
  confidence_level: 0.95              # 95% 置信区间
  regression_pass1_threshold: 0.05    # Pass@1 下降 5% 判回归
  regression_score_threshold: 0.1     # 得分下降 0.1 判退化
```

### 5.3 执行流程

```
python -m eval.run --tier 1 --pass-k 3

1. 加载 config.yaml
2. 加载指定 tier 的测试用例
3. 对每个用例：
   a. 启动会议（POST /meetings，上传文档）
   b. 运行到完成（或超时）
   c. 获取最终状态（GET /meetings/{id}）
   d. 对每个阶段运行对应 Grader
   e. 记录: 用例ID、阶段、维度、得分、token消耗、延迟
4. 汇总统计：
   a. 计算 Pass@1 / Pass@3
   b. 计算阶段通过率
   c. 计算置信区间
   d. 生成报告
5. 输出报告到 reports/{timestamp}/
```

### 5.4 报告格式

```json
{
  "run_id": "eval-20260722-001",
  "timestamp": "2026-07-22T15:00:00Z",
  "config": {
    "target_model": "deepseek-chat",
    "judge_model": "claude-3-5-sonnet",
    "pass_k": 3,
    "tier": 1
  },
  "summary": {
    "total_cases": 10,
    "pass1": 0.70,
    "pass1_ci95": [0.35, 0.93],
    "pass3": 0.90,
    "avg_score": 0.78,
    "total_tokens": 125000,
    "total_cost_usd": 0.42,
    "p50_latency_ms": 45000,
    "p95_latency_ms": 120000
  },
  "stage_breakdown": {
    "clarify": { "pass_rate": 0.90, "avg_score": 0.85 },
    "intra_team": { "pass_rate": 0.80, "avg_score": 0.78 },
    "cross_team": { "pass_rate": 0.60, "avg_score": 0.65 },
    "evidence_check": { "pass_rate": 0.70, "avg_score": 0.72 },
    "arbitrate": { "pass_rate": 0.50, "avg_score": 0.60 },
    "produce": { "pass_rate": 0.80, "avg_score": 0.82 }
  },
  "unstable_cases": [
    { "case_id": "tier1-tech-blog", "pass_rate_5runs": 0.40, "std_score": 0.25 }
  ],
  "unreliable_judgments": [
    { "case_id": "tier1-auth", "dimension": "裁决合理性", "scores": [0.3, 0.8, 0.9], "std": 0.26 }
  ],
  "per_case_results": [...]
}
```

## 6. 预算估算

### 6.1 单次完整评估成本

| 项目 | 数量 | 单价 | 小计 |
|---|---|---|---|
| 被测系统 LLM 调用 | 50 用例 × 6 阶段 × ~3 次/阶段 = 900 次 | ~$0.002/次 (DeepSeek) | $1.80 |
| LLM-judge 评分 | 50 用例 × ~15 维度 × 3 次 = 2250 次 | ~$0.01/次 (Claude) | $22.50 |
| Embedding 调用 | 50 用例 × ~20 chunks = 1000 次 | ~$0.0001/次 | $0.10 |
| Reranker 调用 | 50 用例 × ~5 次 = 250 次 | ~$0.001/次 | $0.25 |
| **单次总计** | | | **~$25** |

### 6.2 Pass@3 成本

Pass@3 需要跑 3 遍：$25 × 3 = **~$75**

### 6.3 建议预算

| 用途 | 次数 | 预算 |
|---|---|---|
| 首次基线建立 | 1 次 Pass@3 | $75 |
| 每次回归测试 | 1 次 Pass@1 (tier4 only, 10 用例) | $5 |
| 模型升级对比 | 2 次 Pass@3 (新旧模型各 1 次) | $150 |
| **总预算** | | **~$300** |

## 7. 实施路径

### Phase 1: 基础设施搭建（不需要 API 预算）

1. 创建 `backend/eval/` 目录结构
2. 实现 3 种 Grader（exact_match, field_check, llm_judge）
3. 实现 case_runner + suite_runner
4. 实现统计模块（metrics, confidence, regression）
5. 实现 config.yaml 解析 + run.py 入口
6. 用 StubLLM 验证流程跑通（Grader 评 StubLLM 输出）

### Phase 2: 种子数据集（不需要 API 预算）

1. 人工编写 10 个 Tier 1 种子用例 + 预期输出
2. 确保覆盖：技术选型冲突、范围争议、事实矛盾、无冲突、简单议题
3. 用 StubLLM 跑一遍，验证 Grader 评分逻辑正确

### Phase 3: 首次基线（需要 API 预算 ~$75）

1. 配置真实 LLM + LLM-judge
2. 跑 Tier 1 (10 用例) × Pass@3
3. 分析结果：
   - 哪些阶段最弱？（大概率是 cross_team 冲突检出 + arbitrate 裁决）
   - 哪些用例不稳定？
   - LLM-judge 是否可靠？（人工抽检 10%）
4. 建立基线报告，作为后续回归对比的锚点

### Phase 4: 扩展 + 迭代（需要 API 预算 ~$225）

1. 用 LLM 辅助生成 40 个扩展用例
2. 人工审核 + 修正预期
3. 跑完整 50 用例 × Pass@3
4. 识别系统边界（哪些类型处理好/差）
5. 每次改 prompt/模型/编排后跑回归

## 8. 与现有系统的集成

### 8.1 复用现有 regression.py

现有 `routers/regression.py` 已有 metrics 提取（`_extract_metrics`），但只记数字不评质量。

扩展方案：
- 保留现有数字 metrics（token、延迟、fallback）
- 新增 `eval/` 模块做语义质量评估
- 两者合并为完整报告：数字指标 + 语义评分

### 8.2 CI 集成

- Tier 4 回归集（10 用例）可加入 CI 流水线
- Pass@1 模式（快速，~$5/次）
- 仅在 PR 到 main 时触发
- 回归判定：Pass@1 下降 > 5% 或平均分下降 > 0.1 则阻止合并

### 8.3 与 pre-push Docker 检查的关系

- pre-push Docker 检查：ruff + mypy（代码质量，秒级）
- CI 回归测试：StubLLM 单元测试（功能正确性，分钟级）
- Eval 回归：真实 LLM 语义评估（输出质量，分钟级，需 API 预算）

三者互补，不替代。
