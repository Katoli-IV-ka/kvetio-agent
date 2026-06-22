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
