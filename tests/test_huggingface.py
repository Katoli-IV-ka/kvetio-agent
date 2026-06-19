"""Тесты HuggingFace-адаптера через respx (моки httpx)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import pytest
import respx
from httpx import Response

from huggingface import HF_MODELS_URL, HF_ORGS_URL, HuggingFaceAdapter
from models import ICPQuery

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture
def query() -> ICPQuery:
    return ICPQuery(segment="speech-and-audio", keywords_strong=())


def _models_handler(tag_responses: dict[str, list[dict]]) -> Callable:
    """Возвращает respx side_effect, который фильтрует по pipeline_tag."""
    def handler(request):
        tag = request.url.params.get("pipeline_tag", "")
        models = tag_responses.get(tag, [])
        return Response(200, json=models)
    return handler


# ── Тест 1: базовый happy path ────────────────────────────────────────────

def test_fetch_yields_signal_for_org_with_website(query: ICPQuery) -> None:
    org = _load("hf_org_sample.json")          # deepgram, website присутствует
    models = _load("hf_models_sample.json")    # только deepgram в ASR

    with respx.mock(assert_all_called=False) as mock:
        mock.get(HF_MODELS_URL).mock(side_effect=_models_handler({
            "automatic-speech-recognition": [models[0]],  # deepgram только
        }))
        mock.get(f"{HF_ORGS_URL}/deepgram/overview").mock(
            return_value=Response(200, json=org)
        )

        with HuggingFaceAdapter(rate_limit_rps=0, max_models_per_tag=1000) as adapter:
            signals = list(adapter.fetch(query))

    assert len(signals) == 1
    s = signals[0]
    assert s.source == "huggingface"
    assert s.signal_type == "hf_org"
    assert s.company_name == "Deepgram"
    assert s.domain == "https://deepgram.com"
    assert s.linkedin_url is None
    assert s.url == "https://huggingface.co/deepgram"
    assert s.confidence == "medium"
    assert "automatic-speech-recognition" in s.payload["pipeline_tags"]
    assert s.payload["num_models"] == 8
    assert s.payload["num_members"] == 45


# ── Тест 2: org без website → domain=None, сигнал не теряется ────────────

def test_org_without_website_yields_domain_none(query: ICPQuery) -> None:
    org_no_web = _load("hf_org_no_website.json")  # mozilla, website=null
    models = _load("hf_models_sample.json")

    with respx.mock(assert_all_called=False) as mock:
        mock.get(HF_MODELS_URL).mock(side_effect=_models_handler({
            "automatic-speech-recognition": [models[1]],  # mozilla
        }))
        mock.get(f"{HF_ORGS_URL}/mozilla/overview").mock(
            return_value=Response(200, json=org_no_web)
        )

        with HuggingFaceAdapter(rate_limit_rps=0, max_models_per_tag=1000) as adapter:
            signals = list(adapter.fetch(query))

    assert len(signals) == 1
    assert signals[0].domain is None
    assert signals[0].company_name == "Mozilla"


# ── Тест 3: isHf=true → фильтруется, не попадает в output ────────────────

def test_ishf_org_is_filtered(query: ICPQuery) -> None:
    org_hf = _load("hf_org_ishf.json")   # isHf=true
    models = _load("hf_models_sample.json")

    with respx.mock(assert_all_called=False) as mock:
        mock.get(HF_MODELS_URL).mock(side_effect=_models_handler({
            "automatic-speech-recognition": [models[2]],  # huggingface org
        }))
        mock.get(f"{HF_ORGS_URL}/huggingface/overview").mock(
            return_value=Response(200, json=org_hf)
        )

        with HuggingFaceAdapter(rate_limit_rps=0, max_models_per_tag=1000) as adapter:
            signals = list(adapter.fetch(query))

    assert signals == []


# ── Тест 4: org 404 → пропускается молча ─────────────────────────────────

def test_org_404_is_skipped(query: ICPQuery) -> None:
    models = _load("hf_models_sample.json")

    with respx.mock(assert_all_called=False) as mock:
        mock.get(HF_MODELS_URL).mock(side_effect=_models_handler({
            "automatic-speech-recognition": [models[0]],  # deepgram
        }))
        mock.get(f"{HF_ORGS_URL}/deepgram/overview").mock(return_value=Response(404))

        with HuggingFaceAdapter(rate_limit_rps=0, max_models_per_tag=1000) as adapter:
            signals = list(adapter.fetch(query))

    assert signals == []


# ── Тест 5: дедупликация — org в двух tags → один сигнал с обоими tags ───

def test_deduplication_same_org_two_tags(query: ICPQuery) -> None:
    org = _load("hf_org_sample.json")  # deepgram

    asr_model = {"author": "deepgram", "id": "deepgram/nova-2", "downloads": 90000}
    tts_model = {"author": "deepgram", "id": "deepgram/tts-model", "downloads": 10000}

    with respx.mock(assert_all_called=False) as mock:
        mock.get(HF_MODELS_URL).mock(side_effect=_models_handler({
            "automatic-speech-recognition": [asr_model],
            "text-to-speech": [tts_model],
        }))
        mock.get(f"{HF_ORGS_URL}/deepgram/overview").mock(
            return_value=Response(200, json=org)
        )

        with HuggingFaceAdapter(rate_limit_rps=0, max_models_per_tag=1000) as adapter:
            signals = list(adapter.fetch(query))

    assert len(signals) == 1  # один сигнал, не два
    tags = signals[0].payload["pipeline_tags"]
    assert "automatic-speech-recognition" in tags
    assert "text-to-speech" in tags


# ── Тест 6: пустой ответ /api/models → ничего не yielded ─────────────────

def test_empty_models_response_yields_nothing(query: ICPQuery) -> None:
    with respx.mock(assert_all_called=False) as mock:
        mock.get(HF_MODELS_URL).mock(return_value=Response(200, json=[]))

        with HuggingFaceAdapter(rate_limit_rps=0, max_models_per_tag=1000) as adapter:
            signals = list(adapter.fetch(query))

    assert signals == []


# ── Тест 7: неизвестный сегмент → ничего не yielded, нет исключений ───────

def test_unknown_segment_yields_nothing() -> None:
    unknown_query = ICPQuery(segment="nonexistent-segment", keywords_strong=())

    with respx.mock(assert_all_called=False):
        with HuggingFaceAdapter(rate_limit_rps=0, max_models_per_tag=1000) as adapter:
            signals = list(adapter.fetch(unknown_query))

    assert signals == []


# ── Тест 8: fullname отсутствует → fallback на name ──────────────────────

def test_missing_fullname_falls_back_to_name(query: ICPQuery) -> None:
    org_no_fullname = {
        "name": "some-startup",
        "fullname": None,
        "description": "A startup.",
        "website": "https://some-startup.com",
        "numModels": 3,
        "numMembers": 5,
        "isHf": False,
    }
    model = {"author": "some-startup", "id": "some-startup/model", "downloads": 100}

    with respx.mock(assert_all_called=False) as mock:
        mock.get(HF_MODELS_URL).mock(side_effect=_models_handler({
            "automatic-speech-recognition": [model],
        }))
        mock.get(f"{HF_ORGS_URL}/some-startup/overview").mock(
            return_value=Response(200, json=org_no_fullname)
        )

        with HuggingFaceAdapter(rate_limit_rps=0, max_models_per_tag=1000) as adapter:
            signals = list(adapter.fetch(query))

    assert signals[0].company_name == "some-startup"
