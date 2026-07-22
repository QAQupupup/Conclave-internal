"""
Web Search Docker 集成测试（在 Docker 容器内运行，验证 Playwright 搜索真实可用）

运行方式：
  docker compose -f docker-compose.yml -f docker-compose.websearch-test.yml build websearch-test
  docker compose -f docker-compose.yml -f docker-compose.websearch-test.yml run --rm websearch-test

测试项：
1. Bing 基础搜索是否返回有效结果
2. 中文搜索（自动翻译为英文，v3 新增）
3. Session 预热 + Cookie 持久化（v3 新增）
4. 时间过滤（time_range）是否生效
5. URL 抓取（fetch_url）是否成功
6. SSRF 防护是否生效
7. 并发搜索稳定性
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

# 强制使用 playwright 模式
os.environ.setdefault("CONCLAVE_WEB_SEARCH_MODE", "playwright")


# 标准 CI（无外网）默认跳过 web_search 集成测试；
# 需要验证 Playwright 搜索时设置 CONCLAVE_RUN_WEBSEARCH_TESTS=1
_run_websearch = os.environ.get("CONCLAVE_RUN_WEBSEARCH_TESTS", "") == "1"
pytestmark = pytest.mark.skipif(
    not _run_websearch, reason="需要外网+Playwright 环境，设置 CONCLAVE_RUN_WEBSEARCH_TESTS=1 启用"
)


# ── 测试 1: 基础搜索 ──────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.integration
async def test_web_search_basic():
    """Bing 基础搜索应返回有效结果"""
    from app.tools import get_web_search

    ws = get_web_search()
    print(f"\n  [test_web_search_basic] 搜索模式: {type(ws).__name__}")

    start = time.monotonic()
    results = await ws.search("Python 3.13 new features", top_k=3, language="en-US")
    elapsed = time.monotonic() - start

    print(f"  耗时: {elapsed:.1f}s, 结果数: {len(results)}")
    for i, r in enumerate(results):
        print(f"  [{i + 1}] {r.get('title', 'N/A')[:60]}")
        print(f"      URL: {r.get('url', 'N/A')[:80]}")
        print(f"      Tier: {r.get('source_tier', '?')}")

    assert len(results) > 0, "搜索应返回至少一条结果"
    for r in results:
        assert r.get("url"), "每条结果应包含 URL"
        assert r.get("source_tier"), "每条结果应包含 source_tier"


# ── 测试 2: 中文搜索（自动翻译为英文） ──────────────────────────
@pytest.mark.asyncio
@pytest.mark.integration
async def test_web_search_chinese():
    """中文查询应自动翻译为英文并返回有效结果（v3 翻译方案）"""
    from app.tools import get_web_search

    ws = get_web_search()
    start = time.monotonic()
    results = await ws.search("微服务架构最佳实践", top_k=3, language="zh-CN")
    elapsed = time.monotonic() - start

    print(f"\n  [test_web_search_chinese] 耗时: {elapsed:.1f}s, 结果数: {len(results)}")
    for i, r in enumerate(results):
        print(f"  [{i + 1}] {r.get('title', 'N/A')[:80]}")
        print(f"      URL: {r.get('url', 'N/A')[:80]}")

    # v3 改进：中文查询现在翻译为英文，应在 30s 内完成（之前 60s 超时）
    assert elapsed < 30.0, f"中文搜索耗时 {elapsed:.1f}s 超过 30s（翻译后应接近英文搜索速度）"
    assert len(results) > 0, "中文搜索应返回至少一条结果"


# ── 测试 3: Session 预热 ──────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.integration
async def test_web_search_session_warmup():
    """Session 预热后中文搜索应稳定返回（v3 新增）"""
    from app.tools import get_web_search

    ws = get_web_search()
    # 第一次搜索会触发 _warmup_session（预热），第二次复用 warmed session
    queries = [
        ("Python object oriented design patterns", "en-US"),
        ("微服务架构最佳实践", "zh-CN"),  # 会被翻译为英文
        ("Kubernetes pod scheduling algorithm", "en-US"),
    ]

    results = []
    for q, lang in queries:
        start = time.monotonic()
        r = await ws.search(q, top_k=2, language=lang)
        elapsed = time.monotonic() - start
        results.append((q, lang, elapsed, len(r)))
        print(f"\n  [{q[:30]}...] → {elapsed:.1f}s, {len(r)} 条结果")

    print(f"\n  总耗时: {sum(r[2] for r in results):.1f}s")
    # 第三次搜索（warmed session）应该比第一次快
    first = results[0][2]
    third = results[2][2]
    print(f"  第一次搜索: {first:.1f}s, 第三次搜索: {third:.1f}s")
    print(f"  加速比: {first / third:.1f}x" if third > 0 else "")

    # 所有查询都应返回结果
    for q, _lang, _elapsed, count in results:
        assert count > 0, f"'{q[:30]}...' 应返回至少一条结果"


# ── 测试 4: 时间过滤 ──────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.integration
async def test_web_search_time_filter():
    """时间过滤 (week) 应返回结果"""
    from app.tools import get_web_search

    ws = get_web_search()
    start = time.monotonic()
    results = await ws.search("AI agent framework", top_k=3, language="en-US", time_range="week")
    elapsed = time.monotonic() - start

    print(f"\n  [test_web_search_time_filter] 耗时: {elapsed:.1f}s, 结果数: {len(results)}")
    for r in results:
        print(f"  - {r.get('title', 'N/A')[:80]}")

    assert len(results) > 0, "时间过滤搜索应返回至少一条结果"


# ── 测试 5: URL 抓取 ──────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.integration
async def test_web_search_fetch_url():
    """fetch_url 应能抓取公开网页内容"""
    from app.tools import get_web_fetch

    f = get_web_fetch()
    start = time.monotonic()
    result = await f.fetch_url("https://www.example.com", max_chars=2000)
    elapsed = time.monotonic() - start

    content = result.get("content", "")
    title = result.get("title", "")
    print(f"\n  [test_web_search_fetch_url] 耗时: {elapsed:.1f}s")
    print(f"  标题: {title[:80]}")
    print(f"  内容长度: {len(content)} chars")

    assert len(content) > 100, f"fetch_url 应返回有意义的内容，实际 {len(content)} chars"
    assert not result.get("error"), f"fetch_url 不应有错误: {result.get('error')}"


# ── 测试 6: SSRF 防护 ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_web_search_ssrf_protection():
    """SSRF 防护应拦截内网/私有地址/file 协议"""
    from app.tools import get_web_fetch

    f = get_web_fetch()

    test_cases = [
        ("http://127.0.0.1:8000/", "localhost"),
        ("http://192.168.1.1/", "私有地址"),
        ("file:///etc/passwd", "file 协议"),
        ("http://metadata.google.internal/", "元数据端点"),
    ]

    print()
    for url, label in test_cases:
        result = await f.fetch_url(url, max_chars=500)
        content = result.get("content", "")
        error = result.get("error", "")
        blocked = not content
        print(f"  [{label}] {url} → {'已拦截' if blocked else '⚠ 未拦截'}" + (f" (error: {error})" if error else ""))
        assert blocked, f"SSRF: {label} ({url}) 应被拦截"


# ── 测试 7: 并发搜索 ──────────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.integration
async def test_web_search_concurrent():
    """并发搜索应全部成功返回"""
    from app.tools import get_web_search

    ws = get_web_search()
    queries = [
        ("Kubernetes 1.30 新特性", "zh-CN"),
        ("PostgreSQL 17 release notes", "en-US"),
        ("Qwen 3.5 模型介绍", "zh-CN"),
    ]

    async def search_one(query, lang):
        try:
            results = await ws.search(query, top_k=2, language=lang)
            return len(results)
        except Exception as e:
            print(f"    [{query[:20]}...] 错误: {e}")
            return 0

    start = time.monotonic()
    counts = await asyncio.gather(*[search_one(q, lang_item) for q, lang_item in queries])
    elapsed = time.monotonic() - start

    print(f"\n  [test_web_search_concurrent] 耗时: {elapsed:.1f}s")
    for (q, _), c in zip(queries, counts, strict=False):
        print(f"  [{q[:30]}...] → {c} 条结果")

    assert all(c > 0 for c in counts), f"并发搜索应全部成功，结果: {counts}"


# ── 测试 8: 结果质量验证 ──────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.integration
async def test_web_search_result_quality():
    """搜索结果应包含引用摘要（quote）和正确的域名 tier"""
    from app.tools import get_web_search

    ws = get_web_search()
    results = await ws.search("Python FastAPI async tutorial", top_k=5, language="en-US")

    print(f"\n  [test_web_search_result_quality] 结果数: {len(results)}")
    has_quote = any(r.get("quote") for r in results)
    has_tier = all(r.get("source_tier") for r in results)

    print(f"  有引用摘要: {has_quote}")
    print(f"  全部有 tier: {has_tier}")
    for r in results[:3]:
        quote = (r.get("quote") or "")[:80]
        print(f"  [{r.get('source_tier', '?')}] {r.get('title', 'N/A')[:60]}")
        if quote:
            print(f"       quote: {quote}")

    assert has_quote, "搜索结果应包含引用摘要"
    assert has_tier, "每条结果都应包含 source_tier"


# ── 测试 9: 搜索延迟基准 ──────────────────────────────────────
@pytest.mark.asyncio
@pytest.mark.integration
async def test_web_search_latency_benchmark():
    """搜索延迟基准：单次搜索应在 30s 内完成"""
    from app.tools import get_web_search

    ws = get_web_search()
    queries = [
        "Python asyncio tutorial",
        "Docker compose best practices",
        "PostgreSQL indexing guide",
    ]

    latencies = []
    for q in queries:
        start = time.monotonic()
        results = await ws.search(q, top_k=3, language="en-US")
        elapsed = time.monotonic() - start
        latencies.append(elapsed)
        print(f"\n  [{q}] → {elapsed:.1f}s, {len(results)} 条结果")

    avg = sum(latencies) / len(latencies)
    print(f"\n  平均延迟: {avg:.1f}s, 最大: {max(latencies):.1f}s, 最小: {min(latencies):.1f}s")

    assert avg < 30.0, f"平均搜索延迟 {avg:.1f}s 超过 30s 阈值"
    assert max(latencies) < 60.0, f"最大搜索延迟 {max(latencies):.1f}s 超过 60s 阈值"
