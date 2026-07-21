# 模型选型规格说明

> **状态**: 草稿（Draft）
> **日期**: 2026-07-15
> **关联**: [模型基准测试报告](../research/model-benchmark-2026-07-15.md)
> **代码模块**: `backend/app/llm_providers.py`

---

## 概述

Conclave 的六阶段会议流程对 LLM 有不同的质量/速度/成本需求。本文档定义阶段级模型分配策略，基于 2026-07-15 的 11 模型统一基准测试结果（其中 7 个可用，Qwen 全系 + GLM-4.5-Air 因不支持 `response_format: json_object` 已排除）。

---

## 阶段需求分析

| 阶段 | 核心需求 | 对模型的敏感度 | 失败代价 |
|------|---------|---------------|---------|
| clarify | 需求澄清，提取议题结构 | JSON 结构化输出必须准确 | 高 — 结构错误导致后续阶段全部错乱 |
| intra_team | 发散讨论，多视角脑暴 | 速度优先，质量够用即可 | 低 — 单次发言可被 cross_team 纠正 |
| cross_team | 交叉论证，逻辑碰撞 | 推理能力必须强 | 中 — 逻辑错误可能误导 arbitrate |
| evidence_check | 证据对照，事实核查 | 抗幻觉必须强，事实对照严格 | 中 — 错误证据影响裁决 |
| arbitrate | 最终裁决，综合判断 | 综合质量最高 | 高 — 最终决策不可逆 |
| produce | 报告产出，面向用户 | 格式规范、语言流畅 | 高 — 直接面向用户 |

---

## 推荐模型分配

基于 [模型基准测试报告](../research/model-benchmark-2026-07-15.md)：

```python
# backend/app/llm_providers.py 中的 STAGE_DEFAULT_MODELS
STAGE_DEFAULT_MODELS = {
    "clarify":        "zai-org/GLM-5.2",
    "intra_team":     "ByteDance-Seed/Seed-OSS-36B-Instruct",
    "cross_team":     "MiniMaxAI/MiniMax-M2.5",
    "evidence_check": "MiniMaxAI/MiniMax-M2.5",
    "arbitrate":      "zai-org/GLM-5.2",
    "produce":        "zai-org/GLM-5.2",
}
```

### 成本估算

5 角色 × 10 轮，每轮 3000 input + 1000 output tokens：

| 阶段 | 模型 | 单价 (¥/M) | 单轮成本 | 10 轮 |
|------|------|-----------|---------|-------|
| clarify | GLM-5.2 | 8.0/28.0 | ¥0.26 | ¥2.60 |
| intra_team | Seed-OSS-36B | 1.5/4.0 | ¥0.04 | ¥0.43 |
| cross_team | MiniMax-M2.5 | 2.1/8.4 | ¥0.07 | ¥0.74 |
| evidence_check | MiniMax-M2.5 | 2.1/8.4 | ¥0.07 | ¥0.74 |
| arbitrate | GLM-5.2 | 8.0/28.0 | ¥0.26 | ¥2.60 |
| produce | GLM-5.2 | 8.0/28.0 | ¥0.26 | ¥2.60 |
| **合计** | | | **¥0.97** | **¥9.70** |

对比全 GLM-5.2：¥26.00 → 节省 63%。

---

## 架构设计

### 三级优先级

```
阶段级覆盖 (@intra_team)     ← 最高优先级，用户可手动覆盖
    ↓ fallback
角色级覆盖 (engineer)        ← 中间优先级
    ↓ fallback
会议级默认 (meeting model)    ← 最低优先级，全局生效
    ↓ fallback
ENV 默认 (CONCLAVE_LLM_MODEL)
```

### 代码链路

```
会议启动 → runner.py
  └─ resolve_models_for_meeting()
       ├─ 读取 role_configs.model_override       (角色级)
       ├─ 读取 stage_overrides 或 STAGE_DEFAULT_MODELS (阶段级)
       └─ 读取 meeting_model / ENV 默认            (会议级)
            └─ 生成 resolved_models dict → 存入 MeetingState

运行时 LLM 调用 → agents/llm.py
  └─ resolve_model_from_snapshot(resolved_models, role, stage)
       └─ 返回 "provider_id:model_id"
```

### 约束

- 模型快照在会议启动时一次性锁定，运行中不允许切换（返回 403）
- 仅 `DONE` 状态的会议可以修改模型配置
- 阶段级覆盖通过 `STAGE_DEFAULT_MODELS` 自动生效，用户无需手动配置

---

## 前端交互设计（待实现）

### 阶段模型配置面板

在 `CreateMeeting` 或 `ModelSelector` 中展示：

```
┌─────────────────────────────────────────┐
│  阶段模型配置                    [展开]  │
├─────────────────────────────────────────┤
│  需求澄清 (clarify)     GLM-5.2    [▼]  │
│  内部讨论 (intra_team)  Seed-36B   [▼]  │
│  交叉论证 (cross_team)  MiniMax    [▼]  │
│  证据核查 (evidence)    MiniMax    [▼]  │
│  最终裁决 (arbitrate)   GLM-5.2    [▼]  │
│  报告产出 (produce)     GLM-5.2    [▼]  │
│                                         │
│  💰 预估单轮成本: ¥0.97                 │
│  💰 预估总计 (10轮): ¥9.70              │
└─────────────────────────────────────────┘
```

### 成本护栏

- 价格对比：实时显示"当前选择 vs 默认"的价格差异
- 高成本告警：超过 ¥8.0/M 标记橙色
- 预算封顶（可选）：`CONCLAVE_MAX_MODEL_PRICE` 环境变量

---

## 实施计划

| 步骤 | 内容 | 风险 | 依赖 |
|------|------|------|------|
| 1 | 添加 `STAGE_DEFAULT_MODELS` 到 `llm_providers.py` | 低 | 无 |
| 2 | 在 `resolve_models_for_meeting()` 中应用默认阶段映射 | 低 | 步骤 1 |
| 3 | 更新 `RECOMMENDED_MODELS` 加入 MiniMax-M2.5 和 Seed-OSS-36B | 低 | 步骤 1 |
| 4 | 前端阶段级模型配置面板 | 中 | 步骤 3 |
| 5 | 成本预估 + 高成本告警 | 低 | 步骤 4 |
| 6 | 预算封顶护栏 | 低 | 步骤 5 |

---

## 模型变更流程

当需要更换某个阶段的模型时：

1. 运行基准测试验证新模型：`python tests/run_model_benchmark.py --models "新模型ID"`
2. 对比基准报告中的评分，确认不低于当前推荐（如 intra_team 不低于 80.8）
3. 更新 `STAGE_DEFAULT_MODELS` 和本文档
4. 更新 `RECOMMENDED_MODELS`
5. 提交 commit 时附带基准测试结果对比

### 高成本模型切换

如切换为更高成本模型（如 intra_team 从 Seed-OSS-36B 改为 GLM-5.2）：

1. 在 PR 中注明成本影响（单轮 + 10 轮差额）
2. 在 `CONCLAVE_MAX_MODEL_PRICE` 范围内方可合并
3. 前端自动显示成本差异警告

---

## 参考

- [模型基准测试报告](../research/model-benchmark-2026-07-15.md) — 11 模型四维度测试结果（7 可用，4 排除）
- [PROJECT_CONVENTIONS.md](../../PROJECT_CONVENTIONS.md) — 项目工程规范
- `backend/app/llm_providers.py` — 模型选型核心模块
- `backend/app/agents/llm.py` — LLM 调用链路