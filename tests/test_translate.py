"""Tests for translate.py: cache-backed translation gateway."""
from __future__ import annotations
import pytest
import translate as tr


class _DictStore:
    """In-memory stub for the translations table."""
    def __init__(self):
        self._data: dict[tuple[str, str], str] = {}
        self.put_calls: list[tuple] = []

    def get(self, source_hash: str, lang: str) -> str | None:
        return self._data.get((source_hash, lang))

    def put(self, source_hash: str, lang: str, source_text: str,
            translated_text: str, model: str | None) -> None:
        self._data[(source_hash, lang)] = translated_text
        self.put_calls.append((source_hash, lang, source_text, translated_text, model))


class _CountingBackend:
    def __init__(self, fn=None):
        self.calls: list[str] = []
        self._fn = fn or (lambda text: f"RU:{text}")

    def __call__(self, text: str) -> str:
        self.calls.append(text)
        return self._fn(text)


def test_cache_miss_calls_backend_and_stores():
    store = _DictStore()
    backend = _CountingBackend()
    result = tr.get_or_translate(store, "Hello world", backend)
    assert result == "RU:Hello world"
    assert len(backend.calls) == 1
    assert len(store.put_calls) == 1


def test_cache_hit_skips_backend():
    store = _DictStore()
    backend = _CountingBackend()
    tr.get_or_translate(store, "Hello world", backend)
    result2 = tr.get_or_translate(store, "Hello world", backend)
    assert result2 == "RU:Hello world"
    assert len(backend.calls) == 1  # backend called only once


def test_changed_text_triggers_new_translation():
    store = _DictStore()
    backend = _CountingBackend()
    tr.get_or_translate(store, "Hello world", backend)
    tr.get_or_translate(store, "Hello world 2", backend)
    assert len(backend.calls) == 2


def test_translator_class_wraps_get_or_translate():
    store = _DictStore()
    backend = _CountingBackend()
    translator = tr.Translator(store=store, backend=backend)
    result = translator.translate("Hello")
    assert result == "RU:Hello"
    assert len(backend.calls) == 1


def test_translator_returns_empty_string_unchanged():
    store = _DictStore()
    backend = _CountingBackend()
    translator = tr.Translator(store=store, backend=backend)
    assert translator.translate("") == ""
    assert len(backend.calls) == 0


def test_translator_returns_none_unchanged():
    store = _DictStore()
    backend = _CountingBackend()
    translator = tr.Translator(store=store, backend=backend)
    assert translator.translate(None) is None
    assert len(backend.calls) == 0


def test_notion_localizer_skips_russian_text():
    backend = _CountingBackend()
    localizer = tr.NotionTextLocalizer(backend)

    result = localizer.localize_text(
        "Компания строит платформу для медицинской диагностики.",
        field="companies.description",
    )

    assert result == "Компания строит платформу для медицинской диагностики."
    assert backend.calls == []


def test_notion_localizer_translates_english_prose_and_preserves_url():
    backend = _CountingBackend(lambda text: "Компания строит AI platform. https://acme.ai")
    localizer = tr.NotionTextLocalizer(backend)

    result = localizer.localize_text(
        "Company builds an AI platform. https://acme.ai",
        field="companies.description",
    )

    assert result == "Компания строит AI platform. https://acme.ai"
    assert backend.calls == ["Company builds an AI platform. https://acme.ai"]


def test_notion_localizer_skips_structural_values():
    backend = _CountingBackend()
    localizer = tr.NotionTextLocalizer(backend)

    assert localizer.localize_text("https://acme.ai", field="companies.website") == "https://acme.ai"
    assert localizer.localize_text("Series A · $12M", field="companies.funding_info") == "Series A · $12M"
    assert backend.calls == []


def test_notion_localizer_fail_sync_raises_on_backend_error():
    localizer = tr.NotionTextLocalizer(
        _CountingBackend(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    )

    with pytest.raises(tr.TranslationError):
        localizer.localize_text("Company builds a radiology AI platform.", field="companies.description")


def test_notion_localizer_write_original_with_warning_returns_original(caplog):
    localizer = tr.NotionTextLocalizer(
        _CountingBackend(lambda _: (_ for _ in ()).throw(RuntimeError("boom"))),
        on_failure="write_original_with_warning",
    )

    text = "Company builds a radiology AI platform."
    assert localizer.localize_text(text, field="companies.description") == text
    assert "writing original" in caplog.text


def test_notion_localizer_skip_field_returns_none_on_failure():
    localizer = tr.NotionTextLocalizer(
        _CountingBackend(lambda _: (_ for _ in ()).throw(RuntimeError("boom"))),
        on_failure="skip_field",
    )

    assert localizer.localize_text(
        "Company builds a radiology AI platform.",
        field="companies.description",
    ) is None


def test_notion_localizer_uses_fallback_backend():
    primary = _CountingBackend(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    fallback = _CountingBackend(lambda text: f"FB:{text}")
    localizer = tr.NotionTextLocalizer(primary, fallback_backend=fallback)

    assert localizer.localize_text(
        "Company builds a radiology AI platform.",
        field="companies.description",
    ) == "FB:Company builds a radiology AI platform."
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FakeHttpClient:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return _FakeResponse(self.data)


def test_gemini_backend_request_and_response_parsing():
    http = _FakeHttpClient({
        "candidates": [{"content": {"parts": [{"text": "Русский текст"}]}}],
    })
    backend = tr.GeminiTranslationBackend(api_key="key", model="gemini-test", http_client=http)

    assert backend("English text") == "Русский текст"
    assert "gemini-test:generateContent" in http.calls[0]["url"]
    assert http.calls[0]["headers"]["x-goog-api-key"] == "key"
    assert http.calls[0]["json"]["contents"][0]["parts"][0]["text"] == "English text"


def test_notion_localizer_skips_russian_text():
    backend = _CountingBackend()
    localizer = tr.NotionTextLocalizer(backend)

    result = localizer.localize_text(
        "Компания строит платформу для медицинской диагностики.",
        field="companies.description",
    )

    assert result == "Компания строит платформу для медицинской диагностики."
    assert backend.calls == []


def test_notion_localizer_translates_english_prose_and_preserves_url():
    backend = _CountingBackend(lambda text: "Компания строит AI platform. https://acme.ai")
    localizer = tr.NotionTextLocalizer(backend)

    result = localizer.localize_text(
        "Company builds an AI platform. https://acme.ai",
        field="companies.description",
    )

    assert result == "Компания строит AI platform. https://acme.ai"
    assert backend.calls == ["Company builds an AI platform. https://acme.ai"]


def test_notion_localizer_skips_structural_values():
    backend = _CountingBackend()
    localizer = tr.NotionTextLocalizer(backend)

    assert localizer.localize_text("https://acme.ai", field="companies.website") == "https://acme.ai"
    assert localizer.localize_text("Series A · $12M", field="companies.funding_info") == "Series A · $12M"
    assert backend.calls == []


def test_notion_localizer_fail_sync_raises_on_backend_error():
    localizer = tr.NotionTextLocalizer(
        _CountingBackend(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    )

    with pytest.raises(tr.TranslationError):
        localizer.localize_text("Company builds a radiology AI platform.", field="companies.description")


def test_notion_localizer_write_original_with_warning_returns_original(caplog):
    localizer = tr.NotionTextLocalizer(
        _CountingBackend(lambda _: (_ for _ in ()).throw(RuntimeError("boom"))),
        on_failure="write_original_with_warning",
    )

    text = "Company builds a radiology AI platform."
    assert localizer.localize_text(text, field="companies.description") == text
    assert "writing original" in caplog.text


def test_notion_localizer_skip_field_returns_none_on_failure():
    localizer = tr.NotionTextLocalizer(
        _CountingBackend(lambda _: (_ for _ in ()).throw(RuntimeError("boom"))),
        on_failure="skip_field",
    )

    assert localizer.localize_text(
        "Company builds a radiology AI platform.",
        field="companies.description",
    ) is None


def test_notion_localizer_uses_fallback_backend():
    primary = _CountingBackend(lambda _: (_ for _ in ()).throw(RuntimeError("boom")))
    fallback = _CountingBackend(lambda text: f"FB:{text}")
    localizer = tr.NotionTextLocalizer(primary, fallback_backend=fallback)

    assert localizer.localize_text(
        "Company builds a radiology AI platform.",
        field="companies.description",
    ) == "FB:Company builds a radiology AI platform."
    assert len(primary.calls) == 1
    assert len(fallback.calls) == 1


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


class _FakeHttpClient:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return _FakeResponse(self.data)


def test_gemini_backend_request_and_response_parsing():
    http = _FakeHttpClient({
        "candidates": [{"content": {"parts": [{"text": "Русский текст"}]}}],
    })
    backend = tr.GeminiTranslationBackend(api_key="key", model="gemini-test", http_client=http)

    assert backend("English text") == "Русский текст"
    assert "gemini-test:generateContent" in http.calls[0]["url"]
    assert http.calls[0]["headers"]["x-goog-api-key"] == "key"
    assert http.calls[0]["json"]["contents"][0]["parts"][0]["text"] == "English text"
