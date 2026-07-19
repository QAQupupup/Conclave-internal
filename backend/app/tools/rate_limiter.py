# Per-domain 限速：token-bucket 算法，按域名隔离，进程级共享
#
# 设计原则（Claude 交叉评审共识）：
# - 按 domain 隔离：不同域名独立限速，避免单域名被刷
# - token-bucket：允许短时突发，但长期平均速率受限
# - 进程级共享：所有协程共用同一个限速器实例
# - 非阻塞获取：令牌不足时返回等待时间，由调用方决定是否等待
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class _TokenBucket:
    """单域名的 token-bucket

    参数：
    - capacity: 桶容量（最大突发请求数）
    - refill_rate: 每秒补充的令牌数（长期平均速率）
    - tokens: 当前令牌数
    - last_refill: 上次补充时间
    """

    capacity: float = 3.0  # 默认 3 次突发
    refill_rate: float = 1.0  # 默认 1 次/秒
    tokens: float = 3.0
    last_refill: float = field(default_factory=time.monotonic)

    def refill(self) -> None:
        """补充令牌（基于时间差）"""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def try_acquire(self) -> tuple[bool, float]:
        """尝试获取一个令牌

        Returns:
            (acquired: bool, wait_seconds: float)
            - acquired=True: 成功获取，wait_seconds=0
            - acquired=False: 令牌不足，wait_seconds=需要等待的时间
        """
        self.refill()
        if self.tokens >= 1.0:
            self.tokens -= 1.0
            return True, 0.0
        # 计算需要等待多久才能有 1 个令牌
        wait = (1.0 - self.tokens) / self.refill_rate
        return False, wait


class DomainRateLimiter:
    """域名级限速器：按域名隔离的 token-bucket 集合

    使用方式：
        limiter = get_rate_limiter()
        # 非阻塞检查
        acquired, wait = limiter.try_acquire("docs.python.org")
        if not acquired:
            await asyncio.sleep(wait)
        # 或直接等待
        await limiter.acquire("docs.python.org")

    默认配置：
    - 普通域名：capacity=3, refill_rate=1/s（突发 3 次，平均 1/s）
    - 可通过 configure_domain 自定义
    """

    def __init__(self) -> None:
        self._buckets: dict[str, _TokenBucket] = {}
        self._lock = asyncio.Lock()
        # 域名级别自定义配置
        self._domain_configs: dict[str, tuple[float, float]] = {}

    def configure_domain(self, domain: str, capacity: float, refill_rate: float) -> None:
        """为特定域名配置限速参数

        Args:
            domain: 域名（不含 scheme）
            capacity: 桶容量（最大突发）
            refill_rate: 每秒补充令牌数
        """
        self._domain_configs[domain] = (capacity, refill_rate)
        # 如果已有 bucket，更新配置
        if domain in self._buckets:
            self._buckets[domain].capacity = capacity
            self._buckets[domain].refill_rate = refill_rate

    def _get_or_create_bucket(self, domain: str) -> _TokenBucket:
        """获取或创建域名的 bucket"""
        if domain not in self._buckets:
            capacity, refill_rate = self._domain_configs.get(domain, (3.0, 1.0))
            self._buckets[domain] = _TokenBucket(
                capacity=capacity,
                refill_rate=refill_rate,
                tokens=capacity,  # 初始满桶
            )
        return self._buckets[domain]

    def try_acquire(self, url_or_domain: str) -> tuple[bool, float]:
        """非阻塞尝试获取令牌

        Args:
            url_or_domain: 完整 URL 或域名
        Returns:
            (acquired, wait_seconds)
        """
        domain = self._extract_domain(url_or_domain)
        bucket = self._get_or_create_bucket(domain)
        return bucket.try_acquire()

    async def acquire(self, url_or_domain: str, max_wait: float = 10.0) -> bool:
        """阻塞式获取令牌（等待直到有令牌或超时）

        Args:
            url_or_domain: 完整 URL 或域名
            max_wait: 最大等待时间（秒）
        Returns:
            True: 成功获取令牌
            False: 等待超时
        """
        domain = self._extract_domain(url_or_domain)
        deadline = time.monotonic() + max_wait

        while True:
            acquired, wait = self.try_acquire(domain)
            if acquired:
                return True
            if time.monotonic() + wait > deadline:
                return False
            await asyncio.sleep(min(wait, 0.5))

    def _extract_domain(self, url_or_domain: str) -> str:
        """从 URL 或域名字符串中提取域名"""
        if "://" in url_or_domain:
            return urlparse(url_or_domain).hostname or url_or_domain
        return url_or_domain

    def status(self) -> dict[str, dict[str, float]]:
        """返回所有域名的限速状态"""
        result = {}
        for domain, bucket in self._buckets.items():
            bucket.refill()
            result[domain] = {
                "tokens": round(bucket.tokens, 2),
                "capacity": bucket.capacity,
                "refill_rate": bucket.refill_rate,
            }
        return result

    def reset(self) -> None:
        """清空所有 bucket（测试用）"""
        self._buckets.clear()


# ---------- 进程级单例 ----------
_rate_limiter: DomainRateLimiter | None = None


def get_rate_limiter() -> DomainRateLimiter:
    """获取全局 DomainRateLimiter 单例"""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = DomainRateLimiter()
    return _rate_limiter


def reset_rate_limiter() -> None:
    """重置 RateLimiter（测试用）"""
    global _rate_limiter
    if _rate_limiter is not None:
        _rate_limiter.reset()
    _rate_limiter = None
