"""PluginRegistry：插件注册、依赖解析、钩子调度、生命周期管理。

核心设计要点：
- 实例化而非类变量单例，在 create_app() 中构造
- Kahn 拓扑排序解析依赖；同层按 (priority, name) 排序保证确定性
- 拦截型钩子：第一个 Override/Fallback 终止链；CORE 异常上抛，CROSSCUTTING/OPTIONAL 异常隔离
- 观察型钩子：所有健康插件都执行，异常隔离；支持并发
- 钩子超时：默认 200ms（asyncio.wait_for），超时视为弃权/跳过
- 热开关：内存版 disable_plugin/enable_plugin（Redis 版 P1b 扩展）
- 健康检查：后台任务每 30 秒并发 health_check，CORE 连续 3 次失败记 CRITICAL
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.plugins.core.event_bus import PluginEventBus
from app.core.exceptions import AppException
from app.plugins.core.exceptions import (
    ConclaveException,
    PluginDependencyError,
)
from app.plugins.core.hooks.lifecycle import (
    LifecycleMixin,
    MiddlewareMixin,
    RouterMixin,
)
from app.plugins.core.types import (
    Fallback,
    Next,
    Override,
    PluginBase,
    PluginContext,
    PluginHealth,
    PluginState,
    PluginTier,
)

logger = logging.getLogger("plugins.registry")

# 模块级全局引用（便于后台任务/非请求路径获取）
_global_registry: PluginRegistry | None = None


def set_global_registry(registry: PluginRegistry) -> None:
    set_global_registry_internal(registry)


def get_registry() -> PluginRegistry | None:
    return _global_registry


# 内部 setter（避免函数名与模块属性同名导致 mypy 抱怨）
def set_global_registry_internal(registry: PluginRegistry) -> None:
    global _global_registry
    _global_registry = registry


# 钩子调度顺序：CORE → CROSSCUTTING → OPTIONAL
_TIER_ORDER = {PluginTier.CORE: 0, PluginTier.CROSSCUTTING: 1, PluginTier.OPTIONAL: 2}


@dataclass
class _PluginEntry:
    """内部维护的插件条目。"""

    plugin: PluginBase
    state: PluginState = PluginState.DISCOVERED
    health: PluginHealth = field(default_factory=lambda: PluginHealth(healthy=True))
    timeout_count: int = 0  # 1 分钟窗口内超时次数
    last_timeout_window: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


class PluginRegistry:
    """插件注册中心。"""

    def __init__(self, hook_timeout_ms: int = 200) -> None:
        self._entries: dict[str, _PluginEntry] = {}
        self._hook_timeout = hook_timeout_ms / 1000.0
        self._order: list[str] = []  # 拓扑排序后的加载顺序
        self._disabled: set[str] = set()  # 热禁用集合（内存版）
        self._health_task: asyncio.Task | None = None
        self._health_interval_sec: float = 30.0
        self._stop_health: asyncio.Event | None = None
        self._stop_health_event: asyncio.Event | None = None
        self.event_bus = PluginEventBus()
        self._ctx: PluginContext | None = None  # resolve_and_load 后赋值
        self._started = False
        self._app: Any = None  # initialize_all 后赋值

    # ---- 注册与查询 ----

    def register(self, plugin: PluginBase) -> None:
        """注册一个插件。重复注册同名插件会抛出异常。"""
        self._validate_plugin(plugin)
        if plugin.name in self._entries:
            raise PluginDependencyError(f"插件名重复: {plugin.name}")
        self._entries[plugin.name] = _PluginEntry(plugin=plugin)
        self._order = []  # 失效，下次 resolve 时重建
        logger.info("插件已注册: name=%s tier=%s v=%s", plugin.name, plugin.tier.value, plugin.version)

    def unregister(self, name: str) -> None:
        if name in self._entries:
            del self._entries[name]
            self._order = []

    def is_registered(self, name: str) -> bool:
        return name in self._entries

    def get_plugin(self, name: str) -> PluginBase | None:
        entry = self._entries.get(name)
        return entry.plugin if entry else None

    def has_plugins(self) -> bool:
        return len(self._entries) > 0

    def ready_plugins(self) -> list[str]:
        return [
            name
            for name, e in self._entries.items()
            if e.state == PluginState.READY
        ]

    def loaded_count(self) -> int:
        """返回当前已注册插件总数。"""
        return len(self._entries)

    def sync_discover(self, dirs: list[Any]) -> int:
        """同步扫描插件目录并注册内置插件（不触发 on_startup）。

        用于 create_app() 阶段，此时需要同步注册中间件/路由。
        异步 on_startup（DB 连接等）在 startup() 中执行。
        Phase 0: 仅遍历目录，无实际插件，返回 0。
        """
        count = 0
        for d in dirs:
            p = Path(str(d))
            if not p.exists() or not p.is_dir():
                continue
            for sub in p.iterdir():
                if not sub.is_dir() or sub.name.startswith("_"):
                    continue
                # Phase 1a 起：import 插件模块并注册 PluginBase 实例
                # Phase 0 仅记录日志
                logger.debug("发现插件目录（未加载）: %s", sub.name)
        logger.info("插件扫描完成，共注册 %d 个插件", count)
        return count

    def bootstrap(self, app: Any) -> None:
        """同步注册中间件、路由、异常处理器（在 create_app() 中调用）。"""
        self._app = app
        # 先做拓扑排序确定插件顺序
        self._order = self._topo_sort()
        logger.info("插件 bootstrap 顺序: %s", " → ".join(self._order))
        self.register_exception_handlers(app)
        self.register_all_middlewares(app)
        self.register_all_routers(app)

    # ---- 便捷加载入口 ----

    async def discover_plugins(self, dirs: list[Any]) -> int:
        """异步扫描插件目录并注册发现的插件。

        Phase 0: 仅遍历目录检查是否存在 ``plugin.py``，不执行实际 import
        （Phase 1a 再实现动态加载逻辑）。当前 builtin 目录为空，返回 0。
        返回发现并注册的插件数量。
        """
        return self.sync_discover(dirs)

    async def initialize_all(self, app: Any | None = None) -> None:
        """异步初始化：调用所有插件 on_startup（DB 初始化、建表等）。"""
        if app is not None:
            self._app = app
        ctx = PluginContext(
            app=app if app is not None else self._app,
            registry=self,
            event_bus=self.event_bus,
        )
        self._ctx = ctx
        await self.resolve_and_load(ctx)

    # ---- 热开关（内存版，Redis 版 P1b 扩展）----

    def disable_plugin(self, name: str) -> None:
        entry = self._entries.get(name)
        if entry is None:
            raise KeyError(f"插件不存在: {name}")
        if entry.plugin.tier == PluginTier.CORE:
            logger.error("CORE 插件不可被热禁用: %s", name)
            return
        self._disabled.add(name)
        entry.state = PluginState.DISABLED
        logger.warning("插件已禁用: %s", name)

    def enable_plugin(self, name: str) -> None:
        self._disabled.discard(name)
        entry = self._entries.get(name)
        if entry is not None and entry.state == PluginState.DISABLED:
            entry.state = PluginState.READY  # 乐观恢复，下次健康检查验证
        logger.info("插件已启用: %s", name)

    def is_disabled(self, name: str) -> bool:
        return name in self._disabled

    # ---- 依赖解析（Kahn 拓扑排序）----

    def _validate_plugin(self, plugin: PluginBase) -> None:
        if not getattr(plugin, "name", None):
            raise PluginDependencyError("插件缺少 name 属性")
        if not hasattr(plugin, "tier") or not isinstance(plugin.tier, PluginTier):
            raise PluginDependencyError(f"插件 {plugin.name} 缺少有效的 tier 属性")
        if not getattr(plugin, "version", None):
            raise PluginDependencyError(f"插件 {plugin.name} 缺少 version 属性")
        if not hasattr(plugin, "dependencies"):
            plugin.dependencies = []  # type: ignore[attr-defined]
        if not hasattr(plugin, "priority"):
            plugin.priority = 100  # type: ignore[attr-defined]

    def _topo_sort(self) -> list[str]:
        """Kahn 算法拓扑排序，同层按 (priority, name) 排序。

        软依赖（"name?" 后缀）缺失仅记 WARNING，不阻断。
        """
        # 收集硬依赖邻接表
        in_degree: dict[str, int] = {n: 0 for n in self._entries}
        graph: dict[str, list[str]] = defaultdict(list)  # dep → [dependents]
        missing_hard: list[str] = []

        for name, entry in self._entries.items():
            for dep in entry.plugin.dependencies:
                is_soft = dep.endswith("?")
                dep_name = dep.rstrip("?")
                if dep_name not in self._entries:
                    if is_soft:
                        logger.warning("软依赖缺失（继续）: %s → %s", name, dep_name)
                        continue
                    missing_hard.append(f"{name} → {dep_name}")
                    continue
                graph[dep_name].append(name)
                in_degree[name] += 1

        if missing_hard:
            raise PluginDependencyError(
                f"硬依赖缺失: {', '.join(missing_hard)}"
            )

        # Kahn：初始入度为 0 的节点，按 (tier, priority, name) 排序
        def _sort_key(n: str) -> tuple[int, int, str]:
            p = self._entries[n].plugin
            return (_TIER_ORDER[p.tier], p.priority, n)

        queue: deque[str] = deque(
            sorted([n for n, d in in_degree.items() if d == 0], key=_sort_key)
        )
        order: list[str] = []
        while queue:
            # 每轮取最小 key 的节点保证确定性
            nodes = sorted(queue, key=_sort_key)
            queue.clear()
            next_layer: list[str] = []
            for node in nodes:
                order.append(node)
                for dependent in graph[node]:
                    in_degree[dependent] -= 1
                    if in_degree[dependent] == 0:
                        next_layer.append(dependent)
            queue.extend(next_layer)

        if len(order) != len(self._entries):
            remaining = [n for n in self._entries if n not in order]
            raise PluginDependencyError(f"检测到循环依赖，涉及插件: {remaining}")

        return order

    # ---- 生命周期 ----

    async def resolve_and_load(self, ctx: PluginContext) -> None:
        """拓扑排序 → 按序调用 on_startup → 启动健康检查。"""
        self._ctx = ctx
        self._order = self._topo_sort()
        logger.info("插件加载顺序: %s", " → ".join(self._order))

        for name in self._order:
            entry = self._entries[name]
            plugin = entry.plugin
            entry.state = PluginState.INITIALIZING
            if not isinstance(plugin, LifecycleMixin):
                entry.state = PluginState.READY
                continue
            try:
                await asyncio.wait_for(
                    plugin.on_startup(ctx),
                    timeout=30.0,  # startup 超时 30s，远长于钩子超时
                )
                entry.state = PluginState.READY
                entry.health = PluginHealth(healthy=True, message="startup ok")
                logger.info("插件启动成功: %s", name)
            except Exception as e:
                if plugin.tier == PluginTier.CORE:
                    entry.state = PluginState.FAILED
                    logger.critical(
                        "CORE 插件启动失败，进程将退出: name=%s error=%s: %s",
                        name, type(e).__name__, e,
                    )
                    raise
                if plugin.tier == PluginTier.CROSSCUTTING:
                    entry.state = PluginState.DEGRADED
                    entry.health = PluginHealth(healthy=False, message=str(e))
                    logger.error(
                        "CROSSCUTTING 插件启动失败，标记为 DEGRADED: name=%s error=%s",
                        name, e,
                    )
                else:
                    entry.state = PluginState.DISABLED
                    entry.health = PluginHealth(healthy=False, message=str(e))
                    logger.warning(
                        "OPTIONAL 插件启动失败，标记为 DISABLED: name=%s error=%s",
                        name, e,
                    )

        # 启动健康检查后台任务
        self._start_health_check(ctx)
        self._started = True

    def register_all_routers(self, app: FastAPI) -> None:
        for name in self._order:
            entry = self._entries[name]
            # bootstrap 阶段：DISCOVERED / BOOTSTRAPPED / READY 都允许注册路由；仅跳过 DISABLED / FAILED
            if entry.state in (PluginState.DISABLED, PluginState.FAILED):
                continue
            plugin = entry.plugin
            if isinstance(plugin, RouterMixin):
                try:
                    plugin.register_routers(app)
                    logger.info("插件路由已注册: %s", name)
                except Exception as e:
                    logger.error("插件 %s 注册路由失败: %s", name, e)

    def register_all_middlewares(self, app: FastAPI) -> None:
        for name in self._order:
            entry = self._entries[name]
            if entry.state in (PluginState.DISABLED, PluginState.FAILED):
                continue
            plugin = entry.plugin
            if isinstance(plugin, MiddlewareMixin):
                try:
                    plugin.register_middlewares(app)
                    logger.info("插件中间件已注册: %s", name)
                except Exception as e:
                    logger.error("插件 %s 注册中间件失败: %s", name, e)

    async def shutdown_all(self, ctx: PluginContext | None = None) -> None:
        """按拓扑序逆序调用 on_shutdown。ctx 可选，默认使用 initialize_all 时保存的 ctx。"""
        self._stop_health_check()
        if not self._order:
            self.event_bus.unsubscribe_all()
            self._started = False
            return
        effective_ctx = ctx or self._ctx or PluginContext(app=self._app, registry=self, event_bus=self.event_bus)
        for name in reversed(self._order):
            entry = self._entries[name]
            if entry.state not in (PluginState.READY, PluginState.DEGRADED):
                continue
            plugin = entry.plugin
            if isinstance(plugin, LifecycleMixin):
                entry.state = PluginState.SHUTTING_DOWN
                try:
                    await asyncio.wait_for(plugin.on_shutdown(effective_ctx), timeout=10.0)
                    entry.state = PluginState.STOPPED
                except Exception as e:
                    logger.warning("插件关闭异常: name=%s error=%s", name, e)
                    entry.state = PluginState.STOPPED
        self.event_bus.unsubscribe_all()
        self._started = False

    # ---- 健康检查后台任务 ----

    def _start_health_check(self, ctx: PluginContext) -> None:
        self._stop_health_event = asyncio.Event()
        self._health_task = asyncio.create_task(self._health_loop(ctx))

    def _stop_health_check(self) -> None:
        if self._stop_health_event:
            self._stop_health_event.set()
        if self._health_task:
            self._health_task.cancel()
            self._health_task = None

    async def _health_loop(self, ctx: PluginContext) -> None:
        consecutive_failures: dict[str, int] = defaultdict(int)
        while self._stop_health_event and not self._stop_health_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_health_event.wait(),
                    timeout=self._health_interval_sec,
                )
                break  # 收到停止信号
            except asyncio.TimeoutError:
                pass
            # 并发检查所有 READY/DEGRADED 且实现 LifecycleMixin 的插件
            targets = [
                (name, e)
                for name, e in self._entries.items()
                if e.state in (PluginState.READY, PluginState.DEGRADED)
                and isinstance(e.plugin, LifecycleMixin)
            ]
            if not targets:
                continue

            async def _check(name: str, entry: _PluginEntry) -> None:
                plugin: LifecycleMixin = entry.plugin  # type: ignore[assignment]  # 已通过 isinstance 过滤
                try:
                    result: PluginHealth = await asyncio.wait_for(
                        plugin.health_check(), timeout=5.0
                    )
                    result.last_check = datetime.now(timezone.utc)
                    entry.health = result
                    if result.healthy:
                        consecutive_failures[name] = 0
                        if entry.state == PluginState.DEGRADED:
                            entry.state = PluginState.READY
                            logger.info("插件恢复健康: %s", name)
                    else:
                        consecutive_failures[name] += 1
                        entry.state = PluginState.DEGRADED
                        if (
                            entry.plugin.tier == PluginTier.CORE
                            and consecutive_failures[name] >= 3
                        ):
                            logger.critical(
                                "CORE 插件健康检查连续 3 次失败: %s (%s)",
                                name, result.message,
                            )
                except Exception as err:
                    consecutive_failures[name] += 1
                    entry.health = PluginHealth(healthy=False, message=str(err))
                    entry.state = PluginState.DEGRADED
                    if (
                        entry.plugin.tier == PluginTier.CORE
                        and consecutive_failures[name] >= 3
                    ):
                        logger.critical(
                            "CORE 插件健康检查异常连续 3 次: %s error=%s", name, err
                        )

            await asyncio.gather(*[_check(n, e) for n, e in targets])

    def get_health_snapshot(self) -> dict[str, dict[str, Any]]:
        snap: dict[str, dict[str, Any]] = {}
        for name, e in self._entries.items():
            snap[name] = {
                "state": e.state.value,
                "tier": e.plugin.tier.value,
                "version": e.plugin.version,
                "healthy": e.health.healthy,
                "message": e.health.message,
                "last_check": e.health.last_check.isoformat() if e.health.last_check else None,
            }
        return snap

    # ---- 钩子调度 ----

    def _eligible_plugins(self, hook_name: str, *, interceptor: bool) -> list[tuple[str, _PluginEntry]]:
        """返回可参与指定钩子的插件列表，按 tier+priority 排序。"""
        result: list[tuple[str, _PluginEntry]] = []
        for name in self._order:
            entry = self._entries[name]
            if entry.state == PluginState.DISABLED:
                continue
            if interceptor:
                # 拦截型：DISABLED/FAILED 的非 CORE 跳过；READY/DEGRADED 参与
                if entry.state in (PluginState.FAILED,) and entry.plugin.tier != PluginTier.CORE:
                    continue
            else:
                # 观察型：best-effort，READY/DEGRADED 都参与
                if entry.state not in (PluginState.READY, PluginState.DEGRADED):
                    continue
            plugin = entry.plugin
            if not hasattr(plugin, hook_name) or not callable(getattr(plugin, hook_name, None)):
                continue
            result.append((name, entry))
        # 按 tier+priority+name 排序
        result.sort(
            key=lambda x: (
                _TIER_ORDER[x[1].plugin.tier],
                x[1].plugin.priority,
                x[0],
            )
        )
        return result

    def _record_timeout(self, entry: _PluginEntry) -> None:
        now = datetime.now(timezone.utc)
        if (now - entry.last_timeout_window).total_seconds() > 60:
            entry.timeout_count = 0
            entry.last_timeout_window = now
        entry.timeout_count += 1
        if entry.timeout_count >= 10 and entry.plugin.tier != PluginTier.CORE:
            entry.state = PluginState.DEGRADED
            logger.warning(
                "插件 1 分钟内超时 %d 次，标记为 DEGRADED: %s",
                entry.timeout_count, entry.plugin.name,
            )

    async def fire_interceptor(
        self,
        hook_name: str,
        ctx: PluginContext,
        *args: Any,
        default: Any = None,
        aggregate: bool = False,
    ) -> Any:
        """拦截型钩子：按 tier+priority 顺序调用。

        - Override.value: 终止链，返回该值
        - Fallback: 转换为 HTTPException 抛出（或 aggregate 模式下收集）
        - Next/None/超时/异常: 继续下一个
        - 所有插件弃权时返回 default
        """
        plugins = self._eligible_plugins(hook_name, interceptor=True)
        if not plugins:
            return default
        rejected: list[Fallback] = []
        for name, entry in plugins:
            plugin = entry.plugin
            method = getattr(plugin, hook_name)
            try:
                result = await asyncio.wait_for(
                    method(ctx, *args), timeout=self._hook_timeout
                )
            except asyncio.TimeoutError:
                logger.warning("钩子超时(%dms): plugin=%s hook=%s", int(self._hook_timeout*1000), name, hook_name)
                self._record_timeout(entry)
                continue
            except Fallback as fb:
                # 插件主动 raise Fallback 等价于返回 Fallback
                if aggregate:
                    rejected.append(fb)
                    continue
                raise HTTPException(status_code=fb.status_code, detail={
                    "code": fb.code, "message": fb.reason, "details": fb.details,
                }) from None
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if entry.plugin.tier == PluginTier.CORE:
                    logger.critical(
                        "CORE 插件钩子异常: plugin=%s hook=%s error=%s", name, hook_name, e
                    )
                    raise
                logger.warning(
                    "插件钩子异常（已跳过）: plugin=%s hook=%s error=%s: %s",
                    name, hook_name, type(e).__name__, e,
                )
                continue

            if result is None or isinstance(result, Next):
                continue
            if isinstance(result, Override):
                return result.value
            if isinstance(result, Fallback):
                if aggregate:
                    rejected.append(result)
                    continue
                raise HTTPException(status_code=result.status_code, detail={
                    "code": result.code,
                    "message": result.reason,
                    "details": result.details,
                })
            # 返回了非标准值：视为 Override
            return result

        if aggregate:
            return rejected
        return default

    async def fire_observer(
        self,
        hook_name: str,
        ctx: PluginContext,
        *args: Any,
        concurrent: bool = False,
    ) -> None:
        """观察型钩子：所有健康插件都执行，异常隔离，返回值忽略。"""
        plugins = self._eligible_plugins(hook_name, interceptor=False)
        if not plugins:
            return

        async def _safe_call(name: str, entry: _PluginEntry) -> None:
            method = getattr(entry.plugin, hook_name)
            try:
                await asyncio.wait_for(method(ctx, *args), timeout=self._hook_timeout)
            except asyncio.TimeoutError:
                logger.warning("观察钩子超时: plugin=%s hook=%s", name, hook_name)
                self._record_timeout(entry)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "观察钩子异常（已隔离）: plugin=%s hook=%s error=%s: %s",
                    name, hook_name, type(e).__name__, e,
                )

        if concurrent:
            await asyncio.gather(
                *[_safe_call(n, e) for n, e in plugins], return_exceptions=True
            )
        else:
            for n, e in plugins:
                await _safe_call(n, e)

    # ---- 全局异常处理器注册 ----

    def register_exception_handlers(self, app: FastAPI) -> None:
        """注册 AppException -> 统一 JSON 响应处理器。"""

        @app.exception_handler(AppException)
        async def _app_exception_handler(request: Request, exc: AppException):  # type: ignore[unused-argument]
            return JSONResponse(
                status_code=exc.status_code,
                content=exc.to_dict(),
            )


# ---- 便捷加载器（Phase 0 为空实现）----


def load_plugins_from_env(registry: PluginRegistry, names: Iterable[str]) -> list[str]:
    """根据名称列表加载内置插件。Phase 0 无内置插件，返回空列表。

    Phase 1a 起根据 name import app.plugins.builtin.<name> 并实例化。
    """
    loaded: list[str] = []
    for name in names:
        if not name:
            continue
        # Phase 0: 没有内置插件
        logger.warning("插件加载未实现（Phase 0），跳过: %s", name)
    return loaded
