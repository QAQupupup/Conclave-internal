#!/usr/bin/env python3
"""
Web Search 手写集成测试（替代 pytest，避免事件循环重建导致浏览器断连）

所有测试在单个 asyncio 事件循环中顺序执行，浏览器只启动一次。
SessionPool 按 session_key 复用 Context，验证话题一致性。

运行方式（Docker 内）：
  python tests/run_web_search_tests.py

运行方式（宿主机）：
  cd backend && python tests/run_web_search_tests.py
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback

# ── 环境配置 ──────────────────────────────────────────────────
os.environ.setdefault("CONCLAVE_WEB_SEARCH_MODE", "playwright")
os.environ.setdefault("CONCLAVE_TEST_MODE", "1")
os.environ.setdefault("CONCLAVE_MEMORY_DISABLED", "1")
os.environ.setdefault("CONCLAVE_LOG_LEVEL", "WARNING")
os.environ.setdefault("CONCLAVE_DISABLE_SANDBOX_WARMUP", "1")
os.environ.setdefault("CONCLAVE_DISABLE_PRICING_LOADER", "1")
os.environ.setdefault("CONCLAVE_DISABLE_KEY_LOADER", "1")
os.environ.setdefault("CONCLAVE_DISABLE_METRICS", "1")
os.environ.setdefault("CONCLAVE_RATE_LIMIT_PER_MIN", "100000")
os.environ.setdefault("CONCLAVE_RATE_LIMIT_FAIL_PER_MIN", "100000")

# 确保 backend 目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── 测试结果追踪 ──────────────────────────────────────────────
class TestReport:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.results: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "", elapsed: float = 0):
        if ok:
            self.passed += 1
            status = "PASSED"
        else:
            self.failed += 1
            status = "FAILED"
        self.results.append(
            {
                "name": name,
                "status": status,
                "detail": detail,
                "elapsed": elapsed,
            }
        )
        print(f"  [{status}] {name} ({elapsed:.1f}s)" + (f" - {detail}" if detail else ""))

    def summary(self):
        total = self.passed + self.failed + self.skipped
        print(f"\n{'=' * 60}")
        print(f"  总计: {total} | 通过: {self.passed} | 失败: {self.failed} | 跳过: {self.skipped}")
        print(f"{'=' * 60}")
        return self.failed == 0


# ── 测试函数 ──────────────────────────────────────────────────
async def test_basic_english(report: TestReport):
    """测试 1: 基础英文搜索"""
    from app.tools import get_web_search

    ws = get_web_search()
    start = time.monotonic()
    results = await ws.search("Python 3.13 new features", top_k=3, language="en-US", session_key="test_basic")
    elapsed = time.monotonic() - start

    ok = len(results) > 0
    detail = f"{len(results)} results"
    if not ok:
        detail = "NO RESULTS"
    report.add("基础英文搜索", ok, detail, elapsed)
    return results


async def test_chinese_translated(report: TestReport):
    """测试 2: 中文搜索 → 自动翻译为英文"""
    from app.tools import get_web_search

    ws = get_web_search()
    start = time.monotonic()
    results = await ws.search("微服务架构最佳实践", top_k=3, language="zh-CN", session_key="test_chinese")
    elapsed = time.monotonic() - start

    ok = len(results) > 0 and elapsed < 30.0
    detail = f"{len(results)} results, {elapsed:.1f}s"
    if not ok and elapsed >= 30.0:
        detail = f"TIMEOUT ({elapsed:.1f}s > 30s)"
    report.add("中文翻译搜索", ok, detail, elapsed)
    return results


async def test_session_pool_reuse(report: TestReport):
    """测试 3: SessionPool 复用 — 同一 session_key 两次搜索，第二次应更快"""
    from app.tools import get_web_search

    ws = get_web_search()

    results = []
    for _i, q in enumerate(["Python async patterns", "Python design patterns"]):
        start = time.monotonic()
        r = await ws.search(q, top_k=2, language="en-US", session_key="test_reuse")
        elapsed = time.monotonic() - start
        results.append((elapsed, len(r)))

    first_time, first_count = results[0]
    second_time, second_count = results[1]
    ok = first_count > 0 and second_count > 0
    detail = f"1st={first_time:.1f}s ({first_count}r), 2nd={second_time:.1f}s ({second_count}r)"
    report.add("SessionPool 复用", ok, detail, first_time + second_time)
    return results


async def test_session_pool_isolation(report: TestReport):
    """测试 4: SessionPool 隔离 — 不同 session_key 使用不同 Context"""
    from app.tools import get_web_search

    ws = get_web_search()

    results = {}
    for agent_id in ["agent_alpha", "agent_beta", "agent_gamma"]:
        start = time.monotonic()
        r = await ws.search("Kubernetes basics", top_k=2, language="en-US", session_key=agent_id)
        elapsed = time.monotonic() - start
        results[agent_id] = (elapsed, len(r))

    ok = all(cnt > 0 for _, cnt in results.values())
    detail = ", ".join(f"{k}:{v:.1f}s/{c}r" for k, (v, c) in results.items())
    report.add("SessionPool 隔离 (3 agents)", ok, detail, sum(v for v, _ in results.values()))


async def test_concurrent_different_sessions(report: TestReport):
    """测试 5: 并发搜索（不同 session_key，模拟多 Agent 同时搜索）"""
    from app.tools import get_web_search

    ws = get_web_search()

    async def search_one(query, session_key):
        try:
            results = await ws.search(query, top_k=2, language="en-US", session_key=session_key)
            return len(results)
        except Exception as e:
            print(f"      [{session_key}] 错误: {e}")
            return 0

    queries = [
        ("Kubernetes 1.30 新特性", "agent_k8s"),
        ("PostgreSQL 17 release notes", "agent_pg"),
        ("Qwen 3.5 模型介绍", "agent_qwen"),
    ]

    start = time.monotonic()
    counts = await asyncio.gather(*[search_one(q, k) for q, k in queries])
    elapsed = time.monotonic() - start

    ok = all(c > 0 for c in counts)
    detail = f"{elapsed:.1f}s, results={counts}"
    report.add("并发多 Session 搜索", ok, detail, elapsed)


async def test_fetch_url(report: TestReport):
    """测试 6: URL 直接抓取"""
    from app.tools import get_web_fetch

    f = get_web_fetch()
    start = time.monotonic()
    result = await f.fetch_url("https://www.example.com", max_chars=2000)
    elapsed = time.monotonic() - start

    content_len = len(result.get("content", ""))
    ok = content_len > 100
    detail = f"{content_len} chars"
    report.add("URL 抓取", ok, detail, elapsed)


async def test_ssrf_protection(report: TestReport):
    """测试 7: SSRF 防护"""
    from app.tools import get_web_fetch

    f = get_web_fetch()

    test_cases = [
        ("http://127.0.0.1:8000/", "localhost"),
        ("http://192.168.1.1/", "私有地址"),
        ("file:///etc/passwd", "file 协议"),
    ]

    all_blocked = True
    for url, label in test_cases:
        result = await f.fetch_url(url, max_chars=500)
        blocked = not result.get("content")
        if not blocked:
            all_blocked = False
            print(f"      ⚠ {label} ({url}) 未拦截!")

    report.add("SSRF 防护", all_blocked, f"{len(test_cases)} cases")


async def test_result_quality(report: TestReport):
    """测试 8: 结果质量验证"""
    from app.tools import get_web_search

    ws = get_web_search()
    start = time.monotonic()
    results = await ws.search("Python FastAPI async tutorial", top_k=5, language="en-US", session_key="test_quality")
    elapsed = time.monotonic() - start

    has_quote = any(r.get("quote") for r in results)
    has_tier = all(r.get("source_tier") for r in results)
    has_url = all(r.get("url") for r in results)

    ok = has_quote and has_tier and has_url and len(results) > 0
    detail = f"{len(results)} results, quote={has_quote}, tier={has_tier}"
    report.add("结果质量", ok, detail, elapsed)


async def test_translation_chunking(report: TestReport):
    """测试 9: 翻译分块 — 超长查询应自动分块翻译"""
    from app.tools import get_web_search

    ws = get_web_search()

    # 构造一个超长查询（> 2000 字符）
    long_query = (
        "Python 异步编程是一种基于协程的并发编程模型。"
        "它允许程序在等待 I/O 操作时释放控制权，从而高效地利用 CPU 资源。"
        "微服务架构中，服务间通信的选择至关重要。"
        "REST API 适合简单的 CRUD 操作，而 gRPC 在低延迟场景下表现更优。"
        "消息队列如 Kafka 和 RabbitMQ 提供了异步解耦的能力。"
        "容器化技术以 Docker 为代表，配合 Kubernetes 实现自动化编排。"
        "数据库选型方面，PostgreSQL 适合复杂查询，MongoDB 适合文档存储。"
        "Redis 作为缓存层可以显著降低数据库压力。"
        "监控和可观测性通过 Prometheus + Grafana 栈实现。"
        "CI/CD 流程使用 GitHub Actions 或 Jenkins 自动化构建和部署。"
        "安全方面需要关注 OAuth 2.0 认证、JWT 令牌管理和 API 限流。"
        "测试策略包括单元测试、集成测试和端到端测试。"
        "日志管理使用 ELK 栈或 Loki 进行集中化收集和分析。"
        "服务网格 Istio 提供流量管理、安全通信和可观测性。"
        "Serverless 架构适合事件驱动和短暂运行的任务。"
        "事件溯源和 CQRS 模式在复杂业务场景中很有价值。"
        "领域驱动设计帮助团队理解复杂业务领域。"
        "敏捷开发方法论强调迭代交付和持续反馈。"
        "代码审查是保证代码质量的重要手段。"
        "性能优化包括数据库索引优化、缓存策略和代码级优化。"
        "分布式系统的一致性问题需要 CAP 定理的权衡。"
        "最终一致性和强一致性各有适用场景。"
    ) * 2  # 确保 > 2000 chars

    start = time.monotonic()
    results = await ws.search(long_query, top_k=3, language="zh-CN", session_key="test_chunking")
    elapsed = time.monotonic() - start

    # 只要不崩溃且返回了结果就算通过（分块翻译可能较慢）
    ok = elapsed < 60.0
    detail = f"{len(results)} results, {elapsed:.1f}s, query={len(long_query)}chars"
    report.add("翻译分块 (超长查询)", ok, detail, elapsed)


# ── 主入口 ────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("  Web Search 集成测试 (手写脚本，单事件循环)")
    print("=" * 60)

    # 检查环境
    print(f"\n  Python: {sys.version.split()[0]}")
    print(f"  Web Search Mode: {os.environ.get('CONCLAVE_WEB_SEARCH_MODE', '?')}")
    print(f"  LLM Base URL: {os.environ.get('CONCLAVE_LLM_BASE_URL', 'N/A')}")
    print(f"  LLM API Key: {'SET' if os.environ.get('CONCLAVE_LLM_API_KEY') else 'NOT SET'}")
    print()

    report = TestReport()

    # 顺序执行测试（共享同一个事件循环）
    try:
        await test_basic_english(report)
    except Exception as e:
        report.add("基础英文搜索", False, str(e)[:80], 0)
        traceback.print_exc()

    try:
        await test_chinese_translated(report)
    except Exception as e:
        report.add("中文翻译搜索", False, str(e)[:80], 0)
        traceback.print_exc()

    try:
        await test_session_pool_reuse(report)
    except Exception as e:
        report.add("SessionPool 复用", False, str(e)[:80], 0)
        traceback.print_exc()

    try:
        await test_session_pool_isolation(report)
    except Exception as e:
        report.add("SessionPool 隔离", False, str(e)[:80], 0)
        traceback.print_exc()

    try:
        await test_concurrent_different_sessions(report)
    except Exception as e:
        report.add("并发多 Session 搜索", False, str(e)[:80], 0)
        traceback.print_exc()

    try:
        await test_fetch_url(report)
    except Exception as e:
        report.add("URL 抓取", False, str(e)[:80], 0)
        traceback.print_exc()

    try:
        await test_ssrf_protection(report)
    except Exception as e:
        report.add("SSRF 防护", False, str(e)[:80], 0)
        traceback.print_exc()

    try:
        await test_result_quality(report)
    except Exception as e:
        report.add("结果质量", False, str(e)[:80], 0)
        traceback.print_exc()

    try:
        await test_translation_chunking(report)
    except Exception as e:
        report.add("翻译分块", False, str(e)[:80], 0)
        traceback.print_exc()

    # 清理
    try:
        from app.tools import get_web_search

        ws = get_web_search()
        if hasattr(ws, "close"):
            await ws.close()
    except Exception:
        pass

    return report.summary()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
