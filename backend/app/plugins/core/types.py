"""插件系统基础类型定义。

包含 PluginTier、PluginState、PluginHealth、PluginBase Protocol、
钩子返回值类型（Override/Next/Fallback）以及 PluginContext。
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from app.plugins.core.event_bus import PluginEventBus


class PluginTier(str, enum.Enum):
    """插件三层分级（ADR-003）。

    CORE:       系统必须依赖，加载失败阻止启动
    CROSSCUTTING: 横切关注点，失败降级但服务可用
    OPTIONAL:   可选功能，失败跳过，API 返回 503
    """

    CORE = "core"
    CROSSCUTTING = "crosscutting"
    OPTIONAL = "optional"


class PluginState(str, enum.Enum):
    """插件生命周期状态。"""

    DISCOVERED = "discovered"      # 已注册但未启动
    LOADED = "loaded"              # 拓扑排序完成
    INITIALIZING = "initializing"  # on_startup 中
    READY = "ready"                # 启动成功，可服务
    DEGRADED = "degraded"          # 启动成功但健康检查失败（CROSSCUTTING）
    SHUTTING_DOWN = "shutting_down"
    FAILED = "failed"              # 启动失败（CORE 抛异常，或硬依赖缺失）
    STOPPED = "stopped"            # 正常关闭
    DISABLED = "disabled"          # 被热开关禁用，或 OPTIONAL 启动失败


@dataclass
class PluginHealth:
    """插件健康检查结果。"""

    healthy: bool
    message: str = ""
    last_check: datetime | None = None
    details: dict[str, Any] = field(default_factory=dict)


# ---- Hook 返回值类型 ----


@dataclass
class Override:
    """拦截型钩子返回：使用此值，终止调用链。"""

    value: Any


@dataclass
class Next:
    """拦截型钩子返回：弃权，交给下一个插件。"""


@dataclass
class Fallback(Exception):
    """拦截型钩子返回/抛出：阻断操作，抛出 HTTPException。

    可作为返回值 ``return Fallback(...)`` 或直接 ``raise Fallback(...)``，
    两种写法在 PluginRegistry.fire_interceptor 中效果相同。
    """

    reason: str
    code: str = "PLUGIN_REJECTED"
    status_code: int = 403
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        Exception.__init__(self, self.reason)


@dataclass
class LLMOverride:
    """on_llm_pre_call 返回：替换 LLM 调用参数。"""

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    extra_headers: dict[str, str] | None = None


@dataclass
class LLMFallback:
    """on_llm_error 返回：切换 Key 重试。"""

    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    reason: str = ""


@dataclass
class PluginContext:
    """传递给插件钩子的上下文对象。"""

    app: Any                                        # FastAPI 实例
    registry: Any                                   # PluginRegistry 实例
    event_bus: PluginEventBus | None = None       # 插件间事件总线
    request_id: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# ---- PluginBase Protocol ----


@runtime_checkable
class PluginBase(Protocol):
    """所有插件必须实现的最小接口。

    插件通过 Mixin 组合声明自己支持的钩子：
        class MyPlugin(PluginBase, LifecycleMixin, RouterMixin, LLMPreCallMixin):
            name = "my_plugin"
            version = "1.0.0"
            tier = PluginTier.OPTIONAL
            dependencies = ["auth?"]   # 软依赖 auth
            priority = 100
    """

    name: str                # 全局唯一，如 "auth", "team", "billing"
    version: str             # semver，如 "1.0.0"
    tier: PluginTier         # CORE / CROSSCUTTING / OPTIONAL
    dependencies: list[str]  # 所依赖的其他插件 name 列表；后缀 "?" 表示软依赖
    priority: int            # 同 tier 内排序，默认 100，数值越小越先执行
