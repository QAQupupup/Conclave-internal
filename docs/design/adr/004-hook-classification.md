# ADR-004: 钩子二分法（拦截型 Interceptor / 观察型 Observer）

| 字段 | 值 |
|------|-----|
| 编号 | ADR-004 |
| 状态 | Accepted |
| 日期 | 2026-07-19 |
| 影响范围 | PluginRegistry.fire_*() 调用语义、插件 Mixin 接口定义、钩子注册 API、插件开发者编码规范 |

## 背景

v0.3 实现的第一版 Hook System 采用了统一的调用语义：**第一个返回非 None 值的插件胜出，终止调用链，返回值作为钩子结果**（first-non-None-wins）。这个语义对于"做决策"类的钩子（例如：从多个来源中选择一个 LLM API Key）是合理的，但在 v0.3 集成测试中暴露出严重问题：

1. **副作用钩子被静默丢弃**：`after_meeting_end` 钩子上同时注册了 billing（记录用量）、audit（写审计日志）、webhook（推送通知）、analytics（更新统计）四个插件。由于它们都返回 None（副作用钩子本就没有有意义的返回值），四个插件都被调用——看似没问题。但如果其中一个插件（例如 analytics）错误地返回了一个非 None 值（如 `True`），调用链会在它那里终止，排在它后面的 webhook 插件永远不会被执行，导致事件通知丢失。

2. **多插件叠加效应无法表达**：billing 想"在配额不足时拦截请求"，ratelimit 也想"在超限时报错"。first-wins 语义下，谁先注册谁生效，后注册的插件完全没有机会表达自己的拦截意图，导致策略叠加失效。

3. **注册顺序变成隐式耦合**：插件作者不得不关心自己的钩子在 Registry 中的注册顺序，甚至出现了插件 A 为了让自己"更优先"而在 `__init_subclass__` 里手动调整 `_hook_order` 的黑魔法。注册顺序本应是无关紧要的实现细节，却变成了影响正确性的关键因素。

4. **无法区分"决策"与"记录"**：核心代码在调用钩子时，无法从类型签名上判断这是一个"需要得到一个答案"的钩子，还是一个"通知大家发生了某事"的钩子，两者的异常处理、返回值处理、超时策略完全不同。

我们需要一种新的钩子分类模型，在类型层面明确区分两种本质不同的钩子语义，避免上述问题。

## 决策

将所有钩子（Hook Point）分为两类，在钩子定义时通过 Mixin 类和注册装饰器显式声明其类型，PluginRegistry 根据类型采用不同的调用策略。

### 类型一：拦截型钩子（Interceptor Hook）

**语义定位**：用于"做决策"或"修改/阻断行为"。多个插件参与同一个决策，最终选择一个结果，或者达成一个共识。

**典型场景**：
- `resolve_llm_api_key`：从用户提供/团队池/企业池多个来源中选择使用哪个 API Key；
- `before_meeting_start`：决定是否允许会议开始（配额检查、合规审查、频控）；
- `select_fallback_model`：主模型失败时选择降级到哪个备用模型；
- `transform_user_prompt`：对用户 prompt 做修改（注入系统提示、PII 脱敏、内容审查）。

**调用语义**：
- **链式调用（Chain of Responsibility）**：按插件优先级顺序调用（CORE > CROSSCUTTING > OPTIONAL，同 tier 内按 `priority` 数值升序）；
- **支持三种返回值**：
  - 返回 `Override(value)`：表示"我做了决策，使用这个值"，终止调用链，`value` 作为钩子结果；
  - 返回 `Fallback(reason)`：表示"我反对/阻断这个操作"，终止调用链，reason 作为错误信息向上抛出（如 HTTP 402/403/429）；
  - 返回 `Next()` 或 `None`：表示"我不做决策，交给下一个插件"；
- **默认值兜底**：如果所有插件都返回 Next/None，使用核心提供的默认值（`default=` 参数）；
- **多插件组合拦截**：对于"检查是否放行"类钩子（返回 bool 或 Fallback），任一插件返回 Fallback 即阻断，但为了让多个插件都能表达"需要拦截"，提供 `Interceptor.all()` 聚合模式——所有插件串行调用，收集所有 Fallback 原因，一次性返回给客户端（例如同时告知用户"配额不足且不在允许时段"）。

### 类型二：观察型钩子（Observer Hook）

**语义定位**：用于"做记录/做通知/触发副作用"。事件已经发生，通知所有关心的插件，不影响主流程决策。

**典型场景**：
- `after_meeting_created`：发送欢迎通知、初始化分析埋点；
- `after_transcript_saved`：billing 记录 token 用量、audit 写日志、webhook 推送、analytics 更新统计；
- `on_plugin_state_change`：其他插件感知某个插件的状态变化；
- `on_error`：错误上报到 Sentry/自研监控平台。

**调用语义**：
- **广播调用（Broadcast）**：**所有**注册了该钩子的插件都被调用，无论其他插件返回什么；
- **返回值全部忽略**：Observer 钩子的返回值无意义，Registry 不做任何处理（但为了调试可以在 TRACE 级别记录）；
- **异常隔离**：单个插件抛出异常时，**不影响其他插件的调用**，也不影响主链路。异常按插件 tier 处理：CORE 插件异常向上抛出（见 ADR-003），CROSSCUTTING 异常记入 outbox 重试，OPTIONAL 异常计入熔断指标；
- **并发可选**：标记为 `concurrent=True` 的 Observer 钩子可通过 asyncio.gather 并发执行（适用于多个互相独立的通知场景），默认串行；
- **不保证顺序敏感**：Observer 插件不应依赖其他 Observer 的执行顺序。

### 声明方式

钩子在核心的 `conclave/core/hooks/` 目录下以 Mixin 类形式定义，使用装饰器标记类型：

```python
# conclave/core/hooks/meeting.py
from conclave.core.hooks import Interceptor, Observer, hook

class MeetingLifecycleHooks:

    @hook.interceptor
    async def before_meeting_start(self, meeting: MeetingState) -> Interceptor.Result[None]:
        """返回 Fallback 可阻止会议开始，Override(None) 或 Next 表示放行"""
        ...

    @hook.observer
    async def after_transcript_saved(self, meeting: MeetingState, segment: TranscriptSegment) -> None:
        """逐字稿片段落盘后的通知钩子，所有观察者都会被调用"""
        ...

    @hook.interceptor(aggregate=True)
    async def check_meeting_allowed(self, meeting: MeetingState) -> list[Fallback]:
        """聚合模式：收集所有拦截原因"""
        ...
```

插件通过继承对应 Mixin 来实现钩子：

```python
from conclave.core.hooks.meeting import MeetingLifecycleHooks
from conclave.core.plugins import BasePlugin, PluginTier, Interceptor, Next

class BillingPlugin(BasePlugin, MeetingLifecycleHooks):
    tier = PluginTier.CROSSCUTTING

    async def before_meeting_start(self, meeting):
        if not await self.has_enough_quota(meeting.created_by):
            return Interceptor.Fallback("配额不足，请升级套餐", code="QUOTA_EXCEEDED")
        return Next()

    async def after_transcript_saved(self, meeting, segment):
        await self.record_token_usage(meeting.id, segment.token_count)
        # 无需返回值
```

### Registry 调用入口

PluginRegistry 提供两套类型明确的 fire 方法：

```python
# Interceptor：返回单个 Override 值或 Fallback 异常
result = await registry.fire_interceptor("before_meeting_start", meeting)

# Observer：无返回值，并行/串行执行所有订阅者
await registry.fire_observer("after_transcript_saved", meeting, segment)
```

两种方法签名不同，核心代码调用时在类型层面就明确知道自己在使用哪种语义，避免混用。

## 选项对比

| 选项 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 选项1：全部 first-non-None-wins（v0.3 现状） | 实现简单，单一调用逻辑 | 副作用钩子被异常返回值截断；多插件叠加策略无法表达；注册顺序变成隐式耦合；无法在类型层区分决策/通知 | 否决，已在 v0.3 集成测试中造成实际 bug（webhook 通知丢失） |
| 选项2：全部 all-called，所有插件都执行，返回值组成列表 | 副作用钩子安全，不会被截断 | 无法表达"做决策"语义——如果两个插件都想选 API Key，最终用谁的？调用方需要自己从列表里挑结果；决策逻辑泄漏到调用点，容易出错；性能开销大——对只需一个答案的钩子也要调所有插件 | 否决，无法满足决策类钩子需求 |
| 选项3：每个钩子自己声明策略（free-form） | 最灵活，钩子作者可以选任意策略 | 缺乏统一约定，每个钩子行为都不同；插件开发者需要逐个阅读钩子文档才能知道返回值语义；Registry 无法做统一的异常处理、超时控制、metrics 埋点 | 否决，灵活性变成混乱，增加认知负担 |
| 选项4：二分法 Interceptor / Observer（选定） | 两种语义覆盖 99% 的实际场景；类型签名明确，调用方和实现方都知道预期行为；副作用钩子安全，不会被截断；决策钩子支持 Override/Fallback/Next 三种明确信号；Registry 可以统一实现异常处理、超时、metrics、并发；与 ADR-003 的 tier 策略天然契合（CORE 插件的 Interceptor 异常可阻断，OPTIONAL 插件的 Observer 异常可熔断） | 需要插件开发者理解两种语义的区别（有轻微学习成本）；极少数"既想决策又想记录"的场景需要拆成两个钩子或在 Interceptor 里通过 EventBus 发事件；需要在钩子定义时就决定类型，后期想改类型会破坏所有实现方 | 选定，语义清晰、类型安全、实现复杂度可控 |

## 后果

### 正面影响

1. **副作用钩子可靠性提升**：Observer 钩子保证所有插件都被调用，彻底消除"analytics 返回了 True 导致 webhook 不执行"这类隐蔽 bug；
2. **决策钩子表达力增强**：Interceptor 的 Override/Fallback/Next 三值模型清晰表达了"我决定"、"我反对"、"我弃权"三种态度，避免用 None/True/False 等模糊返回值；
3. **注册顺序不再重要**：Interceptor 按 tier 和 priority 排序是显式声明的，Observer 根本不依赖顺序，插件作者不再需要钻研注册顺序黑魔法；
4. **异常处理统一**：Registry 可以在 fire_interceptor/fire_observer 两个方法中集中实现异常捕获、tier 判定、熔断计数、metrics 埋点，无需每个钩子单独处理；
5. **可观测性提升**：钩子类型信息可用于自动生成监控面板——Interceptor 记录"决策延迟/决策结果分布"，Observer 记录"各插件执行耗时/失败率"；
6. **静态类型检查友好**：两种钩子的签名可以用 TypeDict/Protocol 精确表达，mypy/pyright 能在编译期检查插件实现是否符合钩子签名。

### 负面影响

1. **迁移成本**：v0.3 中已有的 8 个钩子和 6 个插件需要重写钩子实现，从返回原始值改为返回 Override/Fallback/Next，预计 2 人日工作量；
2. **学习成本**：新插件开发者需要理解两种钩子的区别，可能在早期用错（例如在 Observer 里返回 Override 会被类型检查器报错，但运行期需要友好提示）；
3. **"双钩子"场景**：少数场景下插件既想参与决策又想在决策后记录，需要同时实现 Interceptor 和 Observer 两个钩子（或在 Interceptor 内部发 EventBus 事件），略显啰嗦；
4. **aggregate 模式增加复杂度**：聚合拦截器（多个 Fallback 收集）的返回值类型是 `list[Fallback]` 而非单个 Fallback，调用方需要额外处理列表；
5. **调试复杂度**：Observer 并发执行时异常栈信息会交织在一起，需要 TRACE 日志明确标记是哪个插件的哪次调用出的问题。

### 缓解措施

- 提供完整的迁移脚本 `conclave migrate hooks-v1-to-v2`，自动扫描现有插件代码中的钩子实现并给出修改建议（甚至自动替换常见模式）；
- 在钩子基类中加入运行期检测：如果 Observer 钩子实现返回了非 None 值，在 DEBUG 模式下打印警告"Observer hook should not return a value"；
- 提供详细的钩子作者指南，包含 10+ 个典型场景的示例（"我想选一个值用 Interceptor"、"我想阻止操作返回 Fallback"、"我只想记录一下用 Observer"、"我想等所有检查做完再决定用 aggregate"）；
- fire_observer 在 DEBUG 级别记录每个插件的开始/结束/耗时/异常，在出问题时可以开启 `CONCLAVE_HOOK_TRACE=1` 环境变量获得完整调用轨迹；
- 为两种钩子分别提供单元测试 Mock 工具：`MockInterceptorBus` 可模拟某个钩子返回 Override/Fallback，`MockObserverBus` 可断言某个事件被订阅者收到。

### 初始钩子分类清单（部分）

| 钩子名 | 类型 | 理由 |
|--------|------|------|
| resolve_llm_api_key | Interceptor | 多个来源选一个 Key |
| select_fallback_model | Interceptor | 主模型失败选备用 |
| before_meeting_start | Interceptor | 可阻断会议开始 |
| check_meeting_allowed | Interceptor (aggregate) | 多个合规检查汇总 |
| transform_user_prompt | Interceptor | 修改 prompt 内容 |
| on_api_response | Interceptor | 可修改或缓存响应 |
| after_meeting_created | Observer | 副作用通知 |
| after_meeting_started | Observer | 通知、埋点 |
| after_transcript_saved | Observer | 计费、审计、通知 |
| after_meeting_ended | Observer | 归档、统计、通知 |
| on_error | Observer (concurrent) | 错误上报，可并发 |
| on_plugin_state_change | Observer | 插件间状态感知 |

### 设计边界

- 本决策只规范钩子的**调用语义**，不涉及钩子的注册发现机制（由 PluginRegistry 负责）、不涉及跨进程钩子（未来若拆分微服务，分布式观察者走 EventBus/消息队列，不在此 Hook System 范畴）；
- 钩子之间不支持"嵌套触发"或"在 Observer 里调用 Interceptor 修改当前结果"——Observer 执行时主链路决策已经完成，Observer 不应试图改变已完成的决策（需要改变决策应使用 Interceptor）；
- 钩子超时：Interceptor 默认 5s 超时（因为它阻塞主链路），Observer 默认 30s 但并发模式下整体等待最长 30s，超时值可在钩子定义处覆盖。

## 相关

- ADR-001：插件化架构作为核心扩展机制（本决策是 ADR-001 的 Hook System 具体语义设计）
- ADR-003：插件三层分级（不同 tier 插件在 Observer 异常时的容错策略不同）
- 设计文档：`docs/design/hook-system.md`（钩子类型、返回值协议、priority 规则、并发模型完整规范）
- API 参考：`conclave/core/hooks/__init__.py`（Interceptor / Observer / Override / Fallback / Next 类型定义）
- 迁移指南：`docs/guides/migrate-to-hooks-v2.md`（从 v0.3 旧钩子迁移到二分法钩子的步骤）
