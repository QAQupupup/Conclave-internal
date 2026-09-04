# Prompt 回归测试与多 Agent 评分 — 实施任务清单

> ADR: docs/design/adr/015-prompt-regression-and-multi-agent-scoring.md
> 创建时间: 2026-08-02
> 状态: Phase 1 待开始

---

## Phase 1：Prompt Snapshot + 版本绑定

目标：每次 eval 运行自动捕获所有 prompt 文件快照，评估结果可追溯到精确 prompt 版本。

- [ ] **T1.1** 后端新增 `GET /system/prompts/snapshot` 端点
  - 收集以下文件的 hash + 长度 + git commit：
    - `app/orchestrator/system_prompt.py`
    - `app/agents/role_templates.py`
    - `app/agents/compute.py`
    - `app/orchestrator/stage_runners.py`
    - `app/orchestrator/borrow_helpers.py`
    - `app/plugins/builtin/auth/middleware.py`（如含 prompt 逻辑）
  - 返回 `snapshot_id`(sha256)、`git_commit`、`git_dirty`、各文件 hash
  - 文件位置: `app/routers/system.py`（新建）或扩展现有 debug 路由
  - 验收: `curl /system/prompts/snapshot` 返回合法 JSON，修改任一 prompt 文件后 snapshot_id 变化

- [ ] **T1.2** eval_v2 SuiteResult 增加 prompt_snapshot 字段
  - 文件: `backend/eval_v2/models/result.py`
  - 新增字段: `prompt_snapshot_id: str`, `prompt_snapshot: dict`, `git_commit: str`, `git_dirty: bool`
  - 验收: 序列化/反序列化正常，向后兼容（默认空值）

- [ ] **T1.3** SUTClient 在运行时自动获取 snapshot
  - 文件: `backend/eval_v2/runners/sut_client.py`
  - 在创建会议前/后调用 `/system/prompts/snapshot`，绑定到 SuiteResult
  - 验收: 运行 eval 后，报告 JSON 中包含 prompt_snapshot 字段

- [ ] **T1.4** Vault 导出包含 snapshot
  - 文件: `backend/eval_v2/vault/exporter.py`
  - 导出时包含 prompt snapshot 信息
  - 验收: vault 中历史记录可通过 snapshot_id 查询

---

## Phase 2：逐话题得分矩阵 + 净分计算

目标：版本×话题得分矩阵，自动识别正向/负向 prompt 改动，关联到具体 prompt 文件。

- [ ] **T2.1** 实现 PromptVersionTracker
  - 文件: `backend/eval_v2/regression/prompt_tracker.py`（新建）
  - 从 vault 加载 N 个历史版本的 SuiteResult
  - 构建 `{case_id: {snapshot_id: score}}` 矩阵
  - 输出每个话题的版本间得分变化趋势
  - 验收: 给定 >=2 次历史运行，能输出完整的话题×版本矩阵

- [ ] **T2.2** 扩展 regression/comparator.py
  - 新增 `compute_topic_trends()` 方法：逐话题输出趋势（↑/↓/→）
  - 新增 `compute_net_prompt_effect()` 方法：加权净分（安全性*3 + 事实准确性*3 + 指令遵循*2 + 角色一致*1 + 结构*1）
  - 新增 `correlate_with_prompt_diff()` 方法：相邻版本间分数变化 > 0.1 的话题，标注哪些 prompt 文件 hash 发生了变化
  - 验收: 两次运行对比时，能输出逐话题 delta + 可能关联的 prompt 文件

- [ ] **T2.3** HTML 报告增加 "Prompt 版本对比" 页面
  - 文件: `backend/eval_v2/reports/html_report.py`
  - 新增矩阵热力图（话题×版本，绿=正向，红=负向）
  - 新增净分汇总卡片
  - 验收: 报告中可看到每个话题在每个版本的得分和趋势

- [ ] **T2.4** CLI 入口扩展
  - 文件: `backend/eval_v2/run.py`
  - 新增 `--prompt-regression` flag
  - 新增 `--baseline-snapshot` 参数（指定对比基线）
  - 验收: `python -m eval_v2.run --prompt-regression` 可运行

---

## Phase 3：L5 多 Agent 讨论质量评分

目标：不只评最终产出，还评多 agent 讨论过程质量（信息增益、分歧质量、收敛性、角色履行、引用完整性）。

- [ ] **T3.1** 定义 L5 评分模型
  - 文件: `backend/eval_v2/scorers/l5_multi_agent.py`（新建）
  - 维度:
    - 信息增益（information_gain）：新 claim 占比，权重 2
    - 分歧质量（conflict_quality）：conflict 是否有实质论点，权重 2
    - 收敛性（convergence）：conflict 被 decision 解决的比例，权重 2
    - 角色履行（role_adherence）：发言是否符合角色画像，权重 3
    - 引用完整性（evidence_coverage）：claim 有 evidence 的比例，权重 2
    - 无重复发言（non_repetition）：连续发言语义差异，权重 1
  - 总分: 加权平均 0-10
  - 验收: 单元测试覆盖每个维度的评分逻辑

- [ ] **T3.2** 从 audit_data 提取发言序列
  - 从 `/meetings/{id}/audit` 返回的 events 中提取：
    - 每个 agent 的发言列表（含 role、timestamp、claim 内容）
    - claims 链和 evidence_refs
    - conflicts 和 decisions
  - 文件: `backend/eval_v2/scorers/l5_multi_agent.py` 中的 `extract_discussion_sequence()`
  - 验收: 给定一个完成的会议 audit_data，能提取结构化的发言序列

- [ ] **T3.3** 实现信息增益评分
  - 对每条 claim 计算与前序所有 claim 的 embedding 相似度
  - 相似度 < 0.7 视为新信息
  - 信息增益 = 新信息 claim 数 / 总 claim 数
  - 复用现有 embedding 客户端（`app/rag/store.py` 或独立 HTTP 调用）
  - 验收: 对已知重复发言和新发言的测试用例评分正确

- [ ] **T3.4** 实现角色履行评分（LLM Judge）
  - 用 Judge 模型判断每条发言是否符合角色画像
  - Judge prompt: "以下发言来自{角色名}，其职责是{角色画像}。请判断该发言是否符合其角色定位（0-10分），给出理由。"
  - 聚合: 所有发言的角色履行均分
  - 验收: 安全专家讲代码实现应低分，讲安全风险应高分

- [ ] **T3.5** 实现收敛性和引用完整性评分
  - 收敛性 = len(decisions) / len(conflicts)（有 conflict 时）
  - 引用完整性 = 有 evidence_refs 的 claim 数 / 总 claim 数
  - 验收: 全有 decision 且全有引用 = 10分，全无 = 0分

- [ ] **T3.6** 集成到 SuiteResult 和报告
  - SuiteResult 新增 `multi_agent_quality_score: float`
  - HTML 报告新增"多 Agent 讨论质量"雷达图
  - 验收: 运行 eval 后，报告中展示 L5 各维度分数和雷达图

---

## Phase 4：CI 集成 + 退化阻断

目标：修改 prompt 时自动跑回归，安全性/事实准确性退化时阻断提交。

- [ ] **T4.1** 新增 `prompt-regression` 快速模式
  - 只跑 edge_cases + 安全相关话题（约 10 个用例）
  - 跳过 L3/L5 语义评分（只用 L0-L2 结构检查）
  - 完成时间 < 5 分钟（适合 pre-push hook）
  - 验收: 快速模式能在 5 分钟内跑完，给出 pass/fail

- [ ] **T4.2** pre-push hook 集成
  - 检测 staged 文件是否包含 prompt 相关文件
  - 如果包含，自动跑 prompt-regression 快速模式
  - 安全性或事实准确性维度下降 > 0.1 时阻断推送
  - 验收: 修改 role_templates.py 后 push 触发回归测试，注入测试失败时阻断

- [ ] **T4.3** 新增话题用例增量机制
  - 每次修复 prompt 相关 bug 时，必须在 `eval_v2/dataset/` 新增一个回归话题
  - 在 docs/pitfalls.md 中记录此规则
  - 验收: 规则文档化，并有示例

- [ ] **T4.4** 注册 `prompt-regression` skill
  - 在 SKILL_REGISTRY.md 新增条目
  - 触发关键词: "prompt回归"、"改了prompt"、"测prompt"、"prompt改动"
  - 验收: AI 助手能自动发现并调用该 skill

---

## 完成定义（DoD）

- [ ] Phase 1-4 所有任务完成
- [ ] eval_v2 测试套件新增测试覆盖所有新模块
- [ ] 至少有一次手动端到端验证：修改一个 prompt → 跑回归 → 看到分数变化 → 报告正确关联到改动文件
- [ ] Docker 容器内全量测试通过
- [ ] 文档更新（AGENTS.md、SKILL_REGISTRY.md）
