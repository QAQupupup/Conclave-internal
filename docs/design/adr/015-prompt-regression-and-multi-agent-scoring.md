# ADR-015: Prompt 回归测试与多 Agent 并行讨论质量评估

## 状态

Proposed — 2026-08-02

## 背景

### 问题陈述

当开发者修改 agent 的 system prompt、角色画像、阶段指令或仲裁逻辑时，面临三个核心问题：

1. **无量化反馈**：改动 prompt 后，无法知道变好了还是变差了，只能靠"感觉这次输出更流畅"
2. **话题敏感性盲区**：A 话题上改好了，B 话题可能退化，但没有逐话题得分矩阵
3. **多 Agent 交互黑箱**：单 agent prompt 改好了，多 agent 并行讨论时的群体动力学（信息增益、分歧质量、收敛性、角色履行）完全不可观测

### 代码核验（现有基础设施）

```bash
# 已有评估框架
ls backend/eval_v2/
# → dataset/ (38个测试用例, 覆盖 prd/design/research/business/edge_cases)
# → scorers/ (l0_system_health ~ l4_comparative 五层评分)
# → regression/comparator.py (已有基线对比+Fisher精确检验+Cohen's h效应量)
# → ablation/comparator.py (已有Pairwise盲评)
# → llm_judge/ (独立Judge模型+偏差缓解)
# → vault/ (历史结果导出)

# 已有回归检测能力
grep "compare_with_baseline" backend/eval_v2/regression/comparator.py
# → pass@1/pass@3/avg_score/cost/latency 五维度对比+显著性检验

# 缺失能力
grep -r "prompt_version\|prompt_hash\|prompt_snapshot" backend/eval_v2/  # 零结果
grep -r "information_gain\|convergence\|role_adherence\|group_dynamics" backend/  # 零结果
grep -r "multi_agent_score\|parallel_discussion" backend/eval_v2/  # 零结果
```

### 现有 eval_v2 能力与缺口

| 能力 | 状态 | 说明 |
|------|------|------|
| 结构化检查（字段、长度、终态） | ✅ 已有 | L0-L2 scorer |
| LLM-as-Judge 语义评分 | ✅ 已有 | L3 scorer，独立Judge模型 |
| 两版本对比+统计显著性 | ✅ 已有 | regression/comparator.py |
| 消融实验（多Agent vs 单Agent） | ✅ 已有 | ablation/comparator.py |
| 话题用例库 | ✅ 已有 | 38个用例，5个类别 |
| HTML 报告 | ✅ 已有 | reports/html_report.py |
| **Prompt 版本绑定** | ❌ 缺失 | eval结果不关联prompt版本/hash |
| **逐话题历史趋势** | ❌ 缺失 | 只有两版本pairwise，无N版本趋势 |
| **Prompt diff 关联** | ❌ 缺失 | 分数变化不关联具体prompt改动行 |
| **多Agent群体动力学** | ❌ 缺失 | 无信息增益/收敛性/角色履行评分 |
| **并行讨论整体分** | ❌ 缺失 | 只评最终产出，不评讨论过程质量 |

## 决策

### 总体架构：在 eval_v2 基础上增量扩展三层能力

不重写 eval_v2，而是在其现有五层 scorer、回归对比、vault 历史存储基础上增加三个模块：

### 1. Prompt Version Snapshot（提示词版本快照）

**目标**：每次 eval 运行自动捕获当前所有 prompt 源文件的 hash 和内容快照，使每个评估结果可追溯到精确的 prompt 版本。

**实现**：
- 在 `eval_v2/runners/sut_client.py` 创建会议时，通过新 API `GET /system/prompts/snapshot` 获取当前所有 prompt 文件的 hash 和内容
- SUT 后端新增端点 `GET /system/prompts/snapshot`，返回：
  ```json
  {
    "snapshot_id": "sha256:abc123...",
    "timestamp": "2026-08-02T...",
    "git_commit": "a1b2c3d",
    "git_dirty": true,
    "prompts": {
      "orchestrator.system_prompt": { "hash": "sha256:...", "length": 2341 },
      "agents.role_templates.product_architect": { "hash": "sha256:...", "length": 892 },
      "agents.role_templates.engineer": { "hash": "sha256:...", "length": 756 },
      "agents.compute.intra_team.engineer": { "hash": "sha256:...", "length": 423 },
      ...
    }
  }
  ```
- SuiteResult 新增字段 `prompt_snapshot_id`、`prompt_snapshot`
- Vault 导出包含 prompt snapshot，历史对比可定位到具体哪个 prompt 文件的改动与分数变化相关

**Prompt 文件范围**（从代码中识别）：
- `app/orchestrator/system_prompt.py` — 系统提示词
- `app/agents/role_templates.py` — 7个角色画像
- `app/agents/compute.py` — IntraTeam/InterTeam 模板
- `app/orchestrator/stage_runners.py` — 各阶段指令
- `app/orchestrator/borrow_helpers.py` — 借调逻辑提示

### 2. Per-Topic Score History Matrix（逐话题得分历史矩阵）

**目标**：跟踪每个话题在每个 prompt 版本上的得分，形成版本×话题的得分矩阵，自动识别正向/负向改动。

**实现**：
- Vault 历史存储新增矩阵视图：
  ```
  topics × versions matrix:
  ┌──────────────────┬────────┬────────┬────────┬────────┐
  │ Topic            │ v1.2   │ v1.3   │ v1.4   │ Trend  │
  ├──────────────────┼────────┼────────┼────────┼────────┤
  │ crypto-crash     │ 7.2    │ 8.1 ↑  │ 7.5 ↓  │ ~      │
  │ medical-advice   │ 8.0    │ 7.8 ↓  │ 8.3 ↑  │ ↑      │
  │ code-review      │ 6.5    │ 7.9 ↑  │ 7.0 ↓  │ ~      │
  │ prompt-injection │ 9.0    │ 9.0    │ 9.2 ↑  │ ↑      │
  │ ...              │        │        │        │        │
  └──────────────────┴────────┴────────┴────────┴────────┘
  净变化: +1.2 / -0.8 / 净正向 = +0.4
  ```
- `eval_v2/regression/comparator.py` 扩展：
  - 新增 `PromptVersionTracker` 类，从 vault 加载 N 个历史版本
  - 新增 `compute_topic_trends()` 方法，输出每个话题的版本间得分变化
  - 新增 `compute_net_prompt_effect()` 方法，计算加权净分
  - 新增 `correlate_with_prompt_diff()` 方法，当两个相邻版本间某个话题分数变化 > 0.1 时，自动标注可能相关的 prompt 文件变动（基于 snapshot hash 变化）

- **评分维度**（复用现有 L0-L4 scorer，新增权重汇总）：
  - **事实准确性**（L3 语义评分的准确性子项）：权重 3x
  - **安全性**（注入防御、危险建议拒绝）：权重 3x
  - **遵循指令度**（是否遵守 prompt 中的约束）：权重 2x
  - **角色一致性**（是否保持设定的角色/风格）：权重 1x
  - **结构完整性**（L2 字段检查）：权重 1x

### 3. Multi-Agent Discussion Quality Scoring（多 Agent 讨论质量评分）

**目标**：不只评最终产出，还要评多 agent 并行讨论过程的质量。

**新增 L5 scorer**：`eval_v2/scorers/l5_multi_agent.py`，评分维度：

| 维度 | 定义 | 测量方式 |
|------|------|----------|
| **信息增益** | 后续 agent 是否在前序 agent 基础上提供了新信息 | 计算 claim 语义相似度，新 claim 占比 |
| **分歧质量** | 是否出现有价值的分歧（vs 无意义附和 vs 群体思维） | 检测 conflict 是否有实质论点支撑，而非单纯反对 |
| **收敛性** | 讨论是否在有限轮次内收敛到结论 | arbitrate 阶段是否解决了所有 conflict |
| **角色履行** | 每个 agent 是否坚守了自身角色 | 检查 security_expert 是否在讲安全问题而非产品设计 |
| **引用完整性** | claim 是否有 evidence 支撑，跨 agent 引用链是否完整 | evidence_set 对 claims 的覆盖率 |
| **无重复发言** | 同一 agent 不重复自己或他人已说的观点 | 检测连续发言的语义相似度 |

**测量实现**：
- 利用已有的 audit_data（CaseRunner 已通过 `/meetings/{id}/audit` 获取完整事件流）
- 从 audit_data 中提取每个阶段、每个 agent 的发言序列
- 信息增益：对 claim 文本做 embedding 相似度计算，与前序所有 claim 比较，相似度 < 0.7 视为新信息
- 角色履行：用 LLM Judge 判断每条发言是否符合该角色的职责描述（role_templates.py 中的画像）
- 收敛性：检查 arbitrate 阶段 decisions 数量 vs cross_team 阶段 conflicts 数量
- 引用完整性：检查 claims 中有 evidence_refs 的比例

**并行讨论整体分** = Σ(维度分 × 权重)，作为 SuiteResult 的新指标 `multi_agent_quality_score`。

### API 扩展

```
GET  /system/prompts/snapshot     → 返回当前所有 prompt 文件快照
POST /eval/run-prompt-regression  → 触发一次 prompt 回归测试（可选指定 baseline snapshot）
GET  /eval/prompt-matrix          → 返回逐话题得分矩阵
GET  /eval/multi-agent-quality/{meeting_id} → 返回单场会议的多Agent讨论质量分
```

### 命令行入口

```bash
# 在 eval_v2 现有 run.py 基础上扩展
python -m eval_v2.run --prompt-regression --baseline-snapshot latest
python -m eval_v2.run --prompt-regression --topics edge_cases/*  # 只跑边界case
python -m eval_v2.run --multi-agent-quality  # 包含L5 scorer
```

## 为什么不在 eval_v2 之外另起炉灶

1. eval_v2 已有 38 个话题用例、5 层评分器、独立 Judge、统计检验、vault 存储、HTML 报告
2. prompt 回归本质是 eval_v2 的一个维度扩展，不需要新框架
3. 复用现有 Judge 基础设施保证评分一致性
4. 现有 vault 机制可直接扩展存储 prompt snapshot

## 实施计划

### Phase 1：Prompt Snapshot + 版本绑定（1-2天）
1. 后端实现 `GET /system/prompts/snapshot` 端点
2. eval_v2 SuiteResult 增加 prompt_snapshot 字段
3. CaseRunner/SUTClient 在创建会议时获取 snapshot
4. Vault 导出包含 snapshot

### Phase 2：逐话题得分矩阵 + 净分计算（2-3天）
1. 实现 PromptVersionTracker，从 vault 加载历史矩阵
2. 扩展 regression/comparator.py，增加 topic trends 和 net effect
3. 实现 correlate_with_prompt_diff，自动标注分数变化对应的 prompt 改动文件
4. HTML 报告增加"Prompt 版本对比"页面

### Phase 3：L5 多 Agent 讨论质量评分（3-5天）
1. 实现 l5_multi_agent.py scorer
2. 从 audit_data 提取发言序列和 claim 链
3. 实现信息增益、角色履行、收敛性评分
4. 集成到 SuiteResult 和 HTML 报告
5. 添加话题用例中专门针对多 Agent 质量的测试场景

### Phase 4：CI 集成 + 退化阻断（1-2天）
1. pre-push hook 中对 prompt 改动自动跑关键话题的快速回归
2. 如果安全性/事实准确性维度下降超过阈值（0.1），阻断提交
3. 新增 `prompt-regression` skill 到 SKILL_REGISTRY.md

## 约束与风险

### Judge 一致性风险
- LLM-as-Judge 本身有方差，必须用 judge_runs=3 取中位数，标准差 > 0.2 标记为 unreliable
- 不同 Judge 模型可能给出不同分数，Judge 模型变更也需要做回归

### 话题覆盖不足风险
- 38 个话题可能不够覆盖所有 prompt 改动的影响面
- 需要建立话题增量机制：每次修复一个 prompt 相关 bug 时，必须新增一个回归话题

### 计算成本
- L5 评分需要对每条 claim 做 embedding 和 LLM Judge 调用，成本约为现有评估的 2-3x
- Phase 1-2 不增加额外 LLM 调用，Phase 3 增加成本但提供关键能力

### 不做的事
- 不做 prompt 自动优化（不根据分数自动修改 prompt，只做测量和反馈）
- 不做 A/B 测试框架（同一版本对同一话题跑 N 次取均值是现有 Pass@k 机制）
- 不做实时监控（这是开发期工具，不是生产期监控）
