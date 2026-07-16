# 运维面板指标采集：内存环形缓冲区 + 后台采集
# 每 10 秒采集一次系统资源，保留最近 360 个数据点（60 分钟）
from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from dataclasses import dataclass
from typing import Any

# 缓冲区大小：360 点 × 10 秒 = 60 分钟
_BUFFER_SIZE = int(os.environ.get("METRICS_BUFFER_SIZE", "360"))
# 采集间隔（秒）
_COLLECTION_INTERVAL = float(os.environ.get("METRICS_COLLECTION_INTERVAL", "10"))


@dataclass
class MetricPoint:
    """单个采集点的指标快照"""
    timestamp: float
    cpu_percent: float
    memory_mb: float
    memory_percent: float
    total_tokens: int
    total_cost_usd: float
    api_requests_total: int
    api_requests_per_minute: float
    avg_latency_ms: float
    active_meetings: int
    browser_contexts: int


class MetricsStore:
    """进程级单例指标存储

    后台 asyncio.Task 每 10 秒采集一次系统指标，
    存入环形缓冲区。前端通过 GET /metrics 和 /metrics/history 读取。
    """

    def __init__(self) -> None:
        self._buffer: deque[MetricPoint] = deque(maxlen=_BUFFER_SIZE)
        self._task: asyncio.Task | None = None
        # 请求计数器（用于计算吞吐量）
        self._request_count: int = 0
        self._request_latencies: deque[float] = deque(maxlen=100)
        self._started_at: float = time.time()

    @property
    def uptime_seconds(self) -> float:
        return time.time() - self._started_at

    def record_request(self, latency_ms: float) -> None:
        """记录一次 API 请求的延迟"""
        self._request_count += 1
        self._request_latencies.append(latency_ms)

    def latest(self) -> MetricPoint | None:
        """返回最新的指标快照"""
        return self._buffer[-1] if self._buffer else None

    def history(self) -> list[MetricPoint]:
        """返回全部历史数据"""
        return list(self._buffer)

    def snapshot(self) -> dict[str, Any]:
        """返回当前完整快照（供 GET /metrics 使用）"""
        latest = self.latest()
        avg_latency = (
            sum(self._request_latencies) / len(self._request_latencies)
            if self._request_latencies
            else 0.0
        )
        requests_per_minute = (
            self._request_count / (self.uptime_seconds / 60.0)
            if self.uptime_seconds > 0
            else 0.0
        )

        return {
            "timestamp": time.time(),
            "system": {
                "cpu_percent": latest.cpu_percent if latest else 0.0,
                "memory_mb": latest.memory_mb if latest else 0.0,
                "memory_percent": latest.memory_percent if latest else 0.0,
                "uptime_seconds": self.uptime_seconds,
            },
            "conclave": {
                "active_meetings": latest.active_meetings if latest else 0,
                "browser_contexts": latest.browser_contexts if latest else 0,
            },
            "throughput": {
                "api_requests_total": self._request_count,
                "api_requests_per_minute": round(requests_per_minute, 2),
                "avg_latency_ms": round(avg_latency, 1),
            },
        }

    async def _collect(self) -> None:
        """后台采集循环"""
        import psutil

        while True:
            try:
                # 系统资源
                cpu = psutil.cpu_percent(interval=0.5)
                mem = psutil.virtual_memory()
                memory_mb = mem.used / (1024 * 1024)
                memory_percent = mem.percent

                # Token 成本（从 CostTracker 获取）
                total_tokens = 0
                total_cost_usd = 0.0
                try:
                    from app.observability.cost_tracker import get_cost_tracker
                    s = get_cost_tracker().summary()
                    total_tokens = s.get("total_tokens", 0)
                    total_cost_usd = s.get("total_cost_usd", 0.0)
                except Exception:
                    pass

                # 活跃会议数
                active_meetings = 0
                try:
                    from sqlalchemy import text as _text
                    from app.db.engine import async_session_factory as _asf

                    async with _asf() as session:
                        result = await session.execute(
                            _text("SELECT COUNT(*) AS cnt FROM meetings WHERE status = 'RUNNING'")
                        )
                        row = result.mappings().first()
                    if row:
                        # RowMapping，用 key 访问
                        active_meetings = row.get("cnt", row.get("count", 0))
                except Exception:
                    pass

                # 浏览器上下文数
                browser_contexts = 0
                try:
                    from app.tools.browser_tool import get_browser_pool
                    browser_contexts = get_browser_pool().context_count
                except Exception:
                    pass

                # 请求吞吐量
                requests_per_minute = (
                    self._request_count / (self.uptime_seconds / 60.0)
                    if self.uptime_seconds > 0
                    else 0.0
                )
                avg_latency = (
                    sum(self._request_latencies) / len(self._request_latencies)
                    if self._request_latencies
                    else 0.0
                )

                point = MetricPoint(
                    timestamp=time.time(),
                    cpu_percent=cpu,
                    memory_mb=round(memory_mb, 1),
                    memory_percent=round(memory_percent, 1),
                    total_tokens=total_tokens,
                    total_cost_usd=round(total_cost_usd, 6),
                    api_requests_total=self._request_count,
                    api_requests_per_minute=round(requests_per_minute, 2),
                    avg_latency_ms=round(avg_latency, 1),
                    active_meetings=active_meetings,
                    browser_contexts=browser_contexts,
                )
                self._buffer.append(point)

            except Exception:
                pass  # 采集失败不影响主流程

            await asyncio.sleep(_COLLECTION_INTERVAL)

    def start(self) -> None:
        """启动后台采集任务（在 lifespan 中调用）"""
        if self._task is None:
            self._task = asyncio.ensure_future(self._collect())

    async def stop(self) -> None:
        """停止后台采集"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


# ---------- 进程级单例 ----------
_metrics_store: MetricsStore | None = None


def get_metrics_store() -> MetricsStore:
    """获取全局 MetricsStore 单例"""
    global _metrics_store
    if _metrics_store is None:
        _metrics_store = MetricsStore()
    return _metrics_store