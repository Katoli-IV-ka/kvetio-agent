from __future__ import annotations

from typing import Any

import pytest

from bot import gateway
from bot.intent_agent import ParsedIntent


class FakeTelegram:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.keyboards: list[tuple[str, str, list[list[dict]]]] = []
        self.edits: list[tuple[str, int, str]] = []
        self.answered: list[str] = []

    async def send(self, chat_id: str, text: str) -> dict:
        self.sent.append((chat_id, text))
        return {}

    async def send_with_keyboard(
        self, chat_id: str, text: str, keyboard: list[list[dict]]
    ) -> dict:
        self.keyboards.append((chat_id, text, keyboard))
        return {}

    async def edit_message(self, chat_id: str, message_id: int, text: str) -> dict:
        self.edits.append((chat_id, message_id, text))
        return {}

    async def edit_message_with_keyboard(
        self, chat_id: str, message_id: int, text: str, keyboard: list[list[dict]]
    ) -> dict:
        self.keyboards.append((chat_id, text, keyboard))
        return {}

    async def answer_callback(self, callback_query_id: str) -> None:
        self.answered.append(callback_query_id)


@pytest.fixture(autouse=True)
def clean_sessions() -> None:
    gateway.session_store = gateway.SessionStore()
    yield
    gateway.session_store = gateway.SessionStore()


@pytest.mark.asyncio
async def test_ask_without_text_starts_clarification() -> None:
    tg = FakeTelegram()

    await gateway._handle_message({"chat": {"id": 10}, "text": "/ask"}, client=None, tg=tg)

    assert tg.sent == [("10", "Что хочешь исследовать?")]
    session = await gateway.session_store.get("10")
    assert session is not None
    assert session.state == "clarifying"


@pytest.mark.asyncio
async def test_ask_with_complete_intent_sends_confirmation(monkeypatch) -> None:
    tg = FakeTelegram()

    async def fake_parse(messages: list[dict]) -> ParsedIntent:
        return ParsedIntent(
            mode="single_company",
            params={"company_name": "OpenAI", "stages": "full", "notion_sync": True},
            missing_fields=[],
            clarification_question=None,
            confidence=0.9,
        )

    monkeypatch.setattr(gateway, "parse_intent", fake_parse)

    await gateway._handle_message(
        {"chat": {"id": 10}, "text": "/ask Проанализируй OpenAI"},
        client=None,
        tg=tg,
    )

    assert len(tg.keyboards) == 1
    _, text, keyboard = tg.keyboards[0]
    assert "Сценарий: <b>Анализ компании</b>" in text
    assert "Компания: <b>OpenAI</b>" in text
    assert keyboard[0][0]["callback_data"] == "a1:confirm"
    assert keyboard[0][1]["callback_data"] == "a1:edit"
    assert keyboard[1][0]["callback_data"] == "a1:cancel"


@pytest.mark.asyncio
async def test_plain_text_followup_reparses_active_session(monkeypatch) -> None:
    tg = FakeTelegram()
    parsed_results = [
        ParsedIntent(
            mode="startup_research",
            params={},
            missing_fields=["description"],
            clarification_question="Расскажи о стартапе",
            confidence=0.4,
        ),
        ParsedIntent(
            mode="startup_research",
            params={
                "description": "AI video from text, Series C",
                "company_name": "Synthesia",
                "notion_sync": True,
            },
            missing_fields=[],
            clarification_question=None,
            confidence=0.9,
        ),
    ]

    async def fake_parse(messages: list[dict]) -> ParsedIntent:
        return parsed_results.pop(0)

    monkeypatch.setattr(gateway, "parse_intent", fake_parse)

    await gateway._handle_message({"chat": {"id": 10}, "text": "/ask Исследуй стартап"}, None, tg)
    await gateway._handle_message(
        {"chat": {"id": 10}, "text": "Synthesia, делают AI-видео из текста, Series C"},
        None,
        tg,
    )

    assert tg.sent == [("10", "Расскажи о стартапе")]
    assert len(tg.keyboards) == 1
    _, text, _ = tg.keyboards[0]
    assert "Сценарий: <b>Исследование стартапа</b>" in text
    assert "Описание: <b>AI video from text, Series C</b>" in text


@pytest.mark.asyncio
async def test_ask_confirm_fires_routine_once_and_deletes_session(monkeypatch) -> None:
    tg = FakeTelegram()
    fire_calls: list[str] = []

    async def fake_parse(messages: list[dict]) -> ParsedIntent:
        return ParsedIntent(
            mode="single_company",
            params={"company_name": "OpenAI", "stages": "full", "notion_sync": True},
            missing_fields=[],
            clarification_question=None,
            confidence=0.9,
        )

    def fake_fire(text: str) -> dict[str, Any]:
        fire_calls.append(text)
        return {"dev_mode": True}

    monkeypatch.setattr(gateway, "parse_intent", fake_parse)
    monkeypatch.setattr(gateway, "fire", fake_fire)

    await gateway._handle_message({"chat": {"id": 10}, "text": "/ask OpenAI"}, None, tg)
    await gateway._handle_callback(
        {
            "id": "cq1",
            "data": "a1:confirm",
            "message": {"message_id": 99, "chat": {"id": 10}},
        },
        tg,
    )

    assert fire_calls == ["mode=single_company; company=OpenAI; stages=full; notion_sync=true"]
    assert tg.edits == [("10", 99, "🟡 <b>[dev] Рутина запущена</b>")]
    assert await gateway.session_store.get("10") is None
