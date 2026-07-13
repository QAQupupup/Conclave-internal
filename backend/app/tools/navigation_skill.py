# NavigationSkill：声明式浏览器导航工作流引擎
#
# 设计原则（Claude 交叉评审共识）：
# - 声明式 YAML 定义工作流，而非命令式代码
# - success_when 条件验证器（8种）判断每步是否成功
# - 四级元素定位回退（CSS → structural → text → LLM）
# - compensating_action 补偿失败步骤（非通用回滚）
# - partial 状态：部分步骤成功时返回已获取的数据
# - provenance 标签：标记数据来源和提取路径
# - fallback-rate 指标：统计定位回退频率
#
# 用法：
#     skill = NavigationSkill.from_yaml(yaml_text)
#     engine = NavigationSkillEngine()
#     result = await engine.execute(skill, meeting_id="meeting-123")
#     # result.status: "success" | "partial" | "failed"
#     # result.data: 提取的数据
#     # result.provenance: 数据来源追踪
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger("app.tools.navigation_skill")

# ================================================================
# C-2: NavigationSkill YAML Schema
# ================================================================

@dataclass
class SuccessWhen:
    """success_when 条件定义"""
    type: str = ""               # 8种条件类型
    selector: str = ""           # CSS/XPath 选择器
    contains: str = ""           # URL/text 包含检查
    attribute: str = ""          # 属性名
    value: str = ""              # 期望值
    timeout_ms: int = 5000       # 等待超时
    min_count: int = 1           # 最小元素数量
    max_count: int = 0           # 最大元素数量（0=不限）
    negative: bool = False       # 取反（条件不满足时才算成功）


@dataclass
class NavStep:
    """导航工作流的一个步骤"""
    name: str = ""
    action: str = ""             # goto / click / fill / scroll / wait / evaluate / extract / select / press
    args: dict[str, Any] = field(default_factory=dict)
    success_when: list[SuccessWhen] = field(default_factory=list)
    compensating_action: dict[str, Any] = field(default_factory=dict)  # 补偿动作
    timeout_ms: int = 30000      # 步骤超时
    retries: int = 0             # 重试次数（非补偿）


@dataclass
class ExtractConfig:
    """数据提取配置"""
    selector: str = "body"
    strategy: str = "auto"       # auto/css/xpath/text/role
    fields: dict[str, str] = field(default_factory=dict)  # {field_name: selector}
    js_expression: str = ""      # 自定义 JS 提取表达式
    max_length: int = 10000


@dataclass
class NavigationSkill:
    """声明式导航工作流定义"""
    name: str = ""
    description: str = ""
    version: str = "1.0"
    steps: list[NavStep] = field(default_factory=list)
    extract: Optional[ExtractConfig] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NavigationSkill":
        """从字典构建 NavigationSkill（通常来自 YAML 解析）"""
        steps = []
        for step_data in data.get("steps", []):
            sw_list = [
                SuccessWhen(
                    type=sw.get("type", ""),
                    selector=sw.get("selector", ""),
                    contains=sw.get("contains", ""),
                    attribute=sw.get("attribute", ""),
                    value=sw.get("value", ""),
                    timeout_ms=sw.get("timeout_ms", 5000),
                    min_count=sw.get("min_count", 1),
                    max_count=sw.get("max_count", 0),
                    negative=sw.get("negative", False),
                )
                for sw in step_data.get("success_when", [])
            ]
            steps.append(NavStep(
                name=step_data.get("name", ""),
                action=step_data.get("action", ""),
                args=step_data.get("args", {}),
                success_when=sw_list,
                compensating_action=step_data.get("compensating_action", {}),
                timeout_ms=step_data.get("timeout_ms", 30000),
                retries=step_data.get("retries", 0),
            ))

        extract_data = data.get("extract")
        extract_cfg = None
        if extract_data:
            extract_cfg = ExtractConfig(
                selector=extract_data.get("selector", "body"),
                strategy=extract_data.get("strategy", "auto"),
                fields=extract_data.get("fields", {}),
                js_expression=extract_data.get("js_expression", ""),
                max_length=extract_data.get("max_length", 10000),
            )

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            version=data.get("version", "1.0"),
            steps=steps,
            extract=extract_cfg,
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_yaml(cls, yaml_text: str) -> "NavigationSkill":
        """从 YAML 文本构建 NavigationSkill"""
        import yaml
        data = yaml.safe_load(yaml_text)
        return cls.from_dict(data)


# ================================================================
# C-3: 8种 success_when 条件验证器
# ================================================================

class ConditionValidator:
    """success_when 条件验证器

    8种条件类型：
    1. element_exists: 元素存在且可见
    2. element_disappears: 元素消失
    3. url_changed: URL 变化（contains 子串检查）
    4. text_changed: 页面文本变化（contains 子串检查）
    5. network_idle: 网络空闲（无 pending 请求）
    6. attribute_changed: 元素属性变化
    7. count_stable: 元素数量稳定（连续检查一致）
    8. negative_condition: 条件取反（上述任何条件的否定）
    """

    def __init__(self, browser_tool: Any) -> None:
        self._browser = browser_tool

    async def validate(self, meeting_id: str, condition: SuccessWhen, page_index: int = 0) -> bool:
        """验证单个条件

        Returns:
            True 如果条件满足
        """
        validator = {
            "element_exists": self._check_element_exists,
            "element_disappears": self._check_element_disappears,
            "url_changed": self._check_url_changed,
            "text_changed": self._check_text_changed,
            "network_idle": self._check_network_idle,
            "attribute_changed": self._check_attribute_changed,
            "count_stable": self._check_count_stable,
            "negative_condition": self._check_negative,
        }.get(condition.type)

        if validator is None:
            logger.warning("未知 success_when 类型: %s", condition.type)
            return True  # 未知类型默认通过

        try:
            result = await validator(meeting_id, condition, page_index)
            # negative 取反
            if condition.negative and condition.type != "negative_condition":
                return not result
            return result
        except Exception as e:
            logger.warning("条件验证失败: type=%s err=%s", condition.type, str(e)[:100])
            return False

    async def _check_element_exists(self, meeting_id: str, cond: SuccessWhen, pi: int) -> bool:
        """1. element_exists: 元素存在且可见"""
        if not cond.selector:
            return True
        try:
            result = await self._browser.wait_for_element(
                meeting_id, cond.selector, strategy="auto",
                state="visible", timeout=cond.timeout_ms, page_index=pi,
            )
            return result.get("status") == "ok"
        except Exception:
            return False

    async def _check_element_disappears(self, meeting_id: str, cond: SuccessWhen, pi: int) -> bool:
        """2. element_disappears: 元素消失"""
        if not cond.selector:
            return True
        try:
            result = await self._browser.wait_for_element(
                meeting_id, cond.selector, strategy="auto",
                state="hidden", timeout=cond.timeout_ms, page_index=pi,
            )
            return result.get("status") == "ok"
        except Exception:
            return False

    async def _check_url_changed(self, meeting_id: str, cond: SuccessWhen, pi: int) -> bool:
        """3. url_changed: URL 变化（contains 子串检查）"""
        current_url = await self._browser.get_url(meeting_id, page_index=pi)
        if cond.contains:
            return cond.contains in current_url
        # 无 contains 时只要 URL 不为空就算通过
        return bool(current_url)

    async def _check_text_changed(self, meeting_id: str, cond: SuccessWhen, pi: int) -> bool:
        """4. text_changed: 页面文本变化（contains 子串检查）"""
        text = await self._browser.get_text(meeting_id, page_index=pi)
        if cond.contains:
            return cond.contains in (text or "")
        return bool(text)

    async def _check_network_idle(self, meeting_id: str, cond: SuccessWhen, pi: int) -> bool:
        """5. network_idle: 网络空闲"""
        try:
            # 通过 evaluate 检查 performance entries 是否有 pending
            result = await self._browser.evaluate(
                meeting_id,
                "() => performance.getEntriesByType('resource').length",
                page_index=pi,
            )
            # 简化检查：等待 500ms 后再看是否有新请求
            await asyncio.sleep(0.5)
            result2 = await self._browser.evaluate(
                meeting_id,
                "() => performance.getEntriesByType('resource').length",
                page_index=pi,
            )
            r1 = result.get("data", 0) if isinstance(result, dict) else 0
            r2 = result2.get("data", 0) if isinstance(result2, dict) else 0
            return r1 == r2  # 请求数稳定 = 网络空闲
        except Exception:
            return True  # 无法检查时默认通过

    async def _check_attribute_changed(self, meeting_id: str, cond: SuccessWhen, pi: int) -> bool:
        """6. attribute_changed: 元素属性变化"""
        if not cond.selector or not cond.attribute:
            return True
        attr_val = await self._browser.get_attribute(
            meeting_id, cond.selector, cond.attribute, page_index=pi,
        )
        if cond.value:
            return attr_val == cond.value
        return attr_val is not None

    async def _check_count_stable(self, meeting_id: str, cond: SuccessWhen, pi: int) -> bool:
        """7. count_stable: 元素数量稳定（连续检查一致）"""
        if not cond.selector:
            return True
        try:
            count1 = await self._browser.find_elements(
                meeting_id, cond.selector, page_index=pi,
            )
            await asyncio.sleep(0.5)
            count2 = await self._browser.find_elements(
                meeting_id, cond.selector, page_index=pi,
            )
            n1, n2 = len(count1), len(count2)
            if n1 != n2:
                return False
            if cond.min_count and n1 < cond.min_count:
                return False
            if cond.max_count and n1 > cond.max_count:
                return False
            return True
        except Exception:
            return False

    async def _check_negative(self, meeting_id: str, cond: SuccessWhen, pi: int) -> bool:
        """8. negative_condition: 嵌套条件取反"""
        # 创建一个非 negative 的副本递归验证
        inner = SuccessWhen(
            type=cond.selector or "element_exists",  # 用 selector 字段存储内部类型
            selector=cond.contains,  # 用 contains 字段存储内部 selector
            contains=cond.value,
            timeout_ms=cond.timeout_ms,
            negative=False,
        )
        result = await self.validate(meeting_id, inner, pi)
        return not result


# ================================================================
# C-4: 四级元素定位回退
# ================================================================

class ElementLocator:
    """四级元素定位回退：CSS → structural → text → LLM

    定位策略优先级：
    1. CSS/XPath 选择器（最快，最精确）
    2. 结构化定位（ARIA role + name）
    3. 文本定位（get_by_text）
    4. LLM 辅助定位（最慢，但最灵活）

    每次回退都记录到 fallback-rate 指标
    """

    def __init__(self, browser_tool: Any) -> None:
        self._browser = browser_tool
        # fallback-rate 指标
        self._fallback_counts: dict[str, int] = {
            "css": 0, "structural": 0, "text": 0, "llm": 0,
        }
        self._total_attempts = 0

    async def locate_and_click(
        self,
        meeting_id: str,
        selector: str,
        page_index: int = 0,
    ) -> dict[str, Any]:
        """定位元素并点击（四级回退）"""
        self._total_attempts += 1

        # Level 1: CSS/XPath
        try:
            result = await self._browser.click(
                meeting_id, selector, strategy="auto", timeout=3000, page_index=page_index,
            )
            if result.get("status") == "ok":
                self._fallback_counts["css"] += 1
                return {**result, "locator_strategy": "css"}
        except Exception:
            pass

        # Level 2: Structural (ARIA role)
        try:
            # 尝试将 selector 解析为 role:name 格式
            if ":" in selector:
                role, name = selector.split(":", 1)
                result = await self._browser.click(
                    meeting_id, name, strategy="role", timeout=3000, page_index=page_index,
                )
                if result.get("status") == "ok":
                    self._fallback_counts["structural"] += 1
                    return {**result, "locator_strategy": "structural"}
        except Exception:
            pass

        # Level 3: Text
        try:
            result = await self._browser.click(
                meeting_id, selector, strategy="text", timeout=3000, page_index=page_index,
            )
            if result.get("status") == "ok":
                self._fallback_counts["text"] += 1
                return {**result, "locator_strategy": "text"}
        except Exception:
            pass

        # Level 4: LLM-assisted (simplified - uses find_by_text as approximation)
        try:
            elements = await self._browser.find_by_text(
                meeting_id, selector, page_index=page_index,
            )
            if elements:
                # 点击第一个匹配的元素
                first = elements[0]
                # 尝试用 tag + text 组合定位
                css_selector = f"{first.get('tag', 'button')}:has-text('{selector}')"
                result = await self._browser.click(
                    meeting_id, css_selector, strategy="css", timeout=3000, page_index=page_index,
                )
                if result.get("status") == "ok":
                    self._fallback_counts["llm"] += 1
                    return {**result, "locator_strategy": "llm"}
        except Exception:
            pass

        return {"status": "error", "error": f"四级定位均失败: {selector}", "locator_strategy": "none"}

    @property
    def fallback_rate(self) -> dict[str, Any]:
        """返回 fallback-rate 指标"""
        total = self._total_attempts or 1
        return {
            "total_attempts": self._total_attempts,
            "by_level": {k: v for k, v in self._fallback_counts.items()},
            "fallback_rate": {
                "css": self._fallback_counts["css"] / total,
                "structural": self._fallback_counts["structural"] / total,
                "text": self._fallback_counts["text"] / total,
                "llm": self._fallback_counts["llm"] / total,
            },
        }


# ================================================================
# C-5: 执行引擎（compensating_action + partial 状态 + provenance）
# ================================================================

@dataclass
class StepResult:
    """单步执行结果"""
    step_name: str = ""
    action: str = ""
    status: str = "pending"       # "success" | "failed" | "skipped" | "compensated"
    data: Any = None
    error: str = ""
    latency_ms: int = 0
    conditions_met: bool = False
    compensating_applied: bool = False
    locator_strategy: str = ""    # 元素定位策略（用于 fallback-rate）


@dataclass
class SkillExecutionResult:
    """NavigationSkill 执行结果"""
    skill_name: str = ""
    status: str = "failed"        # "success" | "partial" | "failed"
    data: Any = None
    steps: list[StepResult] = field(default_factory=list)
    provenance: dict[str, Any] = field(default_factory=dict)
    fallback_rate: dict[str, Any] = field(default_factory=dict)
    total_latency_ms: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return {
            "skill_name": self.skill_name,
            "status": self.status,
            "data": self.data,
            "steps": [
                {
                    "step_name": sr.step_name, "action": sr.action, "status": sr.status,
                    "error": sr.error, "latency_ms": sr.latency_ms,
                    "conditions_met": sr.conditions_met, "compensating_applied": sr.compensating_applied,
                    "locator_strategy": sr.locator_strategy,
                }
                for sr in self.steps
            ],
            "provenance": self.provenance,
            "fallback_rate": self.fallback_rate,
            "total_latency_ms": self.total_latency_ms,
            "error": self.error,
        }


class NavigationSkillEngine:
    """NavigationSkill 执行引擎

    使用方式：
        engine = NavigationSkillEngine()
        result = await engine.execute(skill, meeting_id="meeting-123")
        if result.status == "success":
            print(result.data)
    """

    def __init__(self, browser_tool: Any | None = None) -> None:
        if browser_tool is None:
            from app.tools.browser_tool import get_browser_tool
            browser_tool = get_browser_tool()
        self._browser = browser_tool
        self._validator = ConditionValidator(browser_tool)
        self._locator = ElementLocator(browser_tool)

    async def execute(
        self,
        skill: NavigationSkill,
        meeting_id: str,
        page_index: int = 0,
    ) -> SkillExecutionResult:
        """执行 NavigationSkill

        Args:
            skill: NavigationSkill 定义
            meeting_id: 会议 ID（用于 BrowserPool 隔离）
            page_index: 页面索引
        Returns:
            SkillExecutionResult
        """
        result = SkillExecutionResult(skill_name=skill.name)
        t0 = time.monotonic()

        # 获取排他锁（C-1）
        from app.tools.browser_tool import get_browser_pool
        pool = get_browser_pool()
        exclusive_lock = pool.get_exclusive_lock(meeting_id)

        async with exclusive_lock:
            # 逐步执行
            for i, step in enumerate(skill.steps):
                step_result = StepResult(step_name=step.name, action=step.action)
                step_t0 = time.monotonic()

                try:
                    # 执行步骤（带超时）
                    step_result.data = await asyncio.wait_for(
                        self._execute_step(step, meeting_id, page_index),
                        timeout=step.timeout_ms / 1000,
                    )
                    step_result.status = "success"

                    # 验证 success_when 条件
                    if step.success_when:
                        conditions_ok = await self._validate_conditions(
                            step.success_when, meeting_id, page_index,
                        )
                        step_result.conditions_met = conditions_ok
                        if not conditions_ok:
                            step_result.status = "failed"
                            step_result.error = "success_when 条件未满足"

                except asyncio.TimeoutError:
                    step_result.status = "failed"
                    step_result.error = f"步骤超时 ({step.timeout_ms}ms)"
                except Exception as e:
                    step_result.status = "failed"
                    step_result.error = f"{type(e).__name__}: {e}"

                step_result.latency_ms = int((time.monotonic() - step_t0) * 1000)

                # 失败时尝试补偿
                if step_result.status == "failed":
                    if step.compensating_action:
                        compensated = await self._execute_compensating(
                            step.compensating_action, meeting_id, page_index,
                        )
                        step_result.compensating_applied = compensated
                        if compensated:
                            step_result.status = "compensated"
                        else:
                            # 补偿也失败，标记 partial 并跳过后续步骤
                            result.steps.append(step_result)
                            result.status = "partial"
                            result.error = f"步骤 {step.name} 失败且补偿无效"
                            # 尝试提取已获取的数据
                            result.data = await self._try_extract(skill, meeting_id, page_index)
                            result.total_latency_ms = int((time.monotonic() - t0) * 1000)
                            result.fallback_rate = self._locator.fallback_rate
                            result.provenance = self._build_provenance(skill, result.steps)
                            return result
                    else:
                        # 无补偿，标记 partial
                        result.steps.append(step_result)
                        result.status = "partial"
                        result.error = f"步骤 {step.name} 失败（无补偿动作）"
                        result.data = await self._try_extract(skill, meeting_id, page_index)
                        result.total_latency_ms = int((time.monotonic() - t0) * 1000)
                        result.fallback_rate = self._locator.fallback_rate
                        result.provenance = self._build_provenance(skill, result.steps)
                        return result

                result.steps.append(step_result)

            # 所有步骤成功，执行提取
            if skill.extract:
                result.data = await self._execute_extract(skill.extract, meeting_id, page_index)
                result.status = "success"
            else:
                # 无提取配置，最后一步的数据作为结果
                result.data = result.steps[-1].data if result.steps else None
                result.status = "success"

        result.total_latency_ms = int((time.monotonic() - t0) * 1000)
        result.fallback_rate = self._locator.fallback_rate
        result.provenance = self._build_provenance(skill, result.steps)
        return result

    async def _execute_step(self, step: NavStep, meeting_id: str, pi: int) -> Any:
        """执行单个步骤"""
        action = step.action
        args = step.args

        if action == "goto":
            return await self._browser.goto(meeting_id, args.get("url", ""),
                                            wait_until=args.get("wait_until", "domcontentloaded"),
                                            timeout=args.get("timeout", 30000), page_index=pi)
        elif action == "click":
            # 使用四级定位
            return await self._locator.locate_and_click(
                meeting_id, args.get("selector", ""), page_index=pi,
            )
        elif action == "fill":
            return await self._browser.fill(
                meeting_id, args.get("selector", ""), args.get("value", ""),
                strategy=args.get("strategy", "auto"), page_index=pi,
            )
        elif action == "scroll":
            return await self._browser.scroll(
                meeting_id, direction=args.get("direction", "down"),
                amount=args.get("amount", 500),
                selector=args.get("selector"), page_index=pi,
            )
        elif action == "wait":
            return await self._browser.wait_for_element(
                meeting_id, args.get("selector", ""),
                state=args.get("state", "visible"),
                timeout=args.get("timeout", 10000), page_index=pi,
            )
        elif action == "evaluate":
            return await self._browser.evaluate(
                meeting_id, args.get("expression", ""), page_index=pi,
            )
        elif action == "select":
            return await self._browser.select(
                meeting_id, args.get("selector", ""),
                value=args.get("value"), label=args.get("label"), page_index=pi,
            )
        elif action == "press":
            return await self._browser.press(
                meeting_id, args.get("key", "Enter"),
                selector=args.get("selector"), page_index=pi,
            )
        elif action == "extract":
            return await self._browser.extract_content(
                meeting_id, max_length=args.get("max_length", 5000), page_index=pi,
            )
        elif action == "back":
            return await self._browser.back(meeting_id, page_index=pi)
        elif action == "forward":
            return await self._browser.forward(meeting_id, page_index=pi)
        else:
            return {"status": "error", "error": f"未知 action: {action}"}

    async def _validate_conditions(
        self, conditions: list[SuccessWhen], meeting_id: str, pi: int,
    ) -> bool:
        """验证所有 success_when 条件（AND 逻辑）"""
        for cond in conditions:
            ok = await self._validator.validate(meeting_id, cond, pi)
            if not ok:
                return False
        return True

    async def _execute_compensating(
        self, comp: dict[str, Any], meeting_id: str, pi: int,
    ) -> bool:
        """执行补偿动作

        补偿动作是步骤级的，不是通用回滚。
        典型补偿：关闭弹窗、返回上一页、重试等。
        """
        action = comp.get("action", "")
        args = comp.get("args", {})
        try:
            if action == "click":
                await self._browser.click(meeting_id, args.get("selector", ""), page_index=pi)
            elif action == "press":
                await self._browser.press(meeting_id, args.get("key", "Escape"), page_index=pi)
            elif action == "back":
                await self._browser.back(meeting_id, page_index=pi)
            elif action == "goto":
                await self._browser.goto(meeting_id, args.get("url", ""), page_index=pi)
            elif action == "wait":
                await self._browser.wait_for_element(
                    meeting_id, args.get("selector", ""), page_index=pi,
                )
            else:
                logger.warning("未知补偿 action: %s", action)
                return False
            return True
        except Exception as e:
            logger.warning("补偿动作失败: %s", str(e)[:100])
            return False

    async def _try_extract(
        self, skill: NavigationSkill, meeting_id: str, pi: int,
    ) -> Any:
        """尝试提取数据（即使部分步骤失败）"""
        if skill.extract:
            try:
                return await self._execute_extract(skill.extract, meeting_id, pi)
            except Exception:
                return None
        return None

    async def _execute_extract(self, config: ExtractConfig, meeting_id: str, pi: int) -> Any:
        """执行数据提取"""
        if config.js_expression:
            result = await self._browser.evaluate(
                meeting_id, config.js_expression, page_index=pi,
            )
            return result.get("data") if isinstance(result, dict) else result

        if config.fields:
            # 结构化提取
            return await self._browser.extract_structured(
                meeting_id, config.selector, config.fields,
                strategy=config.strategy, page_index=pi,
            )

        # 简单文本提取
        text = await self._browser.get_text(
            meeting_id, selector=config.selector,
            strategy=config.strategy, page_index=pi,
        )
        if text and len(text) > config.max_length:
            text = text[:config.max_length] + "..."
        return text

    def _build_provenance(
        self, skill: NavigationSkill, step_results: list[StepResult],
    ) -> dict[str, Any]:
        """构建数据来源追踪"""
        return {
            "skill_name": skill.name,
            "skill_version": skill.version,
            "steps_executed": len(step_results),
            "steps_succeeded": sum(1 for s in step_results if s.status == "success"),
            "steps_compensated": sum(1 for s in step_results if s.status == "compensated"),
            "steps_failed": sum(1 for s in step_results if s.status == "failed"),
            "extract_config": {
                "selector": skill.extract.selector if skill.extract else None,
                "strategy": skill.extract.strategy if skill.extract else None,
                "has_js": bool(skill.extract and skill.extract.js_expression),
            } if skill.extract else None,
            "locator_strategies_used": [s.locator_strategy for s in step_results if s.locator_strategy],
        }
