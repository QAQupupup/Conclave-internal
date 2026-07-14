"""Verify per-stage temperature configuration in LLM calls."""

from unittest.mock import MagicMock

import pytest

from app.agents.llm import STAGE_TEMPERATURES, RealLLM


@pytest.mark.asyncio
async def test_stage_temperature_map_values():
    """Temperatures must follow the hard constraints in project memory."""
    temps = STAGE_TEMPERATURES()
    assert temps["clarify"] == 0.0
    assert temps["intra_team"] == 0.3
    assert temps["cross_team"] == 0.0
    assert temps["evidence_check"] == 0.0
    assert temps["arbitrate"] == 0.0
    assert temps["produce"] == 0.1


async def _capture_temperature_for_stage(stage: str, monkeypatch) -> float:
    """Instantiate RealLLM, mock the HTTP call, and return the temperature sent."""
    llm = RealLLM()
    captured = {}

    async def fake_post(url, *, headers=None, json=None, timeout=None):
        captured["body"] = json
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json = lambda: {
            "choices": [
                {
                    "message": {
                        "content": '{"result": "ok"}',
                        "reasoning_content": None,
                    }
                }
            ],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
        mock_resp.raise_for_status = lambda: None
        return mock_resp

    monkeypatch.setattr(llm._client, "post", fake_post)

    await llm._call_api(
        user_prompt="hello",
        schema_desc='{"type":"object"}',
        stage=stage,
        attempt=1,
        config_override=("https://api.example.com/v1", "fake-key", "gpt-test"),
    )

    return captured["body"]["temperature"]


@pytest.mark.asyncio
async def test_clarify_stage_uses_zero_temperature(monkeypatch):
    """clarify stage must use temperature 0 for deterministic anchoring."""
    assert await _capture_temperature_for_stage("clarify", monkeypatch) == 0.0


@pytest.mark.asyncio
async def test_intra_team_stage_uses_discussion_temperature(monkeypatch):
    """intra_team stage must allow a small amount of creativity (0.3)."""
    assert await _capture_temperature_for_stage("intra_team", monkeypatch) == 0.3


@pytest.mark.asyncio
async def test_cross_team_stage_uses_zero_temperature(monkeypatch):
    """cross_team stage must use temperature 0."""
    assert await _capture_temperature_for_stage("cross_team", monkeypatch) == 0.0


@pytest.mark.asyncio
async def test_evidence_check_stage_uses_zero_temperature(monkeypatch):
    """evidence_check stage must use temperature 0."""
    assert await _capture_temperature_for_stage("evidence_check", monkeypatch) == 0.0


@pytest.mark.asyncio
async def test_arbitrate_stage_uses_zero_temperature(monkeypatch):
    """arbitrate stage must use temperature 0."""
    assert await _capture_temperature_for_stage("arbitrate", monkeypatch) == 0.0


@pytest.mark.asyncio
async def test_produce_stage_uses_low_temperature(monkeypatch):
    """produce stage must use temperature 0.1 for mostly deterministic code generation."""
    assert await _capture_temperature_for_stage("produce", monkeypatch) == 0.1


@pytest.mark.asyncio
async def test_unknown_stage_defaults_to_zero_temperature(monkeypatch):
    """An unrecognized stage must default to the safest temperature (0.0)."""
    assert await _capture_temperature_for_stage("unknown_stage", monkeypatch) == 0.0
