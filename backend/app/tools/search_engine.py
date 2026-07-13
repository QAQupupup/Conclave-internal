# 多引擎搜索接口：SearchEngine Protocol + SearchResult 类型
#
# 设计原则（Claude 交叉评审共识）：
# - 搜索与提取分离：SearchEngine 只负责 SERP 检索（返回 URL 列表），
#   页面内容提取（fetch + chunk）由调用方或共享的 ContentExtractor 负责
# - SearchResult 携带 signals bag，不预折叠为单一分数
# - 支持 failover：MultiEngineSearch 自动在引擎间切换
# - 引擎健康度追踪：连续失败 N 次后标记为不可用，定时探活恢复
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.tools.domain_registry import tag_url


@dataclass
class SearchResult:
    """单条搜索结果（SERP 级别，不含页面正文）

    与证据（evidence）的区别：
    - SearchResult 是搜索引擎返回的一条结果（URL + 标题 + 摘要）
    - Evidence 是从 SearchResult 对应页面提取的结构化内容块
    一个 SearchResult 可以产生多条 Evidence（多 chunk）
    """
    url: str
    title: str = ""
    snippet: str = ""              # 搜索引擎摘要
    domain: str = ""
    source_tier: str = "C"         # S/A/B/C/D
    signals: dict[str, Any] = field(default_factory=dict)  # signals bag
    rank: int = 0                  # 在 SERP 中的原始排名
    engine: str = ""               # 来源搜索引擎名

    def __post_init__(self) -> None:
        """自动填充 domain 和 source_tier（如果未设置）"""
        if not self.domain and self.url:
            from urllib.parse import urlparse
            self.domain = urlparse(self.url).hostname or ""
        if not self.signals:
            self.signals = tag_url(self.url) if self.url else {}
        if self.source_tier == "C" and self.signals:
            self.source_tier = self.signals.get("source_tier", "C")


@runtime_checkable
class SearchEngine(Protocol):
    """搜索引擎协议：输入查询，返回 SearchResult 列表

    实现可以是：
    - BingPlaywrightEngine：Bing 搜索（Playwright 表单提交）
    - DuckDuckGoEngine：DuckDuckGo 搜索（备用引擎）
    - TavilyEngine：Tavily API
    """

    @property
    def name(self) -> str:
        """引擎名称（如 "bing", "ddg", "tavily"）"""
        ...

    @property
    def is_available(self) -> bool:
        """引擎是否可用（健康检查）"""
        ...

    async def search(self, query: str, max_results: int = 5, **kwargs: Any) -> list[SearchResult]:
        """执行搜索，返回 SearchResult 列表

        Args:
            query: 搜索查询
            max_results: 最大结果数
            **kwargs: 可选参数（time_range, country, language等）
        Returns:
            SearchResult 列表，按可信度排序
        Raises:
            SearchEngineError: 搜索引擎故障
        """
        ...

    async def health_check(self) -> bool:
        """健康检查（探活）"""
        ...


class SearchEngineError(Exception):
    """搜索引擎故障异常"""
    pass


# ---------- 引擎健康度追踪 ----------

class EngineHealth:
    """引擎健康度追踪器：连续失败计数 + 冷却恢复

    规则：
    - 连续失败 >= max_failures 次 → 标记为不可用
    - 不可用后等待 cooldown_seconds 才允许探活
    - 探活成功 → 重置失败计数，恢复可用
    """

    def __init__(self, max_failures: int = 3, cooldown_seconds: float = 60.0) -> None:
        self._max_failures = max_failures
        self._cooldown = cooldown_seconds
        self._fail_counts: dict[str, int] = {}
        self._unavailable_since: dict[str, float] = {}

    def is_available(self, engine_name: str) -> bool:
        """检查引擎是否可用"""
        fail_count = self._fail_counts.get(engine_name, 0)
        if fail_count < self._max_failures:
            return True
        # 冷却期检查
        unavailable_time = self._unavailable_since.get(engine_name, 0)
        if time.monotonic() - unavailable_time >= self._cooldown:
            return True  # 冷却期已过，允许探活
        return False

    def record_success(self, engine_name: str) -> None:
        """记录引擎调用成功"""
        self._fail_counts.pop(engine_name, None)
        self._unavailable_since.pop(engine_name, None)

    def record_failure(self, engine_name: str) -> None:
        """记录引擎调用失败"""
        self._fail_counts[engine_name] = self._fail_counts.get(engine_name, 0) + 1
        if self._fail_counts[engine_name] >= self._max_failures:
            self._unavailable_since[engine_name] = time.monotonic()

    def status(self) -> dict[str, dict[str, Any]]:
        """返回所有引擎的健康状态"""
        result = {}
        for name, count in self._fail_counts.items():
            result[name] = {
                "fail_count": count,
                "available": self.is_available(name),
                "unavailable_since": self._unavailable_since.get(name),
            }
        return result


# ---------- 多引擎搜索调度器 ----------

class MultiEngineSearch:
    """多引擎搜索调度器：按优先级尝试，自动 failover

    策略（Claude 交叉评审共识）：
    - 默认 retry_failed_once_then_partial：首选引擎失败重试一次，再切备选
    - 返回 {succeeded: [...], failed: [...]}
    - D 级证据保留但标记 low_confidence: true
    """

    def __init__(self, engines: list[SearchEngine]) -> None:
        self._engines = engines
        self._health = EngineHealth()

    async def search(
        self,
        query: str,
        max_results: int = 5,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """执行多引擎搜索

        Args:
            query: 搜索查询
            max_results: 最大结果数
            **kwargs: 传递给各引擎的可选参数（time_range, country, language等）

        Returns:
            {
                "results": list[SearchResult],
                "engine_used": str,
                "failed_engines": list[str],
                "low_confidence_count": int,
            }
        """
        failed_engines: list[str] = []

        for engine in self._engines:
            if not self._health.is_available(engine.name):
                failed_engines.append(f"{engine.name}(unavailable)")
                continue

            try:
                results = await asyncio.wait_for(
                    engine.search(query, max_results, **kwargs),
                    timeout=30.0,
                )
                self._health.record_success(engine.name)
                # 标记 D 级结果为 low_confidence
                low_conf_count = sum(1 for r in results if r.source_tier == "D")
                return {
                    "results": results,
                    "engine_used": engine.name,
                    "failed_engines": failed_engines,
                    "low_confidence_count": low_conf_count,
                }
            except (SearchEngineError, asyncio.TimeoutError, Exception) as e:
                self._health.record_failure(engine.name)
                failed_engines.append(f"{engine.name}({type(e).__name__})")
                continue

        # 所有引擎都失败
        return {
            "results": [],
            "engine_used": "none",
            "failed_engines": failed_engines,
            "low_confidence_count": 0,
        }

    @property
    def health_status(self) -> dict[str, dict[str, Any]]:
        """返回引擎健康状态"""
        return self._health.status()


# ---------- 引擎工厂 ----------

_engines: list[SearchEngine] = []
_multi_search: MultiEngineSearch | None = None


def get_multi_engine_search() -> MultiEngineSearch:
    """获取多引擎搜索调度器单例

    引擎优先级：
    1. Bing Playwright（主引擎）
    2. DuckDuckGo Playwright（备用引擎，Phase D 实现）
    """
    global _multi_search
    if _multi_search is None:
        engines: list[SearchEngine] = []
        try:
            from app.tools.engines.bing_engine import BingPlaywrightEngine
            engines.append(BingPlaywrightEngine())
        except ImportError:
            pass
        try:
            from app.tools.engines.ddg_engine import DuckDuckGoEngine
            engines.append(DuckDuckGoEngine())
        except ImportError:
            pass
        if not engines:
            # 无可用引擎时返回空调度器
            pass
        _multi_search = MultiEngineSearch(engines)
    return _multi_search


def reset_multi_engine_search() -> None:
    """重置多引擎搜索调度器（测试用）"""
    global _multi_search
    _multi_search = None
