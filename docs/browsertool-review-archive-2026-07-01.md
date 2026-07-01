# BrowserTool 架构交叉评审归档

**归档日期**: 2026-07-01
**评审模型**: DeepSeek 4 Pro（原始评审）+ GPT（两轮交叉评审）
**评审对象**: `backend/app/tools/browser_tool.py` + `backend/app/tools/playwright_search.py`
**最终文档**: [browsertool-architecture-review.html](../docs/browsertool-architecture-review/browsertool-architecture-review.html)

---

## 评审时间线

| 时间 | 事件 |
|------|------|
| 2026-07-01 | DeepSeek 4 Pro 完成原始评审，识别 4 个 P0 + 7 个 P1 + 5 个 P2 缺陷，提出 5 个开放问题 |
| 2026-07-01 | GPT 第一轮交叉评审：确认全部判定无分歧，补充 N1-N4，回答 5 个开放问题 |
| 2026-07-01 | GPT 第二轮交叉评审：补充 N5-N10，提出验收清单 |
| 2026-07-01 | 用户确认脱敏边界：日志脱敏，数据不脱敏 |
| 2026-07-01 | 交叉评审完成，进入实施阶段 |

---

## 原始评审（DeepSeek 4 Pro）

### P0 缺陷（4 项）

| 编号 | 缺陷 | 文件位置 |
|------|------|---------|
| P0-1 | 单 Context 共享导致跨 Agent 状态覆盖 | `browser_tool.py` 全局单例 `get_browser_tool()` |
| P0-2 | 无域名白名单 — SSRF 攻击面 | `goto()` 方法无 URL 过滤 |
| P0-3 | 无操作审计日志 | 37 个方法均未记录操作日志 |
| P0-4 | Semaphore(5) 并发模型错误 | 5 个协程操作同一个 `_page` |

### P1 缺陷（7 项）

P1-1 标签页无上限 / P1-2 无空闲超时回收 / P1-3 expose_function 不可重复注册 / P1-4 _resolve_locator auto 模式脆弱 / P1-5 无导航深度限制 / P1-6 截图 base64 无大小限制 / P1-7 evaluate 无沙箱

### P2 缺陷（5 项）

P2-1 无重试退避 / P2-2 无代理支持 / P2-3 Context cookie 不隔离 / P2-4 无页面加载性能指标 / P2-5 无 storage_state 导出

### 5 个开放问题

Q1 Context 分配粒度 / Q2 风险检测位置 / Q3 gRPC RPC 设计 / Q4 evaluate 沙箱化 / Q5 storage_state 跨节点同步

---

## GPT 第一轮交叉评审

### 评审结论

总体方向正确：Playwright + Locator-first + CDP 注入 + 6 大类方法拆分符合多 Agent 可组合性。

### 确认的缺陷

全部 P0/P1/P2 判定准确，无分歧。

### 新增缺陷

| 编号 | 缺陷 | 级别 |
|------|------|------|
| N1 | 反检测 ≠ 反验证码 — 需区分 403/验证码/超时，分别走降级路径 | P0 |
| N2 | CSP/Trusted Types 阻断 evaluate 注入 — 需 bypass_csp=True | P1 |
| N3 | 渐进式提取策略缺失 — 应"静态抓取→动态渲染→JS 提取"三级降级 | P1 |
| N4 | 观测指标缺失 — 需导航耗时/渲染耗时/失败原因分类 | P2 |

### 开放问题回答

- Q1: 推荐 meeting/session 粒度（非 agent 粒度）
- Q2: 未明确选择，但强调导航深度计数 + 域名频率限制 + evaluate 预算必须存在
- Q3: 未涉及
- Q4: 所有 evaluate/注入要做 try/catch + 超时控制 + 失败回退
- Q5: 直接销毁重建（更简单，代价是可能需要重新登录）

### 关于 JS 注入异常的结论

"反调试/anti-debug 会导致注入 JS 抛异常"是可能的，但不一定来自 page.evaluate 被检测，更常见来源是：
- 页面阻止脚本执行/重写函数（hook、冻结对象）
- CSP / Trusted Types 限制
- 页面处于错误状态或跨域限制

Playwright 的 addInitScript/CDP 注入通常不会触发 DevTools 面板相关检测，但仍可能触发行为型风控（Cloudflare/验证码）。

---

## GPT 第二轮交叉评审

### 评审结论

方向正确，但需补 6 个"容易被忽略但会再次出事"的点。

### 新增缺陷

| 编号 | 缺陷 | 级别 | 核心问题 |
|------|------|------|---------|
| N5 | URL allowlist 不能只做 hostname | P0 | `http://allowed.com@evil.com/`、scheme 绕过、重定向链绕过 |
| N6 | 并发不仅 page 串行，还要导航/等待串行 | P0 | action 结束必须包含统一 wait_for_load_state |
| N7 | 反检测/注入失败要可控降级（硬规则） | P1 | JS 失败后下一步不应仍依赖 JS，固化降级链 |
| N8 | 截断在协议层而非调用方 | P1 | RPC 返回处截断，结构化字段也要有上限 |
| N9 | 审计日志需脱敏 | P1 | 记录元数据 + 内容字段长度限制 + 移除疑似 token |
| N10 | expose_function 需 scope 化 | P1 | context 级注册一次，action 传参通过结构化 message |

### 验收清单（GPT 建议）

- [ ] BrowserPool：meeting_id→独立 BrowserContext
- [ ] 同一 page：所有 action 串行（队列/lock），并有统一 wait_for settle
- [ ] goto：scheme 限制 + 重定向后校验 + 私网最终 URL 拒绝
- [ ] 审计日志：结构化 + 脱敏 + 大小上限
- [ ] evaluate/addInitScript：10s 超时 + 返回截断 + 失败降级链
- [ ] tab/context：数量上限 + idle 回收 + meeting 结束清理
- [ ] handler：参数 Pydantic 校验 + action step budget

---

## 5 个开放问题的最终结论

| 问题 | 结论 | 依据 |
|------|------|------|
| Q1 Context 粒度 | **按 meeting_id** | 两方一致同意；同 meeting 内通过多 Page（max 3）并行 |
| Q2 风险检测位置 | **BrowserPool 内嵌** + YAML 配置驱动 | 实时性要求高，规则简单不值得独立组件 |
| Q3 gRPC RPC 设计 | **粗粒度** `BrowserActionRequest { action, params }` + Worker 侧参数校验 | 37 个细粒度 RPC 维护成本太高 |
| Q4 evaluate 沙箱 | **不做 AST 白名单**，靠启动参数 + 10s 超时 + 1MB 截断 + 降级链 | AST 分析成本高且容易误杀 |
| Q5 跨节点同步 | **容忍不一致，销毁重建** | Agent 会话短生命周期，不引入 Redis 锁 |

---

## 脱敏边界（用户确认）

**原则：日志脱敏，数据不脱敏。**

- 审计日志：`result_summary` 限制 2KB，移除疑似 cookie/token 模式（`Bearer xxx`、`session=xxx`）
- 提取数据：`extract_content()`、`get_text()`、`evaluate()` 等方法返回给 Agent 的数据不做任何脱敏，保持完整

理由：审计日志用于追踪和追责，不需要完整内容。Agent 提取的页面内容是下游分析的原材料，脱敏会破坏数据质量，导致 Agent 基于残缺数据做出错误决策。

---

## 实施路线

| 阶段 | 范围 | 预估工作量 |
|------|------|-----------|
| 阶段一 | P0 全部 6 项（P0-1~4 + N1 + N5 + N6） | 1 天 |
| 阶段二 | P1 全部 7 项 + N2/N3/N7/N8/N9/N10 | 1 天 |
| 阶段三 | P2 + N4 + gRPC 多节点 | 2-3 天 |
