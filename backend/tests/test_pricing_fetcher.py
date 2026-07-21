"""Tests for the dynamic SiliconFlow pricing fetcher."""

import json
from unittest.mock import AsyncMock

import pytest

from app.pricing_fetcher import (
    _determine_tier,
    _extract_pricing_from_model,
    _parse_flight_data,
    _resolve_flight_rows,
    get_model_pricing,
    refresh_pricing,
)


def _flight_push(content: str) -> str:
    """Escape content so it can be embedded in a Next.js __next_f.push call."""
    escaped = content.replace('"', '\\"').replace("\n", "\\n")
    return f'self.__next_f.push([1,"{escaped}"])'


def test_resolve_flight_rows():
    """Flight rows of the form HEXID:{...} are parsed into a lookup table."""
    text = 'abc:{"x":1}\nxyz:{"y":2}'
    rows = _resolve_flight_rows(text)
    assert rows == {"abc": {"x": 1}, "xyz": {"y": 2}}


def test_extract_pricing_from_model_direct_fields():
    """Model objects with inputPrice and price fields are parsed directly."""
    model = {"modelName": "org/model", "inputPrice": "1.50", "price": "3.00"}
    input_price, output_price = _extract_pricing_from_model(model, {})
    assert input_price == 1.5
    assert output_price == 3.0


def test_extract_pricing_from_model_pricing_reference():
    """Pricing references pointing to prompt/completion specs are resolved."""
    rows = {
        "pr1": [
            {"specification": "prompt", "price": "0.5"},
            {"specification": "completion", "price": "1.5"},
        ]
    }
    model = {"modelName": "org/model", "pricing": "$pr1"}
    input_price, output_price = _extract_pricing_from_model(model, rows)
    assert input_price == 0.5
    assert output_price == 1.5


def test_extract_pricing_from_model_embedding():
    """Embedding/reranker models with no output price default to 0."""
    model = {"modelName": "org/embedding", "inputPrice": "0.1", "subType": "embedding"}
    input_price, output_price = _extract_pricing_from_model(model, {})
    assert input_price == 0.1
    assert output_price == 0.0


def test_extract_pricing_from_model_unparseable():
    """Completely unparseable price values yield None."""
    model = {"modelName": "org/bad", "inputPrice": "contact sales"}
    input_price, output_price = _extract_pricing_from_model(model, {})
    assert input_price is None
    assert output_price is None


def test_determine_tier():
    """Tier classification reflects price levels and model naming."""
    assert _determine_tier(0.0, 0.0, "free-model") == "free"
    assert _determine_tier(4.0, 16.0, "deepseek-r1") == "reasoning"
    assert _determine_tier(2.0, 2.0, "Pro/model") == "pro"
    assert _determine_tier(1.0, 2.0, "fast-model") == "fast"
    assert _determine_tier(1.0, 4.0, "cheap-model") == "cheap"
    assert _determine_tier(1.0, 10.0, "standard-model") == "standard"


def test_parse_flight_data_empty():
    """Empty HTML yields an empty pricing table."""
    assert _parse_flight_data("") == {}


def test_parse_flight_data_extracts_model():
    """A minimal Flight payload containing one model is parsed correctly."""
    obj = {
        "modelName": "org/model-1",
        "inputPrice": "1.00",
        "price": "2.00",
        "subType": "",
    }
    content = json.dumps(obj, ensure_ascii=False)
    html = _flight_push(content)
    pricing = _parse_flight_data(html)

    assert "org/model-1" in pricing
    record = pricing["org/model-1"]
    assert record["input"] == 1.0
    assert record["output"] == 2.0
    assert record["currency"] == "CNY"
    assert record["source"] == "siliconflow_live"


def test_parse_flight_data_skips_invalid_models():
    """Models without a slash in the name are skipped."""
    obj = {"modelName": "invalidname", "inputPrice": "1.00", "price": "2.00"}
    html = _flight_push(json.dumps(obj, ensure_ascii=False))
    assert _parse_flight_data(html) == {}


def test_get_model_pricing_uses_fallback_for_unknown():
    """Unknown models receive the default fallback pricing."""
    pricing = get_model_pricing("unknown-model")
    assert pricing["currency"] == "CNY"
    assert pricing["source"] == "fallback"


def test_get_model_pricing_known_fallback_model():
    """A model present in the hard-coded fallback table returns that entry."""
    pricing = get_model_pricing("gpt-4o")
    assert pricing["source"] == "fallback"
    assert pricing["input"] == 18.0


@pytest.mark.asyncio
async def test_refresh_pricing_success(monkeypatch, tmp_path):
    """refresh_pricing parses live HTML and updates the cache."""
    obj = {
        "modelName": "org/live-model",
        "inputPrice": "3.00",
        "price": "6.00",
        "subType": "",
    }
    html = _flight_push(json.dumps(obj, ensure_ascii=False))

    async def fake_get(*args, **kwargs):
        resp = AsyncMock()
        resp.raise_for_status = lambda: None
        resp.text = html
        return resp

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    # Redirect cache file into tmp_path to avoid disk side effects.
    monkeypatch.setattr("app.pricing_fetcher._CACHE_FILE", tmp_path / "sf_pricing_cache.json")

    result = await refresh_pricing()
    assert result["success"] is True
    assert result["model_count"] == 1
    assert result["source"] == "siliconflow_live"

    pricing = get_model_pricing("org/live-model")
    assert pricing["input"] == 3.0
    assert pricing["output"] == 6.0


@pytest.mark.asyncio
async def test_refresh_pricing_failure(monkeypatch, tmp_path):
    """On HTTP failure, refresh_pricing reports failure without crashing."""

    async def fake_get(*args, **kwargs):
        resp = AsyncMock()
        resp.raise_for_status = lambda: (_ for _ in ()).throw(Exception("network down"))
        resp.text = ""
        return resp

    monkeypatch.setattr("httpx.AsyncClient.get", fake_get)
    monkeypatch.setattr("app.pricing_fetcher._CACHE_FILE", tmp_path / "sf_pricing_cache.json")

    result = await refresh_pricing()
    assert result["success"] is False
