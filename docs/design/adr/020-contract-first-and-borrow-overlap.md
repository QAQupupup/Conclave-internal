# ADR-020: 契约优先工程固化与借调重叠检测

## 状态

Accepted — 2026-09-13

裁决记录（用户 2026-09-13 裁决「D1-D6 按你推荐的来」+ 认可 shadcn/ui CLI 增强建议）：

- 迭代方向报告（`iteration-direction-plan/iteration-direction-plan.html`）D1-D6 全部采纳推荐项（A），与本 ADR 决策表映射：报告 D1→本 ADR D1、报告 D2→D2、报告 D3→D3（方向定案、实施推迟另开 ADR）、报告 D4→D4、报告 D5→D5（方向定案、实施推迟另开 ADR）、报告 D6→D6
- 新增决策 D7-D11 为选型落地细节，随「按推荐裁决」一并生效；D7（Orval 选型）、D11（shadcn/ui CLI）在裁决前已向用户单独呈报并获认可

---

## 背景与问题

### 现状一：API 契约层是当前最大的不稳定源（2026-09-13 grep 逐项核验）

| 事实 | 核验方式 |
|---|---|
| 后端共 **171 处路由声明**（26 个文件），仅 **30 处显式 `response_model=`**，覆盖率 ≈ 18% | `grep '@\w*router\w*\.(get\|post\|...)'` 计 171；`grep 'response_model\s*='` 计 30 |
| 重灾区：`routers/meetings.py` 40 个端点仅 1 处 `response_model` | 同上分文件计数 |
| OpenAPI 文档因此残缺，Swagger 无法作为前后端对接凭据 | 由上两条推得（FastAPI 无 response_model 则响应 schema 为 {}） |
| 前端 `zod ^3.23.0` 已装入 `package.json` 但 `src/` 内**零 import** | `grep "from 'zod'" frontend/src` 无匹配 |
| 前端类型全手写：`src/types/` 5 文件约 695 行 + 散落内联类型，与后端无生成关系；`lib/api.ts` 1243 行手写 fetch 封装 | 契约层调研（本会话）+ `package.json` 无任何代码生成工具 |
| 前端无运行时响应校验，全靠 `as` 断言 | 同上 |

### 现状二：LLM 输出模型三份真相源

LLM 结构化输出的模型定义散落在三处：`conclave_core` 领域模型（`charter.py` / `state.py` / `evidence.py` 等）、`app/agents/schemas.py`、StubLLM 兜底输出内联构造。三者各自演化，与 ADR-019 在 DB 层发现的「三轨并行、零单一真相」是同构问题。

### 现状三：借调查重只防「同名」，不防「同职」

| 事实 | 核验方式 |
|---|---|
| `charter_logic.py::is_already_borrowed` 是字符串前缀匹配（`f"{target_role}::"`），`borrow_history` 条目格式 `{role}::{verdict}` | grep 核验 `charter_logic.py` 101-106 行 |
| 自动借调配额 `AUTO_BORROW_THRESHOLD = 3`，超出挂起等审批 | `borrow_helpers.py` 49 行 |
| 同时在会借调角色硬上限 2（三处硬编码拒绝） | 契约层/借调研判（本会话，`borrow_helpers.py` 186-412 行） |
| v1 实际出现过借调大量职责高度重合的临时专家（架构师 / 微服务架构师 / 数据架构师 / 数据分析师 / 法律咨询顾问 / 合规专员等） | 用户陈述（2026-09-13） |

数量约束（上限 2 + 配额 3 + 单次发言 + 冻结）已解决「借太多」，但「架构师」与「微服务架构师」字符串不同即视为两个角色，**职责重叠问题当前无解**。

### 现状四：工程前提事实

| 事实 | 核验方式 |
|---|---|
| 前端构建/开发镜像为 `node:20-slim` / `node:20-alpine`（华为 SWR 源） | `frontend/Dockerfile` 6 行、`Dockerfile.dev` 3 行 |
| Orval 8.32.0 `engines.node >= 22.18.0`、MIT | npm registry `orval/8.32.0` 包文档 |
| UI 栈已是 Tailwind CSS v4 + 16 个 Radix primitives + CVA + clsx + tailwind-merge + lucide-react + ECharts，全部 MIT，与 shadcn/ui 工具链同源 | `frontend/package.json` |
| hey-api 仍 0.99.0 未发 1.0；openapi-zod-client 官方停止维护 | npm dist-tags / GitHub（2026-09-13 核验，见会话检查点 `20260913-0733`/`20260913-0836`） |

### 约束

- 设计原则对齐：原则 2 借调三问法（本 ADR 扩展为四问）、原则 6 MVP 三问、原则 7 反架构沉迷、原则 9 分阶段温度（借调评估属裁决类，temperature 0 不变）
- 镜像源纪律：所有 npm 依赖走 npmmirror（PROJECT_CONVENTIONS）
- 不随意改动前端既有视觉风格（用户红线）；`ui_design_system.yaml` 红线不变

---

## 决策

| # | 决策 | 理由 | 被推翻的替代方案 |
|---|------|------|-----------------|
| D1 | **迭代主轴：P0 契约优先工程固化 → P1 方法论库化，串行推进** | 契约层是 LLM/Agent 产出稳定性的地基（设计原则 7：先跑通主闭环）；方法论库依赖稳定契约才能可靠产出 | 「双线并行」——资源分散、契约缺口持续放大；「方法论先行」——地基不稳时模板产出仍会漂移 |
| D2 | **契约桥接全链路**：response_model 补齐 → openapi.json 成 CI 产物 → 代码生成类型+zod+Query hooks → 契约 diff 门禁 | 只补类型不做运行时校验与门禁，漂移会在两周内复发；全链路才能形成「后端改契约 → 前端编译期/运行期即失败」的闭环 | 「仅生成类型」——无运行时校验、无门禁，漂移不可检测；「继续手写」——现状即事故源 |
| D3 | **方法论载体：methodology-as-skill**（yaml 方法论文件 + PRODUCE 模板扩展），方向定案，**实施推迟至 P1 另开 ADR** | 复用现有 Skill 注入体系（四维激活匹配），零新架构；本 ADR 只锁方向不锁实现，避免设计超过实现阶段（原则 7） | 「独立方法论服务」——新组件新部署面，MVP 三问不过关 |
| D4 | **借调重叠检测：三问法扩展为四问**——评估 prompt 增加 `overlap_with` 能力差量裁决问（明确指出与哪个现有角色重叠、差量是什么，差量不足即拒绝）+ `match_role` 规范角色归一化后参与查重 | 复用现有评估调用零新依赖；归一化把「架构师族」「法务合规域」收敛到规范角色，字符串查重立即生效 | 「embedding 语义相似度查重」——引入向量依赖与阈值调参成本，违反原则 7；「维持现状」——v1 重叠问题无解 |
| D5 | **报告 block 扩展：新增 chart（ECharts）+ diagram（mermaid）两类 block**，方向定案，**实施推迟至 P1 另开 ADR**（与 D3 同批） | 前端已有 echarts 依赖、Layout Spec 已有 16 类 block 的扩展机制 | 「截图贴图」——不可交互、不可复现 |
| D6 | **LLM schema 单一真相源**：`conclave_core` 领域模型为唯一定义处，`app/agents/schemas.py` 降级为薄封装引用，StubLLM 输出工厂化（从领域模型构造而非内联） | 与 ADR-019「模型是唯一 schema 真相」同构收敛；消除三份真相源各自演化 | 「以 agents/schemas 为源」——领域模型已被锚点链/结论链广泛引用，反向迁移成本更高 |
| D7 | **代码生成工具选型：Orval 8，锁版本 >= 8.32**，纳入依赖更新纪律 | 五候选中唯一 MIT + 一站式（类型/zod/Query hooks/fetch 客户端/MSW mock）+ 维护最活跃（2026-09 一周三连发、GHSA 快速修复）；早期 8.x 带过 GHSA 漏洞，故必须锁 8.32+ 并持续跟进 | 「hey-api」——0.99 未发 1.0、631 open issues，观望；「openapi-zod-client」——官方停止维护；「openapi-typescript 组合」——无 zod+hooks 一体化，作为 Node 版本不达标时的降级备选保留 |
| D8 | **前端基础镜像升级 node:20 → node:22 LTS**（Dockerfile / Dockerfile.dev / CI actions 同步） | Orval 8 硬性要求 `node >= 22.18.0`；顺带解决搁置项「actions Node.js 20 弃用升级」 | 「降级 Orval 7 迁就 node 20」——旧 major，错过 zod/新 target 支持与全部安全修复 |
| D9 | **保留现有 `lib/api.ts` 封装作为 Orval custom instance**，生成客户端叠加其上 | CSRF、401 刷新排队、demo 切换、中文错误映射都在 api.ts 内，重写风险大且无收益 | 「生成客户端完全替换 api.ts」——安全与降级逻辑需全部重实现，违反最小改动 |
| D10 | **契约 diff 门禁分级上线**：先 warning 模式观察一个迭代周期 → 转 blocking | 当前存量漂移 82%，直接 blocking 会让所有 PR 红、开发停摆 | 「直接 blocking」——存量未清即阻断，不可执行；「永久 warning」——无约束力，漂移复发 |
| D11 | **引入 shadcn/ui CLI（复制代码入仓模式）**，仅用于新增组件，存量组件不强制迁移 | 与现有工具链（Radix+CVA+clsx+tailwind-merge）完全同源，零样式锁定、代码入仓可完全控制，官方定位即「不是组件库」；加速组件产出且贴合 `ui_design_system.yaml` | 「整套组件库（AntD/MUI/Mantine/Semi/Arco）」——均 MIT 但各带视觉骨架，深度去风格化成本不低于自持，与自有设计语言冲突；「完全不引入」——组件继续全手写，产出速度慢 |

---

## 分阶段实施

| Phase | 内容 | 验收标准 |
|---|---|---|
| **Phase 0（前提）** | 前端基础镜像与 CI 升级 node:22 LTS（SWR 源）；`package-lock.json` 在 node 22 下重建 | 容器内 `npm run build` + `tsc -b --noEmit` + eslint 全绿；`node -v` >= 22.18 |
| **Phase 1（MVP：后端契约）** | ① `response_model` 补齐：先 `meetings.py` 40 端点，再全量（websocket/纯文本端点豁免并登记）；② `openapi.json` 作为 CI 产物提交；③ diff 门禁 warning 模式 | 覆盖率 100%（豁免清单外）；openapi.json 变更可被 CI 检测；容器内 ruff+mypy+pytest 全绿 |
| **Phase 2（前端全链路）** | ① Orval 配置（custom instance → `api.ts`），生成至 `src/api/generated/`；② 关键端点接 zod 运行时校验；③ 引入 shadcn CLI（仅新组件）；④ 手写 `src/types/` 收敛 | tsc/eslint/build 全绿；手写类型缩减 ≥ 80%；zod 校验含非正向测试（畸形响应必须报错） |
| **Phase 3（LLM schema 统一 + 门禁硬化）** | ① D6 单一真相源收敛 + StubLLM 工厂化；② diff 门禁 warning → blocking；③ pre-commit 生成 openapi.json 检查 | 容器内三检查全绿；ADR-015 prompt 回归套件全绿；后端改契约不带生成物时 CI 红 |
| **Phase 4（借调重叠检测，可与 Phase 3 并行）** | ① 评估 prompt 四问化（`overlap_with` 字段，Pydantic 校验）；② `match_role` 归一化映射参与 `is_already_borrowed`；③ 修正 `profile.py` docstring 偏差 | 往返测试 + 重叠场景测试（「架构师」在会后借调「微服务架构师」被拒）；prompt 回归全绿 |
| **推迟项** | D3 方法论库、D5 chart/diagram block → **P1 另开 ADR**（ADR-021 候选） | 本 ADR 只锁方向 |

---

## 风险评估

| 风险 | 影响 | 概率 | 缓解（护栏） |
|---|---|---|---|
| openapi.json 与代码漂移（改了后端忘重新生成） | 高——前端拿到过期契约 | 中 | D10 diff 门禁（warning→blocking）+ Phase 3 pre-commit 检查双护栏 |
| 生成代码 git 噪音大、review 负担重 | 中——提交卫生恶化 | 高 | 生成物隔离至 `src/api/generated/`，`.gitattributes` 标 `linguist-generated`，CI 对该目录免 lint |
| node:22 升级破坏现有构建 | 高——前端无法构建 | 低 | Phase 0 独立成段、先跑全量构建与测试再进入 Phase 1；回滚即还原镜像 tag |
| 借调评估 prompt 新增问题改变 LLM 输出结构 | 中——评估解析失败 | 中 | `overlap_with` 进 Pydantic 模型校验 + ADR-015 prompt 回归套件 + 往返测试；temperature 0 不变（原则 9） |
| Orval 早期版本 GHSA 复发 | 中——供应链安全 | 低 | D7 锁 >= 8.32 + 依赖更新纪律（纳入周期性升级） |
| zod 运行时校验误拒合法响应（后端新增字段） | 中——前端功能中断 | 中 | 生成 schema 用宽松模式（未知字段放行），仅关键端点先接入，灰度扩面 |

正确性判定：本 ADR 不涉及共享并发写或增量重建——契约链是构建期产物（可整体重新生成、等价于 ADR-019 语境下「可重建的缓存」），借调检测运行在单会议状态机内（ADR-013 契约不变），故无需时序推演；核心不变式「生成物 == openapi.json 派生」由 diff 门禁持续兜底。

---

## 工程红线

- [x] 不新增业务表——借调检测复用 `borrow_history`，归一化映射为纯代码；多租户 checklist（P8）不触发，特此声明
- [x] 新依赖（orval、shadcn CLI 均为 devDependencies）走 npmmirror 国内源；生成物不进 lock 之外的依赖面
- [x] `src/api/generated/` 禁止手改：eslint ignore + CI 检查该目录无手工 diff
- [x] `api.ts` 的 CSRF / 401 排队 / demo 切换 / 错误映射逻辑不得被生成客户端削弱（D9）
- [x] 与既有 ADR 一致性：承接 ADR-019 单一真相思想（DB schema → API 契约层同构扩展，非决策联动）；D4 扩展设计原则 2 借调三问法为四问；prompt 变更受 ADR-015 回归套件约束；不触碰 ADR-002 JSONB 扩展约定与 ADR-013 状态机契约

---

## 测试策略

- 每个 Phase 完成后在 Docker 容器内一次性跑 `ruff check` + `mypy` + `pytest`（避免反复起容器，Hard Constraint）
- Phase 1：`app.openapi()` 输出快照测试——端点增减必须伴随 openapi.json 变更
- Phase 2：前端 `tsc -b --noEmit` + eslint + build；zod 校验单元测试每文件至少 1 个非正向用例（testing-rules §9）
- Phase 4：借调评估往返测试（testing-rules §3）+ 重叠拒绝非正向测试；`profile.py` 行为与文档一致性用例
- 回归：ADR-015 prompt 回归套件、`test_password_hash.py`（若触碰认证相邻代码）

---

## 定稿前验证清单

- [x] 每条事实性声明已 grep/一手源核验（P21）：171/30 端点计数、zod 零 import、node:20 镜像、Orval engines >= 22.18.0、`is_already_borrowed` 前缀匹配、`AUTO_BORROW_THRESHOLD=3`、hey-api 0.99 未发 1.0
- [x] 全部可推翻点已获用户裁决并记录在状态节（报告 D1-D6 + shadcn 增强，2026-09-13）
- [x] 跨 ADR 引用一致（ADR-019 / ADR-015 / ADR-013 / ADR-002 均为单向承接引用，无决策联动需求）
- [x] 决策表编号连续 D1-D11，新增为追加
- [x] Phase 拆分含测试策略，推迟项（D3/D5）显式标注另开 ADR
- [x] 状态生命周期：Proposed → Accepted（附裁决记录）
