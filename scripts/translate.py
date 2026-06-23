"""Translation helpers for Notion-facing Russian localization.

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
import logging
import os
import re
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_GEMINI_TRANSLATION_MODEL = "gemini-2.5-flash-lite"
DEFAULT_OPENAI_TRANSLATION_MODEL = "gpt-5-mini"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"

_URL_RE = re.compile(r"https?://[^\s)>\]]+|www\.[^\s)>\]]+")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}")
_CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё]{2,}")

_PROSE_FIELD_HINTS = (
    "prose",
    "description",
    "summary",
    "audit",
    "contact_info",
    ".info",
    "note",
    "overview",
    "position",
    "activities",
    "target_market",
    "problem",
    "technologies",
    "features",
    "data_need",
    "data_needs",
    "challenges",
    "dynamics",
    "forecast",
    "interesting",
    "entry_point",
    "pitch",
    "next_step",
    "outreach",
    "hook",
    "claim",
    "reality",
    "risk",
    "role",
    "gap",
    "money_moment_need",
    "sales_opportunity",
    "contact_angle",
)

_STRUCTURAL_FIELD_HINTS = (
    "url",
    "email",
    "phone",
    "linkedin",
    "facebook",
    "instagram",
    "website",
    "domain",
    "id",
    "status",
    "segment",
    "country",
    "stage",
    "amount",
    "date",
    "year",
    "size",
    "type",
    "name",
    "company",
    "round",
    "investor",
    "source",
    "category",
    "use_case",
    "funding",
)


class TranslationError(RuntimeError):
    """Raised when Notion localization cannot produce a safe Russian value."""


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


def _field_has_hint(field: str, hints: tuple[str, ...]) -> bool:
    tokens = [t for t in re.split(r"[^a-z0-9_]+", field.lower()) if t]
    exact_only = {"company", "name", "info", "id", "url", "email", "phone", "type"}
    for hint in hints:
        normalized_hint = hint.strip(".")
        if normalized_hint in tokens:
            return True
        if normalized_hint in exact_only:
            continue
        if any(
            token.startswith(f"{normalized_hint}_") or token.endswith(f"_{normalized_hint}")
            for token in tokens
        ):
            return True
    return False


def _urls(text: str) -> list[str]:
    return _URL_RE.findall(text)


def _looks_structural(text: str, field: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if _field_has_hint(field, _STRUCTURAL_FIELD_HINTS):
        return True
    if _URL_RE.fullmatch(stripped) or _EMAIL_RE.fullmatch(stripped):
        return True
    without_urls = _URL_RE.sub("", stripped)
    without_emails = _EMAIL_RE.sub("", without_urls)
    letters = _LATIN_RE.findall(without_emails) + _CYRILLIC_RE.findall(without_emails)
    if not letters:
        return True
    words = _WORD_RE.findall(without_emails)
    if len(words) <= 1 and len(without_emails) <= 24:
        return True
    return False


def _is_already_russian(text: str) -> bool:
    cyrillic = len(_CYRILLIC_RE.findall(text))
    if cyrillic < 2:
        return False
    latin = len(_LATIN_RE.findall(text))
    return cyrillic >= max(2, int((cyrillic + latin) * 0.2))


def should_localize_text(text: str | None, *, field: str) -> bool:
    """Return True when text is likely English presentation prose."""
    if text is None:
        return False
    if not isinstance(text, str):
        return False
    if _is_already_russian(text):
        return False
    if _looks_structural(text, field):
        return False

    prose_field = _field_has_hint(field, _PROSE_FIELD_HINTS)
    latin = len(_LATIN_RE.findall(text))
    cyrillic = len(_CYRILLIC_RE.findall(text))
    words = _WORD_RE.findall(_URL_RE.sub("", _EMAIL_RE.sub("", text)))
    if latin <= cyrillic:
        return False
    if prose_field:
        return len(words) >= 2
    return len(words) >= 5


class GeminiTranslationBackend:
    """Synchronous Gemini translation backend using the existing REST surface."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_GEMINI_TRANSLATION_MODEL,
        http_client: httpx.Client | Any | None = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.model = model
        self.http_client = http_client
        self.timeout = timeout

    def __call__(self, text: str) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": _translation_system_prompt()}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0.1},
        }
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        url = GEMINI_ENDPOINT.format(model=self.model)
        response = self._post(url, payload, headers)
        data = response.json()
        translated = (
            data.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        if not translated:
            raise TranslationError("Gemini response did not include translated text")
        return str(translated).strip()

    def _post(self, url: str, payload: dict[str, Any], headers: dict[str, str]):
        return _post_with_retries(
            url,
            payload,
            headers,
            timeout=self.timeout,
            http_client=self.http_client,
        )


class OpenAITranslationBackend:
    """Optional OpenAI fallback backend."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_OPENAI_TRANSLATION_MODEL,
        http_client: httpx.Client | Any | None = None,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.model = model
        self.http_client = http_client
        self.timeout = timeout

    def __call__(self, text: str) -> str:
        payload = {
            "model": self.model,
            "input": [
                {"role": "system", "content": _translation_system_prompt()},
                {"role": "user", "content": text},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = self._post(OPENAI_RESPONSES_ENDPOINT, payload, headers)
        data = response.json()
        translated = _extract_openai_text(data)
        if not translated:
            raise TranslationError("OpenAI response did not include translated text")
        return translated.strip()

    def _post(self, url: str, payload: dict[str, Any], headers: dict[str, str]):
        return _post_with_retries(
            url,
            payload,
            headers,
            timeout=self.timeout,
            http_client=self.http_client,
        )


class NotionTextLocalizer:
    """Localize Notion presentation prose in memory only."""

    def __init__(
        self,
        backend: Callable[[str], str],
        *,
        fallback_backend: Callable[[str], str] | None = None,
        on_failure: str = "fail_sync",
    ):
        if on_failure not in {"fail_sync", "write_original_with_warning", "skip_field"}:
            raise ValueError(f"unsupported translation failure policy: {on_failure}")
        self.backend = backend
        self.fallback_backend = fallback_backend
        self.on_failure = on_failure

    def translate(self, text: str | None) -> str | None:
        """Compatibility alias for older injection points."""
        return self.localize_text(text, field="prose")

    def localize_text(self, text: str | None, *, field: str) -> str | None:
        if text is None or text == "":
            return text
        if not isinstance(text, str):
            return text
        if not should_localize_text(text, field=field):
            return text

        try:
            return self._translate_checked(text, self.backend)
        except Exception as primary_exc:  # noqa: BLE001
            if self.fallback_backend is not None:
                try:
                    return self._translate_checked(text, self.fallback_backend)
                except Exception as fallback_exc:  # noqa: BLE001
                    return self._handle_failure(text, field, fallback_exc)
            return self._handle_failure(text, field, primary_exc)

    def localize_mapping(self, value: Mapping[str, Any], *, field_prefix: str) -> dict:
        result: dict[str, Any] = {}
        for key, item in value.items():
            field = f"{field_prefix}.{key}"
            result[key] = self._localize_value(item, field=field)
        return result

    def localize_list(self, value: list, *, field_prefix: str) -> list:
        return [
            self._localize_value(item, field=f"{field_prefix}.{idx}")
            for idx, item in enumerate(value)
        ]

    def _localize_value(self, value: Any, *, field: str) -> Any:
        if isinstance(value, str):
            return self.localize_text(value, field=field)
        if isinstance(value, Mapping):
            return self.localize_mapping(value, field_prefix=field)
        if isinstance(value, list):
            return self.localize_list(value, field_prefix=field)
        return value

    def _translate_checked(self, text: str, backend: Callable[[str], str]) -> str:
        translated = backend(text)
        if not isinstance(translated, str) or not translated.strip():
            raise TranslationError("translation backend returned empty output")
        translated = translated.strip()
        original_urls = _urls(text)
        translated_urls = _urls(translated)
        if original_urls != translated_urls:
            raise TranslationError("translation backend changed URLs")
        return translated

    def _handle_failure(self, text: str, field: str, exc: Exception) -> str | None:
        if self.on_failure == "write_original_with_warning":
            logger.warning("Notion localization failed for %s; writing original: %s", field, exc)
            return text
        if self.on_failure == "skip_field":
            logger.warning("Notion localization failed for %s; skipping field: %s", field, exc)
            return None
        raise TranslationError(f"Notion localization failed for {field}: {exc}") from exc


def build_notion_localizer_from_env(
    env: Mapping[str, str] | None = None,
    *,
    http_client: httpx.Client | Any | None = None,
) -> NotionTextLocalizer | None:
    """Create Notion localizer when KVETIO_NOTION_LOCALIZATION enables it."""
    env = env or os.environ
    mode = str(env.get("KVETIO_NOTION_LOCALIZATION", "")).strip().lower()
    if mode not in {"1", "true", "yes", "ru", "russian", "hybrid"}:
        return None

    provider = str(env.get("KVETIO_TRANSLATION_PROVIDER", "gemini")).strip().lower()
    model = str(env.get("KVETIO_TRANSLATION_MODEL", DEFAULT_GEMINI_TRANSLATION_MODEL)).strip()
    backend: Callable[[str], str]
    if provider == "gemini":
        api_key = str(env.get("GEMINI_API_KEY", "")).strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is required for Notion localization")
        backend = GeminiTranslationBackend(api_key=api_key, model=model, http_client=http_client)
    else:
        raise RuntimeError(f"unsupported KVETIO_TRANSLATION_PROVIDER: {provider}")

    fallback_backend = None
    fallback_provider = str(env.get("KVETIO_TRANSLATION_FALLBACK_PROVIDER", "")).strip().lower()
    if fallback_provider == "openai":
        fallback_model = str(
            env.get("KVETIO_TRANSLATION_FALLBACK_MODEL", DEFAULT_OPENAI_TRANSLATION_MODEL)
        ).strip()
        openai_key = str(env.get("OPENAI_API_KEY", "")).strip()
        if not openai_key:
            raise RuntimeError("OPENAI_API_KEY is required for OpenAI translation fallback")
        fallback_backend = OpenAITranslationBackend(
            api_key=openai_key,
            model=fallback_model,
            http_client=http_client,
        )
    elif fallback_provider:
        raise RuntimeError(
            f"unsupported KVETIO_TRANSLATION_FALLBACK_PROVIDER: {fallback_provider}"
        )

    return NotionTextLocalizer(
        backend,
        fallback_backend=fallback_backend,
        on_failure=str(env.get("KVETIO_TRANSLATION_ON_FAILURE", "fail_sync")).strip()
        or "fail_sync",
    )


def _translation_system_prompt() -> str:
    return (
        "Translate the user's text into natural Russian for a B2B data-services "
        "research and sales user. Return only the translated text. Preserve markdown "
        "structure, headings, bullets, URLs, emails, numbers, dates, metrics, company "
        "names, person names, product names, model names, dataset names, and evidence "
        "references exactly unless a conventional Russian spelling exists. Do not add "
        "facts, warnings, commentary, or explanations."
    )


def _post_with_retries(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout: float,
    http_client: httpx.Client | Any | None = None,
    attempts: int = 3,
):
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            if http_client is not None:
                response = http_client.post(url, json=payload, headers=headers, timeout=timeout)
            else:
                with httpx.Client(timeout=timeout) as client:
                    response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = exc.response.status_code
            if status not in {429, 500, 502, 503, 504} or attempt == attempts - 1:
                raise
        except httpx.TransportError as exc:
            last_exc = exc
            if attempt == attempts - 1:
                raise
        time.sleep(0.5 * (2 ** attempt))
    if last_exc:
        raise last_exc
    raise TranslationError("translation request failed without an exception")


def _extract_openai_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    parts: list[str] = []
    for item in data.get("output", []) or []:
        for content in item.get("content", []) or []:
            if isinstance(content.get("text"), str):
                parts.append(content["text"])
    return "".join(parts)
