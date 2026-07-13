"""Tests for the Web Search layer, engine scheduler, and SSRF protection."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.tools import StubWebSearch, TavilyWebSearch
from app.tools.playwright_search import _is_safe_url
from app.tools.search_engine import (
    EngineHealth,
    MultiEngineSearch,
    SearchEngine,
    SearchEngineError,
    SearchResult,
)


# ---------------------------------------------------------------------------
# StubWebSearch
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_stub_web_search_returns_empty():
    """Stub must return empty results and an error payload for fetch_url."""
    stub = StubWebSearch()
    assert await stub.search("anything") == []
    fetched = await stub.fetch_url("https://example.com")
    assert fetched["error"] == "web_search_disabled"


# ---------------------------------------------------------------------------
# TavilyWebSearch
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tavily_search_uses_time_range(monkeypatch):
    """Tavily search must translate time_range into days."""
    tavily = TavilyWebSearch(api_key="fake-key")
    captured = {}

    async def fake_post(url, *, json=None, **kwargs):
        captured["payload"] = json
        mock_resp = MagicMock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json = lambda: {"results": []}
        return mock_resp

    monkeypatch.setattr(tavily._get_client(), "post", fake_post)

    await tavily.search("AI", top_k=3, time_range="week")

    assert captured["payload"]["days"] == 7
    assert captured["payload"]["topic"] == "news"


@pytest.mark.asyncio
async def test_tavily_search_parses_results(monkeypatch):
    """Tavily results must be normalized to the internal evidence format."""
    tavily = TavilyWebSearch(api_key="fake-key")

    async def fake_post(url, *, json=None, **kwargs):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json = lambda: {
            "results": [
                {"title": "T1", "url": "https://a.com", "content": "content A", "score": 0.9},
                {"title": "T2", "url": "https://b.com", "content": "content B", "score": 0.8},
            ]
        }
        return mock_resp

    monkeypatch.setattr(tavily._get_client(), "post", fake_post)

    results = await tavily.search("test", top_k=2)
    assert len(results) == 2
    assert results[0]["evidence_id"] == "web-0"
    assert results[0]["source_tier"] == "B"
    assert results[0]["signals"]["engine"] == "tavily"


@pytest.mark.asyncio
async def test_tavily_fetch_url(monkeypatch):
    """Tavily fetch_url must call the Tavily extract endpoint."""
    tavily = TavilyWebSearch(api_key="fake-key")

    async def fake_post(url, *, json=None, **kwargs):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = lambda: None
        mock_resp.json = lambda: {
            "results": [
                {"title": "Example", "raw_content": "long content here"}
            ]
        }
        return mock_resp

    monkeypatch.setattr(tavily._get_client(), "post", fake_post)

    result = await tavily.fetch_url("https://example.com", max_chars=10)
    assert result["title"] == "Example"
    assert result["content"] == "long conte"
    assert result["source_tier"] == "B"


# ---------------------------------------------------------------------------
# EngineHealth / MultiEngineSearch
# ---------------------------------------------------------------------------
def test_engine_health_failure_tracking():
    """EngineHealth must mark an engine unavailable after max_failures."""
    health = EngineHealth(max_failures=2)
    assert health.is_available("bing")
    health.record_failure("bing")
    assert health.is_available("bing")
    health.record_failure("bing")
    assert not health.is_available("bing")
    health.record_success("bing")
    assert health.is_available("bing")


class FakeEngine(SearchEngine):
    """A minimal SearchEngine implementation for scheduling tests."""

    def __init__(self, name: str, results: list[SearchResult] | None = None):
        self._name = name
        self._results = results or []

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_available(self) -> bool:
        return True

    async def search(self, query: str, max_results: int = 5, **kwargs: Any) -> list[SearchResult]:
        return self._results

    async def health_check(self) -> bool:
        return True


class FailingEngine(SearchEngine):
    """Engine that always raises."""

    @property
    def name(self) -> str:
        return "failing"

    @property
    def is_available(self) -> bool:
        return True

    async def search(self, query: str, max_results: int = 5, **kwargs: Any) -> list[SearchResult]:
        raise SearchEngineError("boom")

    async def health_check(self) -> bool:
        return False


@pytest.mark.asyncio
async def test_multi_engine_uses_first_success():
    """MultiEngineSearch must return results from the first successful engine."""
    primary = FakeEngine(
        "primary",
        [SearchResult(url="https://primary.test", title="primary result")],
    )
    backup = FakeEngine(
        "backup",
        [SearchResult(url="https://backup.test", title="backup result")],
    )
    multi = MultiEngineSearch([primary, backup])

    result = await multi.search("query")
    assert result["engine_used"] == "primary"
    assert len(result["results"]) == 1


@pytest.mark.asyncio
async def test_multi_engine_failover():
    """MultiEngineSearch must failover to the next engine when the first fails."""
    failing = FailingEngine()
    backup = FakeEngine(
        "backup",
        [SearchResult(url="https://backup.test", title="backup result")],
    )
    multi = MultiEngineSearch([failing, backup])

    result = await multi.search("query")
    assert result["engine_used"] == "backup"
    assert result["failed_engines"][0].startswith("failing(")


@pytest.mark.asyncio
async def test_multi_engine_all_failed():
    """When every engine fails, the result must be empty and engine_used='none'."""
    multi = MultiEngineSearch([FailingEngine(), FailingEngine()])
    result = await multi.search("query")
    assert result["engine_used"] == "none"
    assert result["results"] == []
    assert len(result["failed_engines"]) == 2


# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------
def test_is_safe_url_accepts_public_http():
    ok, reason = _is_safe_url("https://siliconflow.cn/pricing")
    assert ok
    assert reason == "ok"


def test_is_safe_url_rejects_private_ips():
    ok, reason = _is_safe_url("http://192.168.1.1/admin")
    assert not ok
    assert "私网" in reason or "被拒绝" in reason


def test_is_safe_url_rejects_localhost():
    ok, reason = _is_safe_url("http://localhost:8000")
    assert not ok
    assert "localhost" in reason


def test_is_safe_url_rejects_file_scheme():
    ok, reason = _is_safe_url("file:///etc/passwd")
    assert not ok
    assert "file" in reason


def test_is_safe_url_rejects_metadata_endpoint():
    ok, reason = _is_safe_url("http://metadata.google.internal/computeMetadata/v1/")
    assert not ok
    assert "metadata" in reason
