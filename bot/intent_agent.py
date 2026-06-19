"""Gemini Flash intent parser for /ask launches."""

from __future__ import annotations

import json
import logging
import os
from inspect import isawaitable
from dataclasses import dataclass
from typing import Any

import httpx

from bot.scenarios import SCENARIOS

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_MODEL = "gemini-2.0-flash-lite"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
FALLBACK_QUESTION = "Не понял запрос. Уточни, что хочешь запустить?"


@dataclass
class ParsedIntent:
    mode: str
    params: dict[str, Any]
    missing_fields: list[str]
    clarification_question: str | None
    confidence: float


def build_system_prompt() -> str:
    lines = [
        "Ты intent parser для Telegram-бота Kvetio.",
        "Верни только JSON с полями: mode, params, missing_fields, clarification_question, confidence.",
        "mode должен быть одним из ключей сценариев ниже.",
        "Если обязательных параметров не хватает, заполни missing_fields и задай один короткий вопрос.",
        "Если запрос непонятен, выбери наиболее вероятный mode и попроси уточнить.",
        "",
        "Сценарии:",
    ]
    for key, scenario in SCENARIOS.items():
        lines.extend(
            [
                f"- {key}: {scenario.name}. {scenario.description}",
                f"  required_params: {', '.join(scenario.required_params)}",
                f"  optional_params: {', '.join(scenario.optional_params) or '-'}",
                "  params:",
            ]
        )
        for param, description in scenario.param_descriptions.items():
            lines.append(f"    - {param}: {description}")
        if scenario.defaults:
            lines.append(f"  defaults: {json.dumps(scenario.defaults, ensure_ascii=False)}")
    return "\n".join(lines)


async def parse_intent(
    messages: list[dict],
    http_client: httpx.AsyncClient | Any | None = None,
) -> ParsedIntent:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        return _fallback_intent()

    model = os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL).strip() or DEFAULT_GEMINI_MODEL
    payload = {
        "systemInstruction": {"parts": [{"text": build_system_prompt()}]},
        "contents": messages,
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    url = GEMINI_ENDPOINT.format(model=model)

    try:
        if http_client is not None:
            response = await http_client.post(url, json=payload, headers=headers, timeout=20)
            await _maybe_await(response.raise_for_status())
            return _coerce_intent_payload(_extract_json_payload(await _maybe_await(response.json())))

        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return _coerce_intent_payload(_extract_json_payload(response.json()))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemini intent parsing failed: %s", exc)
        return _fallback_intent()


def _extract_json_payload(response: dict[str, Any]) -> dict[str, Any]:
    text = (
        response.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )
    if not text:
        raise ValueError("Gemini response did not include candidate text")
    return json.loads(text)


async def _maybe_await(value: Any) -> Any:
    if isawaitable(value):
        return await value
    return value


def _coerce_intent_payload(payload: dict[str, Any]) -> ParsedIntent:
    mode = str(payload.get("mode") or "icp_segment")
    if mode not in SCENARIOS:
        mode = "icp_segment"

    scenario = SCENARIOS[mode]
    params = dict(scenario.defaults)
    raw_params = payload.get("params")
    if isinstance(raw_params, dict):
        params.update(raw_params)

    missing_fields = [
        str(field)
        for field in payload.get("missing_fields", [])
        if isinstance(field, str)
    ]
    for field in scenario.required_params:
        value = params.get(field)
        if value in ("", None, []) and field not in missing_fields:
            missing_fields.append(field)

    question = payload.get("clarification_question")
    if missing_fields and not question:
        question = f"Уточни: {', '.join(missing_fields)}?"

    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    return ParsedIntent(
        mode=mode,
        params=params,
        missing_fields=missing_fields,
        clarification_question=str(question) if question else None,
        confidence=confidence,
    )


def _fallback_intent() -> ParsedIntent:
    return ParsedIntent(
        mode="icp_segment",
        params={},
        missing_fields=["request"],
        clarification_question=FALLBACK_QUESTION,
        confidence=0.0,
    )
