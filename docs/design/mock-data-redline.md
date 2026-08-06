# Mock 数据红线规范（定稿）

> 状态：Accepted · 日期：2026-08-06
> 适用范围：Conclave 全部代码（前端/后端/脚本/配置），以及任何在本仓库工作的 AI 编码助手（Cursor / Trae / Copilot / Claude Code / WorkBuddy 等）与人类开发者。
> 引用方式：本文档条款编号为 `MR-n`，可在代码审查、commit message、issue 中直接引用（如"违反 MR-2"）。
> 相关纪律：AGENTS.md §5.2（Anti-Vibe-Coding）、docs/pitfalls.md P21/P22。

---

## 1. 为什么是红线

Conclave 的核心价值主张是**证据诚实性**（design-principles.md 原则 10：宁可标注"证据不足"，也不编造伪引用）。Mock 数据混入生产路径是对这一主张的直接腐蚀：

- **UI 对用户编造能力**：`frontend/src/lib/mock-data.ts:1574` 宣称支持 `.pdf/.docx` 上传，后端实际 415 拒绝——产品在对用户撒谎。
- **掩盖断链**：生产路径被 mock 兜底后，真实 API 断掉不会暴露（无报错、无空态），问题被隐藏而非被修复。
- **审计失效**：审查者看到"功能存在"，实际跑的是假数据，外部审计因此产生误判（CONCLAVE-CROSS-VERIFY-REPORT-2026-08-04 已实证：10 条声明 6 条有偏差）。
- **信任不可逆**：用户发现一次假数据后，对所有真实数据也会怀疑。

一个以"不编造"为卖点的系统，自身不能有任何编造。**这不是代码风格问题，是产品诚信问题，按 P1 级事故处置。**

---

## 2. 定义与判定规则

**Mock 数据**：任何在非测试环境下运行的、用于冒充真实后端响应/真实业务数据的硬编码数据、随机生成数据或静态样例。

**生产路径**：用户正常使用时可达的任何代码路径——包括页面渲染、API 响应、降级/兜底分支、空态内容、错误处理分支。

### 判定三问（任一答"是"即违规）

1. 这段数据是否会被**真实用户**在**非测试环境**看到或消费？
2. 这段数据是否冒充了**本应从后端/文件系统/外部服务获得**的结果？
3. 移除这段数据后，功能是否会**静默地**显示一个看似正常但虚假的状态？

### 典型违规形态（实证案例）

| 形态 | 案例 |
|---|---|
| mock 模块被生产页面 import | `frontend/src/features/graph/page.tsx`、`admin/page.tsx`、`operations/page.tsx` import `lib/mock-data.ts` |
| mock 数据声明虚假能力 | `mock-data.ts:1574` `allowed_extensions: ['.pdf', ...]` |
| `isDemoMode()` 分支散落各处 | 多个页面内嵌 demo 分支，真假数据混在同一渲染路径 |
| 空态里放假数据"撑场面" | 列表为空时展示样例条目且无"这是示例"标识 |

---

## 3. 条款

- **MR-1 生产零 Mock**：生产路径（含降级分支、空态、错误态）禁止出现任何 mock 数据。后端不可达时的正确做法是：加载态 → 错误态（含重试入口）→ 空态（如实说明"无数据"），三态任选，**禁止用假数据填充**。
- **MR-2 单点开关**：如确需演示模式，必须满足：① 全局唯一开关（环境变量，如 `CONCLAVE_DEMO_MODE=1`）；② 所有 mock 数据集中在唯一模块；③ 生产构建/部署中该开关默认关闭且文档明确标注；④ demo 模式下 UI 必须有持久可见的"演示数据"水印标识。当前散落的 `isDemoMode()` 多点分支形态**不符合**本条款，必须收敛。
- **MR-3 能力宣称即实现**：UI 上出现的任何能力宣称（支持的文件格式、按钮文案、特性列表），必须有真实后端实现支撑。实现未完成的入口**要么隐藏，要么禁用并注明**，禁止可点击但 toast"功能开发中"（实证：`message-stream.tsx:117` "分支探索"按钮）。
- **MR-4 测试隔离**：mock/fixture 只允许存在于 `tests/`、`__tests__/`、`*.test.*`、`*.spec.*`、stub 实现（`StubLLM/StubEmbedding`，经 `CONCLAVE_*_MODE=stub` 环境变量显式启用）中。测试文件禁止被生产代码 import。
- **MR-5 禁假上传**：禁止用 `file.text()` 读文件后 POST JSON 冒充 multipart 上传（实证：`features/workspace/page.tsx:271-293`）。文件上传必须 `FormData` + multipart，并有类型/大小校验与进度反馈。
- **MR-6 新增代码门禁**：任何新增页面/组件/接口，审查时必须回答"这里展示的数据来自哪个真实接口？"，答不上来不予合入。
- **MR-7 违反处置**：发现生产 mock 按 P1 bug 处理：立即修复 + 按 `docs/RETROSPECTIVE_CONVENTIONS.md` 出修复报告，commit footer 引用本条款编号。
- **MR-8 存量清偿**：`frontend/src/lib/mock-data.ts`（1612 行）是当前最大存量违规，必须在下一迭代整体移除或迁移为符合 MR-2 的单点 demo 模块，不得继续扩散引用。

---

## 4. 提交前自查（任何 AI 助手/开发者都必须执行）

```bash
# 前端：生产源码中是否引用 mock
grep -rn "mock" frontend/src --include="*.ts" --include="*.tsx" \
  | grep -v "__tests__" | grep -v ".test." | grep -v ".spec."

# 前端：demo 分支是否多点散落
grep -rn "isDemoMode\|demoMode\|DEMO" frontend/src --include="*.ts" --include="*.tsx"

# 前端：假上传模式
grep -rn "file.text()" frontend/src

# 通用：假入口
grep -rn "功能开发中\|即将上线\|coming soon" frontend/src
```

**判定**：以上命令在生产源码（非测试文件）中的任何命中，都必须逐条确认是否符合 MR-2/MR-4 的豁免形态，否则阻断提交。

## 5. CI/Hook 强制（待实施，见整改清单）

1. ESLint `no-restricted-imports`：禁止 `src/features/**`、`src/components/**` 从 `**/mock-data` 导入。
2. pre-commit hook 增加第 4 节 grep 检查（秒级，符合 hook 设计约束）。
3. 后端 stub 实现（StubLLM/StubEmbedding）启动时若非测试/显式 stub 模式，日志打 WARN 横幅（StubEmbedding 已有告警，store.py:782-789，推广到全部 Stub）。

---

## 6. 对 AI 编码助手的特别约束

大模型生成代码时有三个系统性倾向会触发本红线，必须主动对抗：

1. **"先把 UI 撑起来"倾向**：生成页面时顺手写假数据占位。**禁止**。正确做法是先接真实接口，接口不存在就渲染加载/错误/空三态。
2. **"让报错消失"倾向**：接口失败时写兜底假数据让页面"看起来正常"。**禁止**。失败必须可见。
3. **"照着已有代码抄"倾向**：仓库里已有 mock 用法时会当成项目惯例模仿。**注意**：存量 mock 是待清偿债务（MR-8），不是范例。

> 本规范与 AGENTS.md、PROJECT_CONVENTIONS.md 同效力。任何 AI 助手在本仓库工作时，开始编码前应阅读本文档。
