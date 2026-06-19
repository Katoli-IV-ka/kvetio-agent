from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from bot.config import RunConfig
from bot.intent_agent import ParsedIntent, _coerce_intent_payload, build_system_prompt, parse_intent
from bot.scenarios import SCENARIOS
from bot.session import BotSession, SessionStore


def test_scenarios_include_required_modes() -> None:
    assert set(SCENARIOS) >= {"icp_segment", "single_company", "startup_research"}
    assert SCENARIOS["icp_segment"].required_params == ["segments"]
    assert SCENARIOS["single_company"].required_params == ["company_name"]
    assert SCENARIOS["startup_research"].required_params == ["description"]


def test_system_prompt_is_generated_from_scenarios() -> None:
    prompt = build_system_prompt()
    assert "icp_segment" in prompt
    assert "single_company" in prompt
    assert "startup_research" in prompt
    assert "medical-imaging" in prompt


def test_coerce_intent_applies_defaults_and_missing_fields() -> None:
    parsed = _coerce_intent_payload(
        {
            "mode": "single_company",
            "params": {"company_name": "OpenAI"},
            "missing_fields": [],
            "clarification_question": None,
            "confidence": 0.8,
        }
    )

    assert parsed.mode == "single_company"
    assert parsed.params["company_name"] == "OpenAI"
    assert parsed.params["stages"] == "full"
    assert parsed.params["notion_sync"] is True
    assert parsed.missing_fields == []


def test_run_config_validates_mode_specific_required_fields() -> None:
    RunConfig(run_mode="single_company", segments=[], limit_per_segment=5, stages="full", company_name="OpenAI").validate()
    RunConfig(
        run_mode="startup_research",
        segments=[],
        limit_per_segment=5,
        stages="full",
        startup_description="AI video from text",
    ).validate()

    with pytest.raises(ValueError, match="company_name"):
        RunConfig(run_mode="single_company", segments=[], limit_per_segment=5, stages="full").validate()

    with pytest.raises(ValueError, match="description"):
        RunConfig(run_mode="startup_research", segments=[], limit_per_segment=5, stages="full").validate()


@pytest.mark.asyncio
async def test_session_store_cleans_up_expired_sessions() -> None:
    now = datetime(2026, 6, 19, tzinfo=UTC)
    store = SessionStore(ttl=timedelta(minutes=30), now=lambda: now)
    expired = BotSession(
        chat_id="old",
        messages=[],
        parsed_intent=None,
        state="clarifying",
        clarification_count=0,
        created_at=now - timedelta(minutes=31),
    )
    active = BotSession(
        chat_id="new",
        messages=[],
        parsed_intent=None,
        state="clarifying",
        clarification_count=0,
        created_at=now,
    )

    await store.set(expired)
    await store.set(active)

    assert await store.get("old") is None
    assert await store.get("new") == active


@pytest.mark.asyncio
async def test_parse_intent_returns_fallback_when_gemini_fails(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "key")

    class FailingClient:
        async def post(self, *args, **kwargs):
            raise RuntimeError("network down")

    parsed = await parse_intent(
        [{"role": "user", "parts": [{"text": "Проанализируй OpenAI"}]}],
        http_client=FailingClient(),
    )

    assert parsed.mode == "icp_segment"
    assert parsed.missing_fields
    assert parsed.clarification_question == "Не понял запрос. Уточни, что хочешь запустить?"


@pytest.mark.asyncio
async def test_parse_intent_reads_json_candidate(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "key")
    response = AsyncMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": (
                                '{"mode":"single_company","params":{"company_name":"OpenAI"},'
                                '"missing_fields":[],"clarification_question":null,"confidence":0.9}'
                            )
                        }
                    ]
                }
            }
        ]
    }
    client = AsyncMock()
    client.post.return_value = response

    parsed = await parse_intent(
        [{"role": "user", "parts": [{"text": "Проанализируй OpenAI"}]}],
        http_client=client,
    )

    assert parsed == ParsedIntent(
        mode="single_company",
        params={"company_name": "OpenAI", "stages": "full", "notion_sync": True},
        missing_fields=[],
        clarification_question=None,
        confidence=0.9,
    )
