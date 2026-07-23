# ADR-010: 论点提纯架构与证据诚实性

## 状态

Accepted — 2026-07-22

## 背景

### 当前问题

Conclave 处于"flying blind"状态(见 `eval-framework-design.md` §0),但评估框架设计本身存在与系统实际使用场景的错位。经代码核验发现四个结构性问题:

**1. 证据系统的"假安检"**

`evidence_helpers.py:13-42` 的 `_make_common_knowledge_evidence` 在无文档/网络证据时,将冲突双方论点文本套入模板生成伪引用:

```python
"quote": f"（通用工程实践 · 倾向 A 方）{side_a or summary}。此原则基于行业常识..."
```

`fact_check_status` 由 `_preliminary_fact_check_status()`(`evidence_helpers.py:45-55`)按 source 前缀分配:`doc:*` 自动标 `verified`,从不比对 quote 是否真实存在于文档中。仲裁节点基于这些"已核查"标签的伪引用做裁决,产出物继承幻觉。

**2. 评估框架与实际场景脱节**

`eval-framework-design.md` §1.4 将"事实核查准确性"设为 25% 权重维度,但用户实际使用场景是"基于大模型内置知识互质提纯观点"——项目初期无法提供有效的前置依据(如公司内部信息、商业决策背景)。评估框架假设所有用例都有 `uploaded_docs`,与白板讨论场景脱节。

**3. intra_team 的反应式串行依赖**

`intra_team.py:42-95` 采用"N-1 并行 + 最后 1 反应"模式:最后一个角色用 `build_intra_react_prompt` 看到前面所有角色的 claims 再发言。这在无证据场景下产生锚定偏误——最后角色被前面论点带偏,而非独立思考。

**4. 无质量门禁机制**

`cross_team` 完成后直接进入下一阶段(`stage_runners.py:182-188`),无机制判断"讨论是否充分"。现有 `runner.py:519-577` 的动态路由回退由元认知 Agent 驱动,触发信号是阶段间跳转,非讨论质量。`_MAX_TOTAL_REGRESSIONS = 5` 的全局计数器粒度过粗。

### 用户本意

用户明确:现阶段核心是基于大模型内置知识让多方角色互质,将结论和观点提纯,而非当作证据。项目运行初期无法提供有效前置依据(如商业决策的公司基本信息)。评估框架的"跑测试不合常理"也源于此——测试用例假设有文档可上传,但实际场景是白板讨论。

## 决策

### 五项改动

#### 改动 1:证据诚实性 — 砍掉伪引用

`evidence_helpers.py:13-42` `_make_common_knowledge_evidence` 改为返回空 quote 占位:

```python
def _make_common_knowledge_evidence(conflict: dict) -> list[dict]:
    """无文档/网络证据时的降级：明确标注无证据，不制造伪引用。

    返回空 quote 占位，让 arbitrate 基于 side_a/side_b 论点本身质量裁决。
    strength=none 触发 prompts.py:119 的"无外部证据，低置信度裁决"路径。
    """
    return [
        {
            "evidence_id": "none-a",
            "quote": "",
            "source": "common_knowledge:none",
            "char_range": [0, 0],
            "strength": "none",
            "fact_check_status": "unverifiable",
        },
        {
            "evidence_id": "none-b",
            "quote": "",
            "source": "common_knowledge:none",
            "char_range": [0, 0],
            "strength": "none",
            "fact_check_status": "unverifiable",
        },
    ]
```

关键变化:
- `strength` 从 `"weak"` 改为 `"none"`。`prompts.py:69` 已定义 `none` = 无证据占位,但原代码用 `weak` 从未真正触发 `prompts.py:119` 的"全为 weak 或 none"降级路径。
- `quote` 清空,不再将 `side_a` 论点文本套模板制造伪引用。

#### 改动 2:intra_team 全并发 — 消除锚定偏误

`intra_team.py:42-95` 砍掉"最后 1 反应"逻辑,所有角色走 `build_intra_prompt`(独立思考)全并发:

```python
async def intra_team_node(state: MeetingState) -> MeetingState:
    """IntraTeam 阶段：全并发思考，所有角色独立产出 claims"""
    # ... members 解析逻辑不变 ...

    async def _think_one(role: Role, stance: str) -> dict[str, Any]:
        async def call_fn(anchor: str) -> dict[str, Any]:
            req = build_intra_prompt(role, state.clarified_topic or state.topic, stance, anchor=anchor)
            req.model = _resolve_model_for_call(state, role.value, "intra_team")
            resp = await execute_think(req)
            return resp.result
        result, confidence = await _run_with_consistency(state, "intra_team", call_fn)
        return {"role": role.value, "stance": stance, "claims": result.get("claims", []), "confidence": confidence, "react": False}

    role_results = await asyncio.gather(*[_think_one(r, s) for r, s in members])
    return await run_intra_team(state, list(role_results))
```

`build_intra_react_prompt` 保留不删(未来可作为配置项恢复),但 `intra_team_node` 不再调用。

**角色依赖处理**:当前 `team_config` 无 `depends_on` 字段。现阶段默认角色(product_architect + engineer)无强依赖,全并发安全。未来若引入安全专家等依赖型角色,在 `team_config` 加 `depends_on` 字段,按拓扑排序分组并发——无依赖的第一批,有依赖的第二批。本次不实现分组逻辑,预留扩展点。

#### 改动 3:cross_team 质量门禁 — 主持人举证否决

`cross_team` 完成后,主持人在发言中输出结构化门禁判断。门禁采用**举证责任倒置**:默认 NOT_PASS,主持人必须举证三个条件全部满足才能判 PASS。

**门禁条件**:
1. 每个角色的 claims 中至少有 1 条被其他角色直接反驳或质疑
2. 冲突列表覆盖了议题的核心决策点(非边缘细节)
3. 不存在"某角色 claims 全部未被任何冲突引用"的情况

**门禁输出结构**:
```json
{
  "gate_decision": "pass | supplement | re_examine",
  "gate_reason": "举证说明（若判 pass 必须逐条论证三个条件如何满足）",
  "weak_dimensions": ["未满足的条件编号"],
  "target_roles": ["supplement 时需补充的角色"]
}
```

**回退语义**:
- `supplement`:论点缺失/浅薄。仅 `target_roles` 角色带着冲突补充 claims,其他角色首轮论点保留。
- `re_examine`:论点有了但互质不深。全员重跑 cross_team,带"深挖以下维度"指令。
- `pass`:进入 arbitrate。

**循环上限**:supplement 最多 1 轮,re_examine 最多 1 轮,总计最多 2 次回退。超过则强制进 arbitrate,rationale 标注"讨论不充分,置信度低"。比 `runner.py:529` 的全局 `_MAX_TOTAL_REGRESSIONS = 5` 更严,因为每次回退是完整 LLM 调用,成本高。

#### 改动 4:门禁防偏四层机制

**第一层 — Prompt 举证倒置**:门禁 Prompt 默认 NOT_PASS,主持人必须主动证明三条件满足。见改动 3。

**第二层 — 代码层硬校验**(不可被 LLM 绕过):

`run_cross_team` 对主持人 `gate_decision == "pass"` 做后置校验:

```python
if gate_decision == "pass":
    # 条件3: 每个角色的 claims 至少有 1 条被冲突引用
    referenced_claims = set()
    for conflict in conflicts:
        referenced_claims.update(conflict.get("claim_refs", []))
    
    unreferenced_roles = set()
    for conclusion in state.team_conclusions:
        role_claim_ids = {c["id"] for c in conclusion.get("claims", [])}
        if role_claim_ids and not (role_claim_ids & referenced_claims):
            unreferenced_roles.add(conclusion["role"])
    
    if unreferenced_roles:
        # 代码否决主持人的 pass，强制降级为 supplement
        gate_decision = "supplement"
        target_roles = list(unreferenced_roles)
```

条件 3 是结构性验证(claims 是否被引用),代码可确定性判断。条件 1 和 2 需语义理解,只能靠 Prompt 约束。

**第三层 — 对抗性校准样本**(评估时):

黄金用例中埋两类对抗样本:
- "毒苹果"用例:某角色给出明显浅薄 claims,`expected.gate_decision != "pass"`
- "虚假和谐"用例:两角色论点趋同(伪冲突),`expected.gate_decision != "pass"`

**第四层 — 历史统计监控**(基线建立后):

评估报告加"门禁触发率"指标:
- 首轮 PASS 率 > 90% → 门禁形同虚设,需收紧 Prompt 条件
- 首轮 PASS 率 50-80% → 正常区间
- 首轮 PASS 率 < 30% → 门禁过严,可能浪费预算

#### 改动 5:评估框架维度重构

`eval-framework-design.md` §1.4 EvidenceCheck 维度从"证据驱动"转为"论点提纯驱动":

| 原维度(权重) | 新维度(权重) | 理由 |
|---|---|---|
| 证据相关性 30% | 论点区分度 15% | 双方论点是否真正对立,而非伪冲突 |
| 支持方向准确性 25% | 论点质量 20% | 论点是否有逻辑支撑、是否切中核心 |
| 证据强度判断 20% | 证据利用质量 15% | 有证据时正确引用,无证据时诚实标注 |
| 事实核查准确性 25% | 裁决归因清晰度 15% | arbitrate 是否说明基于哪些论点得出结论 |
| — | 置信度自评准确性 15% | 无证据时是否主动降级置信度 |
| — | 论点互补性 20% | 双方论点是否互补而非纯粹对立 |
| — | 门禁触发信号 15% | 首轮 pass=高分,supplement=中分,达上限=最低分 |

§1.5 Arbitrate 砍掉"采纳论点准确性",新增"论点综合质量"。

§4.2"通过"定义从"所有精确匹配全过 + LLM-judge >= 0.7"改为"low_confidence_flagged 必须通过 + LLM-judge 平均分 >= 0.7"。

### 保留的扩展点(现阶段不实现)

**证据比对层**:`_verify_against_source(meeting_id, evidence_chunk)` 函数签名预留。当 `source` 以 `doc:` 开头时,用 `store._raw_texts[doc_id]` + `char_range` 做原文比对(`documents.py:76` 已调用 `store_raw_text` 填充原文)。现阶段用户不上传文档,比对层零触发零成本。有可信内容后填充比对逻辑,自动对 `doc:*` 生效。

**角色依赖分组**:`team_config` 加 `depends_on` 字段,`intra_team_node` 按拓扑排序分组并发。现阶段默认角色无依赖,全并发安全。

## 与评估框架的关系

这五项改动是 `eval-framework-design.md` 能产出有效基准的前提:

1. **改动 1(砍伪引用)** — 否则评估的"事实核查准确性"维度在校验幻觉标签,系统产出物继承幻觉
2. **改动 2(全并发)** — 否则"角色视角一致性"维度测的是锚定偏误而非真实视角
3. **改动 3+4(门禁防偏)** — 门禁触发率本身就是评估信号,替代部分事后 LLM-judge,降低评估成本
4. **改动 5(维度重构)** — 否则评估维度与实际场景(白板讨论)脱节

**最小评估闭环**:5 个白板讨论黄金用例(无 uploaded_docs)+ 调整后维度 + 门禁触发率信号。成本 ~$3,当天出基线。完整 50 用例矩阵等系统稳定后再扩。

## 影响

### 代码变更

| 文件 | 变更 | 依赖 |
|---|---|---|
| `evidence_helpers.py` | `_make_common_knowledge_evidence` 改实现 | 无 |
| `intra_team.py` | 全并发,砍反应式 | 无 |
| `prompts.py` | cross_team 主持人 Prompt 增加门禁输出结构 | 无 |
| `stage_runners.py` | `run_cross_team` 解析 `gate_decision`,代码层校验条件 3 | cross_team 输出携带 `claim_refs` |
| `models.py` / `MeetingState` | 新增 `gate_history` 字段 | 无 |
| `eval-framework-design.md` | §1.4/§1.5/§4.2 维度重构 | 无 |

### 新增节点(第二阶段)

`intra_team_refine` 轻量节点:复用 `build_intra_prompt`,带 conflicts 上下文,仅 `target_roles` 参与补充。本次 ADR 记录设计,实现跟随门禁机制一起做。

### 测试影响

- `test_evidence_fact_check.py` 需更新:`strength` 从 `weak` 改 `none`,`quote` 改空
- `test_core_flow.py` 需验证全并发不破坏 claims 聚合
- `test_determinism.py` 需验证全并发下 `_run_with_consistency` 仍稳定

### 不在此 ADR 范围

- 50 用例完整评估矩阵(等 5 黄金用例基线稳定后再扩)
- Factuality Grader / 证据比对层实现(有可信内容后再做)
- 角色依赖分组实现(引入依赖型角色后再做)
- Web 路径缓存比对(`playwright_search` 返回结构变更,独立 ADR)

## 执行顺序

1. `evidence_helpers.py` 砍伪引用(单函数,10 分钟)
2. `intra_team.py` 全并发(单节点,15 分钟)
3. 跑 `test_core_flow.py` / `test_determinism.py` / `test_evidence_fact_check.py` 验证无回归
4. `prompts.py` + `stage_runners.py` 门禁机制(Prompt + 代码层校验)
5. `MeetingState` 加 `gate_history` 字段
6. 写 5 个白板讨论黄金用例
7. 更新 `eval-framework-design.md` 维度重构
8. 跑首次基线(StubLLM 验证流程,再真实 LLM 出基线)
