"""Translation cache gateway.

get_or_translate: hash source text → lookup in store → call backend on miss.
Translator: gateway class injected into NotionSync and render_and_write_body.

Store interface (duck-typed):
  store.get(source_hash: str, lang: str) -> str | None
  store.put(source_hash: str, lang: str, source_text: str,
            translated_text: str, model: str | None) -> None

In tests, inject _DictStore stub.
In production, inject a Supabase-backed store querying the translations table.
"""
from __future__ import annotations

import hashlib


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def get_or_translate(store, text: str, backend, lang: str = "ru") -> str:
    h = _sha256(text)
    cached = store.get(h, lang)
    if cached is not None:
        return cached
    translated = backend(text)
    store.put(h, lang, text, translated, model=None)
    return translated


class Translator:
    """Injected gateway. translate(text) returns cached or fresh translation."""

    def __init__(self, store, backend, lang: str = "ru"):
        self._store = store
        self._backend = backend
        self._lang = lang

    def translate(self, text) -> str | None:
        if not text:
            return text
        return get_or_translate(self._store, text, self._backend, self._lang)
