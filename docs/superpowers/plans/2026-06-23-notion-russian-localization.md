# Notion Russian Localization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Notion sync write natural Russian presentation text by default, while new agent output is generated in Russian and legacy English prose is translated on the fly through Gemini without storing translations in Supabase.

**Architecture:** Add a focused `scripts/notion_localization.py` boundary that owns language detection, prose-field whitelisting, Gemini translation, and failure policy. Wire that boundary into `notion_sync.py` and `notion_render.py` before Notion payloads are built, so source DB rows remain unchanged. Update agent prompts so future `analysis_records`, `dossiers`, and sales-brief fields are written in Russian at generation time.

**Tech Stack:** Python 3.11, `httpx`, existing Gemini REST endpoint pattern from `bot/intent_agent.py`, pytest, existing fake Notion/DB gateways.

---

## File Structure

- Create: `scripts/notion_localization.py`
  - Owns `NotionTextLocalizer`, `GeminiTranslationBackend`, `LocalizationError`, config parsing, language heuristics, field whitelists, and convenience helpers for rows/mappings/lists.
- Create: `tests/test_notion_localization.py`
  - Unit tests for language detection, skip rules, Gemini request/response parsing, and failure policies.
- Modify: `scripts/notion_sync.py`
  - Replace sync-time `translator` behavior with `localizer`.
  - Localize whitelisted rich-text property values before `to_notion_property`.
  - Localize legacy dossier body path.
  - Build production localizer from env in CLI.
- Modify: `scripts/notion_render.py`
  - Localize source-level render inputs before building Notion block dictionaries.
- Modify: `bot/gateway.py`
  - Build the same production localizer for `/notion_sync` and internal cron sync.
- Modify: `scripts/notion_profile.py`
  - Stop translating `description` in profile builder; Notion sync localizes it at payload time.
- Modify: `tests/test_notion_sync.py`, `tests/test_notion_render.py`, `tests/test_notion_profile.py`
  - Update old translator tests to localizer tests.
- Modify: `tests/test_pipeline_prompts.py`
  - Add prompt contract tests that require Russian presentation output instructions.
- Modify: `agents/prompts/analysis_task.md`, `agents/prompts/analysis_section_task.md`, `agents/prompts/analysis_audit_task.md`, `agents/prompts/conclusions_task.md`
  - Add clear Russian-output contract.
- Modify: `ARCHITECTURE.md`
  - Replace the cached `translations` runtime description with the new Notion-only localization path.

---

### Task 1: Prompt Language Contract

**Files:**
- Modify: `tests/test_pipeline_prompts.py`
- Modify: `agents/prompts/analysis_task.md`
- Modify: `agents/prompts/analysis_section_task.md`
- Modify: `agents/prompts/analysis_audit_task.md`
- Modify: `agents/prompts/conclusions_task.md`

- [ ] **Step 1: Add failing prompt contract tests**

Append this test to `tests/test_pipeline_prompts.py`:

```python
def test_analysis_and_conclusion_prompts_require_russian_presentation_text() -> None:
    required_files = [
        "analysis_task.md",
        "analysis_section_task.md",
        "analysis_audit_task.md",
        "conclusions_task.md",
    ]
    for name in required_files:
        text = _read(name).lower()
        assert "человекочитаемые" in text, f"{name} must define presentation text language"
        assert "естественном русском" in text, f"{name} must require natural Russian"
        assert "url" in text, f"{name} must preserve source URLs"
        assert "названия" in text, f"{name} must preserve proper names"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_pipeline_prompts.py::test_analysis_and_conclusion_prompts_require_russian_presentation_text -v
```

Expected: FAIL because at least one prompt does not yet contain the exact Russian-output contract.

- [ ] **Step 3: Add the language contract to `analysis_task.md`**

Insert after the role/next-stage intro in `agents/prompts/analysis_task.md`:

```markdown
## Язык результата

Все человекочитаемые аналитические поля, которые будут показаны пользователю
или попадут в Notion, пиши на естественном русском языке. Не делай машинную
кальку с английского: формулируй как деловую аналитическую заметку для
русскоязычного sales/research пользователя.

Сохраняй без перевода URL, email, телефоны, числа, даты, суммы, funding stages,
названия компаний, продуктов, людей, инвесторов, моделей и датасетов. Если
источник содержит важную английскую формулировку, передай смысл по-русски и
оставь URL источника.
```

- [ ] **Step 4: Add the language contract to `analysis_section_task.md`**

Insert after the role section in `agents/prompts/analysis_section_task.md`:

```markdown
## Язык результата

Поля `facts`, краткие выводы секции и любые человекочитаемые пояснения пиши на
естественном русском языке. Это presentation-текст для Notion и внутреннего
анализа, поэтому он должен быть понятным человеку, а не выглядеть как дословный
перевод.

Не переводи URL, email, телефоны, имена людей, названия компаний, продуктов,
моделей, датасетов, инвесторов, funding stages, суммы, даты и технические
идентификаторы. Сохраняй ссылки на источники рядом с фактами.
```

- [ ] **Step 5: Add the language contract to `analysis_audit_task.md`**

Insert after the role section in `agents/prompts/analysis_audit_task.md`:

```markdown
## Язык результата

Все человекочитаемые выводы аудита пиши на естественном русском языке для
русскоязычного sales/research пользователя. Сохраняй факты, числа, даты, суммы,
URL, названия компаний, продуктов, людей, моделей и датасетов без искажений.
Не добавляй выводы, которые не подтверждаются анализом и источниками.
```

- [ ] **Step 6: Add the language contract to `conclusions_task.md`**

Insert before `## Write dossier` in `agents/prompts/conclusions_task.md`:

```markdown
## Язык dossier и sales-brief

Все человекочитаемые поля dossier и sales-brief пиши на естественном русском
языке: `section_summaries`, `summary_md`, `audit_md`, `pain_summary`,
`pitch_angle`, `why_interesting`, `outreach_hook`.

Сохраняй без перевода URL, email, телефоны, числа, даты, суммы, funding stages,
названия компаний, продуктов, людей, инвесторов, моделей и датасетов. Текст
должен звучать как ясная деловая заметка, а не как машинный перевод.
```

- [ ] **Step 7: Run prompt tests**

Run:

```bash
python -m pytest tests/test_pipeline_prompts.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tests/test_pipeline_prompts.py agents/prompts/analysis_task.md agents/prompts/analysis_section_task.md agents/prompts/analysis_audit_task.md agents/prompts/conclusions_task.md
git commit -m "docs(prompts): require Russian presentation output"
```

---

### Task 2: Localizer Core

**Files:**
- Create: `scripts/notion_localization.py`
- Create: `tests/test_notion_localization.py`

- [ ] **Step 1: Add failing tests for heuristics and skip rules**

Create `tests/test_notion_localization.py` with:

```python
from __future__ import annotations

import pytest

import notion_localization as nl


class FakeBackend:
    def __init__(self, translations=None, fail=False):
        self.calls: list[str] = []
        self.translations = translations or {}
        self.fail = fail

    def translate(self, text: str) -> str:
        self.calls.append(text)
        if self.fail:
            raise RuntimeError("backend down")
        return self.translations.get(text, f"RU:{text}")


def test_russian_text_is_not_sent_to_backend():
    backend = FakeBackend()
    localizer = nl.NotionTextLocalizer(backend=backend)

    result = localizer.localize_text(
        "Компания строит платформу для медицинской разметки.",
        field="companies.description",
    )

    assert result == "Компания строит платформу для медицинской разметки."
    assert backend.calls == []


def test_english_prose_is_translated_for_whitelisted_field():
    backend = FakeBackend({"AI platform for radiology workflows.": "Платформа AI для радиологии."})
    localizer = nl.NotionTextLocalizer(backend=backend)

    result = localizer.localize_text(
        "AI platform for radiology workflows.",
        field="companies.description",
    )

    assert result == "Платформа AI для радиологии."
    assert backend.calls == ["AI platform for radiology workflows."]


@pytest.mark.parametrize(
    "field,value",
    [
        ("companies.website", "https://acme.ai"),
        ("contacts.email", "ceo@acme.ai"),
        ("companies.funding_info", "Series A · $12M"),
        ("companies.status", "dossier_ready"),
        ("companies.potential_data", "Images"),
    ],
)
def test_structural_values_are_not_translated(field, value):
    backend = FakeBackend()
    localizer = nl.NotionTextLocalizer(backend=backend)

    assert localizer.localize_text(value, field=field) == value
    assert backend.calls == []


def test_mapping_values_are_localized_recursively_by_field_prefix():
    backend = FakeBackend({"English summary": "Русское саммари"})
    localizer = nl.NotionTextLocalizer(backend=backend)

    result = localizer.localize_mapping(
        {"intro": "English summary", "url": "https://example.com"},
        field_prefix="dossiers.section_summaries",
    )

    assert result == {"intro": "Русское саммари", "url": "https://example.com"}
    assert backend.calls == ["English summary"]


def test_fail_sync_raises_localization_error_before_write():
    backend = FakeBackend(fail=True)
    localizer = nl.NotionTextLocalizer(backend=backend, on_failure="fail_sync")

    with pytest.raises(nl.LocalizationError):
        localizer.localize_text("English summary", field="dossiers.summary_md")


def test_write_original_with_warning_returns_original(caplog):
    backend = FakeBackend(fail=True)
    localizer = nl.NotionTextLocalizer(
        backend=backend,
        on_failure="write_original_with_warning",
    )

    result = localizer.localize_text("English summary", field="dossiers.summary_md")

    assert result == "English summary"
    assert "Localization failed" in caplog.text


def test_skip_field_returns_none_on_failure():
    backend = FakeBackend(fail=True)
    localizer = nl.NotionTextLocalizer(backend=backend, on_failure="skip_field")

    assert localizer.localize_text("English summary", field="dossiers.summary_md") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest tests/test_notion_localization.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'notion_localization'`.

- [ ] **Step 3: Implement `scripts/notion_localization.py` core**

Create `scripts/notion_localization.py`:

```python
"""Notion-only Russian localization.

This module localizes presentation prose immediately before Notion writes.
It never persists translated text back to Supabase.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from typing import Protocol

logger = logging.getLogger(__name__)


class LocalizationError(RuntimeError):
    """Raised when localization is required but cannot be completed."""


class TranslationBackend(Protocol):
    def translate(self, text: str) -> str:
        """Return Russian text for English source prose."""


PROSE_FIELDS = {
    "companies.description",
    "contacts.info",
    "dossiers.summary_md",
    "dossiers.audit_md",
    "dossiers.section_summaries",
    "dossiers.pain_summary",
    "dossiers.pitch_angle",
    "dossiers.why_interesting",
    "dossiers.outreach_hook",
    "research_records.summary",
}

STRUCTURAL_FIELD_SUFFIXES = (
    ".website",
    ".linkedin_url",
    ".facebook_url",
    ".instagram_url",
    ".email",
    ".phone",
    ".phone_number",
    ".status",
    ".icp_segment",
    ".potential_data",
    ".funding_info",
    ".company_size",
    ".team_size_estimate",
    ".company_page_ids",
    ".notion_page_id",
)

URL_OR_EMAIL_RE = re.compile(r"^(https?://|www\.|[^@\s]+@[^@\s]+\.[^@\s]+$)", re.I)
CYRILLIC_RE = re.compile(r"[А-Яа-яЁё]")
LATIN_RE = re.compile(r"[A-Za-z]")


def is_structural_field(field: str) -> bool:
    return field.endswith(STRUCTURAL_FIELD_SUFFIXES)


def is_whitelisted_prose_field(field: str) -> bool:
    if field in PROSE_FIELDS:
        return True
    return field.startswith("analysis_records.facts.") or field.startswith(
        "dossiers.section_summaries."
    )


def looks_structural_value(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return True
    if URL_OR_EMAIL_RE.match(stripped):
        return True
    if re.fullmatch(r"[\w .:/@+()#,&$%·\-–—]+", stripped) and len(stripped.split()) <= 4:
        return True
    return False


def looks_russian(text: str) -> bool:
    cyr = len(CYRILLIC_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    return cyr >= 8 and cyr >= latin * 0.35


def should_localize(text: str | None, *, field: str) -> bool:
    if text is None:
        return False
    if not isinstance(text, str):
        return False
    if not text.strip():
        return False
    if is_structural_field(field):
        return False
    if not is_whitelisted_prose_field(field):
        return False
    if looks_structural_value(text):
        return False
    if looks_russian(text):
        return False
    return bool(LATIN_RE.search(text))


@dataclass
class NotionTextLocalizer:
    backend: TranslationBackend | None = None
    on_failure: str = "fail_sync"

    def localize_text(self, text: str | None, *, field: str) -> str | None:
        if not should_localize(text, field=field):
            return text
        if self.backend is None:
            return self._handle_failure(text, field, RuntimeError("translation backend is not configured"))
        try:
            translated = self.backend.translate(text)
        except Exception as exc:  # noqa: BLE001
            return self._handle_failure(text, field, exc)
        if not translated or not str(translated).strip():
            return self._handle_failure(text, field, RuntimeError("empty translation response"))
        return str(translated)

    def localize_mapping(self, value: dict, *, field_prefix: str) -> dict:
        result = {}
        for key, item in value.items():
            field = f"{field_prefix}.{key}"
            if isinstance(item, str):
                result[key] = self.localize_text(item, field=field)
            elif isinstance(item, dict):
                result[key] = self.localize_mapping(item, field_prefix=field)
            elif isinstance(item, list):
                result[key] = self.localize_list(item, field_prefix=field)
            else:
                result[key] = item
        return result

    def localize_list(self, value: list, *, field_prefix: str) -> list:
        result = []
        for idx, item in enumerate(value):
            field = f"{field_prefix}.{idx}"
            if isinstance(item, str):
                result.append(self.localize_text(item, field=field))
            elif isinstance(item, dict):
                result.append(self.localize_mapping(item, field_prefix=field))
            elif isinstance(item, list):
                result.append(self.localize_list(item, field_prefix=field))
            else:
                result.append(item)
        return result

    def _handle_failure(self, text: str | None, field: str, exc: Exception) -> str | None:
        message = f"Localization failed for {field}: {exc}"
        if self.on_failure == "write_original_with_warning":
            logger.warning("%s", message)
            return text
        if self.on_failure == "skip_field":
            logger.warning("%s; skipping field", message)
            return None
        raise LocalizationError(message) from exc


def localization_enabled(env: dict | None = None) -> bool:
    env = env or os.environ
    return env.get("KVETIO_NOTION_LOCALIZATION", "").strip().lower() in {"hybrid", "true", "1"}
```

- [ ] **Step 4: Run localizer tests**

Run:

```bash
python -m pytest tests/test_notion_localization.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/notion_localization.py tests/test_notion_localization.py
git commit -m "feat(notion): add Russian localization guard"
```

---

### Task 3: Gemini Translation Backend

**Files:**
- Modify: `scripts/notion_localization.py`
- Modify: `tests/test_notion_localization.py`

- [ ] **Step 1: Add failing Gemini backend tests**

Append to `tests/test_notion_localization.py`:

```python
class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def post(self, url, *, json, headers, timeout):
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        return FakeResponse(self.payload)


def test_gemini_backend_posts_translation_request():
    client = FakeHttpClient({
        "candidates": [{"content": {"parts": [{"text": "Русский текст"}]}}]
    })
    backend = nl.GeminiTranslationBackend(
        api_key="key",
        model="gemini-2.5-flash-lite",
        http_client=client,
    )

    result = backend.translate("English text")

    assert result == "Русский текст"
    call = client.calls[0]
    assert call["url"].endswith("/models/gemini-2.5-flash-lite:generateContent")
    assert call["headers"]["x-goog-api-key"] == "key"
    assert call["json"]["contents"][0]["parts"][0]["text"] == "English text"
    assert "естественный русский" in call["json"]["systemInstruction"]["parts"][0]["text"]


def test_gemini_backend_rejects_empty_candidate():
    client = FakeHttpClient({"candidates": [{"content": {"parts": [{"text": ""}]}}]})
    backend = nl.GeminiTranslationBackend(api_key="key", http_client=client)

    with pytest.raises(nl.LocalizationError):
        backend.translate("English text")


def test_make_notion_localizer_returns_none_when_disabled(monkeypatch):
    monkeypatch.delenv("KVETIO_NOTION_LOCALIZATION", raising=False)

    assert nl.make_notion_localizer() is None


def test_make_notion_localizer_uses_gemini_when_enabled(monkeypatch):
    monkeypatch.setenv("KVETIO_NOTION_LOCALIZATION", "hybrid")
    monkeypatch.setenv("KVETIO_TRANSLATION_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "key")

    localizer = nl.make_notion_localizer()

    assert isinstance(localizer, nl.NotionTextLocalizer)
    assert isinstance(localizer.backend, nl.GeminiTranslationBackend)
```

- [ ] **Step 2: Run Gemini tests to verify they fail**

Run:

```bash
python -m pytest tests/test_notion_localization.py -k "gemini or make_notion" -v
```

Expected: FAIL because `GeminiTranslationBackend` and `make_notion_localizer` do not exist.

- [ ] **Step 3: Implement Gemini backend and factory**

Append to `scripts/notion_localization.py`:

```python
import httpx


DEFAULT_GEMINI_TRANSLATION_MODEL = "gemini-2.5-flash-lite"
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

TRANSLATION_SYSTEM_PROMPT = """Ты профессиональный редактор-переводчик для Kvetio.

Переведи входной текст на естественный русский язык для деловой Notion-карточки.
Сохраняй факты, числа, даты, суммы, URL, markdown-структуру, списки и заголовки.
Не переводи названия компаний, продуктов, людей, инвесторов, моделей и датасетов,
если у них нет общеупотребимого русского написания.
Не добавляй новых выводов, предупреждений, пояснений или источников.
Верни только готовый русский текст без комментариев.
Контекст: Kvetio продаёт data services, датасеты и разметку для AI-моделей.
"""


class GeminiTranslationBackend:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_GEMINI_TRANSLATION_MODEL,
        http_client=None,
        timeout: float = 30,
    ):
        if not api_key:
            raise LocalizationError("GEMINI_API_KEY is required for Gemini translation")
        self.api_key = api_key
        self.model = model
        self.http_client = http_client
        self.timeout = timeout

    def translate(self, text: str) -> str:
        payload = {
            "systemInstruction": {"parts": [{"text": TRANSLATION_SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": text}]}],
            "generationConfig": {"temperature": 0.1},
        }
        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        url = GEMINI_ENDPOINT.format(model=self.model)
        if self.http_client is not None:
            response = self.http_client.post(
                url,
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self._extract_text(response.json())
        with httpx.Client(timeout=self.timeout) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
            return self._extract_text(response.json())

    def _extract_text(self, response: dict) -> str:
        text = (
            response.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        if not text or not str(text).strip():
            raise LocalizationError("Gemini response did not include translation text")
        return str(text).strip()


def make_notion_localizer(env: dict | None = None) -> NotionTextLocalizer | None:
    env = env or os.environ
    if not localization_enabled(env):
        return None
    provider = env.get("KVETIO_TRANSLATION_PROVIDER", "gemini").strip().lower()
    on_failure = env.get("KVETIO_TRANSLATION_ON_FAILURE", "fail_sync").strip() or "fail_sync"
    if provider != "gemini":
        raise LocalizationError(f"unsupported translation provider: {provider}")
    model = env.get("KVETIO_TRANSLATION_MODEL", DEFAULT_GEMINI_TRANSLATION_MODEL).strip()
    backend = GeminiTranslationBackend(
        api_key=env.get("GEMINI_API_KEY", "").strip(),
        model=model or DEFAULT_GEMINI_TRANSLATION_MODEL,
    )
    return NotionTextLocalizer(backend=backend, on_failure=on_failure)
```

- [ ] **Step 4: Run localizer tests**

Run:

```bash
python -m pytest tests/test_notion_localization.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/notion_localization.py tests/test_notion_localization.py
git commit -m "feat(notion): add Gemini localization backend"
```

---

### Task 4: Localize Notion Forward Property Payloads

**Files:**
- Modify: `scripts/notion_profile.py`
- Modify: `scripts/notion_sync.py`
- Modify: `tests/test_notion_profile.py`
- Modify: `tests/test_notion_sync.py`

- [ ] **Step 1: Add failing sync-forward localization test**

Append to `tests/test_notion_sync.py`:

```python
def test_sync_forward_localizes_whitelisted_rich_text_before_notion_write():
    class Localizer:
        def __init__(self):
            self.calls = []

        def localize_text(self, text, *, field):
            self.calls.append((field, text))
            if field == "companies.description":
                return "Русское описание"
            return text

    mapping = {
        "companies": {
            "notion_database_id_env": "NOTION_COMPANIES_DB_ID",
            "db_table": "companies",
            "db_key": "domain",
            "db_status_filter": ["relevant"],
            "fields": [
                {"db_column": "name", "notion_property": "Company Name", "notion_type": "title", "direction": "forward"},
                {"db_column": "description", "notion_property": "AI Summary", "notion_type": "rich_text", "direction": "forward"},
                {"db_column": "funding_info", "notion_property": "Funding Info", "notion_type": "rich_text", "direction": "forward"},
            ],
        }
    }
    rows = [{
        "domain": "acme.com",
        "name": "Acme",
        "description": "AI platform for radiology.",
        "funding_info": "Series A · $12M",
        "status": "relevant",
        "notion_page_id": None,
    }]
    notion = FakeNotion()
    db = FakeDb(rows)
    localizer = Localizer()

    sync = ns.NotionSync(
        notion=notion,
        db=db,
        mapping=mapping,
        env={"NOTION_COMPANIES_DB_ID": "DBID"},
        localizer=localizer,
    )
    result = sync.sync_forward("companies")

    assert result["created"] == 1
    page_id = db.tables["companies"][0]["notion_page_id"]
    props = notion.pages[page_id]["properties"]
    assert props["AI Summary"] == {"rich_text": [{"text": {"content": "Русское описание"}}]}
    assert props["Funding Info"] == {"rich_text": [{"text": {"content": "Series A · $12M"}}]}
    assert ("companies.description", "AI platform for radiology.") in localizer.calls
    assert ("companies.funding_info", "Series A · $12M") not in localizer.calls
```

- [ ] **Step 2: Update profile-builder tests away from translator behavior**

Replace `test_profile_translator_translates_description` in `tests/test_notion_profile.py` with:

```python
def test_profile_builder_keeps_description_source_text_for_sync_localization():
    class StubTranslator:
        def translate(self, text: str) -> str:
            return f"RU:{text}"

    profile = np_mod.build_company_notion_profile(
        _COMPANY, None, {}, _POTENTIAL_CFG, translator=StubTranslator()
    )
    assert profile["description"] == "AI-powered radiology platform."
```

Keep `test_profile_translator_does_not_translate_select_fields` or rename it to:

```python
def test_profile_builder_does_not_localize_structural_fields():
    profile = np_mod.build_company_notion_profile(
        _COMPANY, None, {}, _POTENTIAL_CFG
    )
    assert profile["icp_segment"] == "medical-imaging"
    assert profile["status"] == "relevant"
    assert profile["hq_country"] == "US"
```

- [ ] **Step 3: Run targeted tests to verify failure**

Run:

```bash
python -m pytest tests/test_notion_sync.py::test_sync_forward_localizes_whitelisted_rich_text_before_notion_write tests/test_notion_profile.py -v
```

Expected: FAIL because `NotionSync.__init__` does not accept `localizer`, and profile builder still translates `description`.

- [ ] **Step 4: Remove source-time translation from `notion_profile.py`**

In `scripts/notion_profile.py`, replace:

```python
    description = company.get("description")
    if translator and description:
        description = translator.translate(description)
```

with:

```python
    description = company.get("description")
```

Leave the `translator=None` parameter temporarily for backwards-compatible call signatures. Do not call it.

- [ ] **Step 5: Add localizer support to `NotionSync`**

In `scripts/notion_sync.py`, add import near the top:

```python
from notion_localization import make_notion_localizer
```

Replace `NotionSync.__init__` with:

```python
class NotionSync:
    def __init__(self, notion, db, mapping=None, env=None, translator=None, localizer=None):
        self.notion = notion
        self.db = db
        self.mapping = mapping if mapping is not None else load_mapping()
        self.env = env if env is not None else os.environ
        self.translator = translator  # legacy; do not use for new localization path
        self.localizer = localizer
```

Add these methods inside `NotionSync`:

```python
    def _localize_forward_value(self, entity: str, field: dict, value):
        if self.localizer is None:
            return value
        notion_type = field["notion_type"]
        if notion_type != "rich_text":
            return value
        field_name = f"{entity}.{field['db_column']}"
        return self.localizer.localize_text(value, field=field_name)

    def _notion_property_for_forward_field(self, entity: str, field: dict, row: dict) -> dict:
        value = row.get(field["db_column"])
        value = self._localize_forward_value(entity, field, value)
        return to_notion_property(field["notion_type"], value)
```

In `sync_forward`, replace the `props = { ... }` comprehension with:

```python
                props = {
                    f["notion_property"]: self._notion_property_for_forward_field(entity, f, row)
                    for f in fields
                }
```

- [ ] **Step 6: Wire CLI localizer factory**

In `scripts/notion_sync.py`, replace:

```python
    sync = NotionSync(notion=_make_notion(), db=_make_db(), mapping=mapping)
```

with:

```python
    sync = NotionSync(
        notion=_make_notion(),
        db=_make_db(),
        mapping=mapping,
        localizer=make_notion_localizer(),
    )
```

- [ ] **Step 7: Run targeted tests**

Run:

```bash
python -m pytest tests/test_notion_sync.py::test_sync_forward_localizes_whitelisted_rich_text_before_notion_write tests/test_notion_profile.py -v
```

Expected: PASS.

- [ ] **Step 8: Run broader Notion sync/profile tests**

Run:

```bash
python -m pytest tests/test_notion_sync.py tests/test_notion_profile.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add scripts/notion_profile.py scripts/notion_sync.py tests/test_notion_profile.py tests/test_notion_sync.py
git commit -m "feat(notion): localize forward properties at sync time"
```

---

### Task 5: Localize Legacy Dossier Sync Path

**Files:**
- Modify: `scripts/notion_sync.py`
- Modify: `tests/test_notion_sync.py`

- [ ] **Step 1: Replace old translator dossier test with localizer behavior**

Replace `test_sync_dossiers_translates_prose_fields` in `tests/test_notion_sync.py` with:

```python
def test_sync_dossiers_localizes_prose_fields():
    class Localizer:
        def __init__(self):
            self.calls = []

        def localize_text(self, text, *, field):
            self.calls.append((field, text))
            translations = {
                "English summary": "Русское саммари",
                "English audit": "Русский аудит",
                "Intro section": "Вступительный раздел",
            }
            return translations.get(text, text)

        def localize_mapping(self, value, *, field_prefix):
            return {
                key: self.localize_text(item, field=f"{field_prefix}.{key}")
                for key, item in value.items()
            }

    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {}, "children": []}
    db = FakeDb([])
    db.tables["companies"] = [{"id": "cid", "domain": "acme.com", "notion_page_id": "page-1"}]
    db.tables["dossiers"] = [{
        "company_id": "cid",
        "summary_md": "English summary",
        "audit_md": "English audit",
        "section_summaries": {"intro": "Intro section"},
    }]
    localizer = Localizer()

    sync = ns.NotionSync(
        notion=notion,
        db=db,
        mapping=COMPANIES_MAPPING,
        env={"NOTION_COMPANIES_DB_ID": "DBID"},
        localizer=localizer,
    )
    result = sync.sync_dossiers()

    assert result["updated"] == 1
    assert ("dossiers.summary_md", "English summary") in localizer.calls
    assert ("dossiers.audit_md", "English audit") in localizer.calls
    assert ("dossiers.section_summaries.intro", "Intro section") in localizer.calls
    all_text = [
        block["paragraph"]["rich_text"][0]["text"]["content"]
        for block in notion.pages["page-1"]["children"]
        if block["type"] == "paragraph"
    ]
    assert any("Русское саммари" in text for text in all_text)
    assert any("Вступительный раздел" in text for text in all_text)
    assert any("Русский аудит" in text for text in all_text)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_notion_sync.py::test_sync_dossiers_localizes_prose_fields -v
```

Expected: FAIL because `sync_dossiers` still uses `self.translator`.

- [ ] **Step 3: Update `sync_dossiers` to use localizer**

In `scripts/notion_sync.py`, replace the block:

```python
                if self.translator is not None:
                    d = dict(d)
                    d["summary_md"] = self.translator.translate(d.get("summary_md"))
                    d["audit_md"] = self.translator.translate(d.get("audit_md"))
                    if isinstance(d.get("section_summaries"), dict):
                        d["section_summaries"] = {
                            k: self.translator.translate(v)
                            for k, v in d["section_summaries"].items()
                        }
```

with:

```python
                if self.localizer is not None:
                    d = dict(d)
                    d["summary_md"] = self.localizer.localize_text(
                        d.get("summary_md"),
                        field="dossiers.summary_md",
                    )
                    d["audit_md"] = self.localizer.localize_text(
                        d.get("audit_md"),
                        field="dossiers.audit_md",
                    )
                    if isinstance(d.get("section_summaries"), dict):
                        d["section_summaries"] = self.localizer.localize_mapping(
                            d["section_summaries"],
                            field_prefix="dossiers.section_summaries",
                        )
```

- [ ] **Step 4: Run dossier tests**

Run:

```bash
python -m pytest tests/test_notion_sync.py -k "dossier or localizes" -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/notion_sync.py tests/test_notion_sync.py
git commit -m "feat(notion): localize legacy dossier body sync"
```

---

### Task 6: Localize Modern Notion Renderer Inputs

**Files:**
- Modify: `scripts/notion_render.py`
- Modify: `tests/test_notion_render.py`

- [ ] **Step 1: Replace render translator test with localizer test**

Replace `test_render_and_write_body_translates_via_sync_translator` in `tests/test_notion_render.py` with:

```python
def test_render_and_write_body_localizes_source_inputs_before_rendering():
    class Localizer:
        def __init__(self):
            self.calls = []

        def localize_text(self, text, *, field):
            self.calls.append((field, text))
            translations = {
                "Builds vision models": "Создаёт модели компьютерного зрения",
                "English summary prose": "Русское резюме",
                "English audit prose": "Русский аудит",
                "Solid company": "Сильная компания",
                "Raised $30M led by a16z": "Привлекла $30M под лидерством a16z",
                "CEO, tier 1 — data partnerships": "CEO, tier 1 — партнёрства по данным",
            }
            return translations.get(text, text)

        def localize_mapping(self, value, *, field_prefix):
            result = {}
            for key, item in value.items():
                if isinstance(item, str):
                    result[key] = self.localize_text(item, field=f"{field_prefix}.{key}")
                elif isinstance(item, list):
                    result[key] = self.localize_list(item, field_prefix=f"{field_prefix}.{key}")
                elif isinstance(item, dict):
                    result[key] = self.localize_mapping(item, field_prefix=f"{field_prefix}.{key}")
                else:
                    result[key] = item
            return result

        def localize_list(self, value, *, field_prefix):
            result = []
            for idx, item in enumerate(value):
                if isinstance(item, str):
                    result.append(self.localize_text(item, field=f"{field_prefix}.{idx}"))
                elif isinstance(item, dict):
                    result.append(self.localize_mapping(item, field_prefix=f"{field_prefix}.{idx}"))
                else:
                    result.append(item)
            return result

    dossier_with_prose = {
        "company_id": _COMPANY["id"],
        "product_category": "Computer Vision",
        "ai_use_case": "Object detection",
        "funding_stage": "Series B",
        "summary_md": "English summary prose",
        "audit_md": "English audit prose",
    }
    analysis = [{
        "section": "audit",
        "facts": {"overview": "Solid company"},
    }]
    contacts = [{**_CONTACTS[0], "info": "CEO, tier 1 — data partnerships"}]
    news = [{**_NEWS[0], "summary": "Raised $30M led by a16z"}]
    db = _FakeDbForRender(
        {**_COMPANY, "description": "Builds vision models"},
        dossier_with_prose,
        analysis,
        contacts,
        news,
    )
    notion = _FakeNotionForRender()

    class _FakeSyncWithLocalizer:
        def __init__(self):
            self.db = db
            self.notion = notion
            self.localizer = Localizer()

    sync = _FakeSyncWithLocalizer()
    nr.render_and_write_body(sync, _COMPANY["id"], "page-99", refresh=False)

    assert ("companies.description", "Builds vision models") in sync.localizer.calls
    assert ("dossiers.summary_md", "English summary prose") in sync.localizer.calls
    assert ("dossiers.audit_md", "English audit prose") in sync.localizer.calls
    assert ("analysis_records.facts.audit.overview", "Solid company") in sync.localizer.calls
    assert ("contacts.info", "CEO, tier 1 — data partnerships") in sync.localizer.calls
    assert ("research_records.summary", "Raised $30M led by a16z") in sync.localizer.calls

    all_text = []
    for block in notion.appended.get("page-99", []):
        def _collect_text(b):
            for section in ("paragraph", "heading_1", "heading_2", "heading_3", "heading_4", "quote", "bulleted_list_item"):
                rt = (b.get(section) or {}).get("rich_text", [])
                for seg in rt:
                    all_text.append((seg.get("text") or {}).get("content", ""))
            for child in (b.get("callout") or {}).get("children", []):
                _collect_text(child)
            for child in (b.get("bulleted_list_item") or {}).get("children", []):
                _collect_text(child)
        _collect_text(block)

    assert any("Создаёт модели компьютерного зрения" in text for text in all_text)
    assert any("Русское резюме" in text for text in all_text)
    assert any("Русский аудит" in text for text in all_text)
    assert any("Сильная компания" in text for text in all_text)
    assert any("Привлекла $30M" in text for text in all_text)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_notion_render.py::test_render_and_write_body_localizes_source_inputs_before_rendering -v
```

Expected: FAIL because `render_and_write_body` still only checks `sync.translator` and only localizes dossier summary/audit.

- [ ] **Step 3: Add source-input localization helper**

In `scripts/notion_render.py`, add this helper before `render_and_write_body`:

```python
def _localize_render_inputs(localizer, company, dossier, analysis, contacts, news):
    if localizer is None:
        return company, dossier, analysis, contacts, news

    company = dict(company or {})
    company["description"] = localizer.localize_text(
        company.get("description"),
        field="companies.description",
    )

    if dossier is not None:
        dossier = dict(dossier)
        dossier["summary_md"] = localizer.localize_text(
            dossier.get("summary_md"),
            field="dossiers.summary_md",
        )
        dossier["audit_md"] = localizer.localize_text(
            dossier.get("audit_md"),
            field="dossiers.audit_md",
        )
        for key in ("pain_summary", "pitch_angle", "why_interesting", "outreach_hook"):
            if key in dossier:
                dossier[key] = localizer.localize_text(
                    dossier.get(key),
                    field=f"dossiers.{key}",
                )
        if isinstance(dossier.get("section_summaries"), dict):
            dossier["section_summaries"] = localizer.localize_mapping(
                dossier["section_summaries"],
                field_prefix="dossiers.section_summaries",
            )

    localized_analysis = {}
    for section, row in analysis.items():
        row = dict(row)
        facts = row.get("facts")
        if isinstance(facts, dict):
            row["facts"] = localizer.localize_mapping(
                facts,
                field_prefix=f"analysis_records.facts.{section}",
            )
        localized_analysis[section] = row

    localized_contacts = []
    for contact in contacts:
        contact = dict(contact)
        contact["info"] = localizer.localize_text(
            contact.get("info"),
            field="contacts.info",
        )
        localized_contacts.append(contact)

    localized_news = []
    for item in news:
        item = dict(item)
        item["summary"] = localizer.localize_text(
            item.get("summary"),
            field="research_records.summary",
        )
        localized_news.append(item)

    return company, dossier, localized_analysis, localized_contacts, localized_news
```

- [ ] **Step 4: Replace translator block in `render_and_write_body`**

In `scripts/notion_render.py`, delete:

```python
    translator = getattr(sync, 'translator', None)
    if translator is not None and dossier is not None:
        dossier = dict(dossier)  # shallow copy — avoid mutating original
        if dossier.get("summary_md"):
            dossier["summary_md"] = translator.translate(dossier["summary_md"])
        if dossier.get("audit_md"):
            dossier["audit_md"] = translator.translate(dossier["audit_md"])
```

After fetching `contacts` and `news`, before `build_page_blocks`, insert:

```python
    localizer = getattr(sync, "localizer", None)
    company, dossier, analysis, contacts, news = _localize_render_inputs(
        localizer,
        company,
        dossier,
        analysis,
        contacts,
        news,
    )
```

- [ ] **Step 5: Run render tests**

Run:

```bash
python -m pytest tests/test_notion_render.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/notion_render.py tests/test_notion_render.py
git commit -m "feat(notion): localize rendered page body inputs"
```

---

### Task 7: Wire Bot/Internal Notion Sync

**Files:**
- Modify: `bot/gateway.py`
- Modify: `tests/test_bot_gateway_cleanup.py` or create targeted test in existing gateway test file if it already has sync tests.

- [ ] **Step 1: Add failing gateway wiring test**

Append to `tests/test_bot_gateway_cleanup.py`:

```python
def test_notion_sync_blocking_passes_env_localizer(monkeypatch):
    import bot.gateway as gw

    created = {}

    class FakeSync:
        def __init__(self, notion, db, localizer=None):
            created["localizer"] = localizer

        def sync_forward(self, entity):
            return {"entity": entity, "created": 0, "updated": 0, "errors": 0}

    monkeypatch.setattr("notion_sync.NotionSync", FakeSync, raising=False)
    monkeypatch.setattr("notion_sync._make_notion", lambda: object(), raising=False)
    monkeypatch.setattr("notion_sync._make_db", lambda: object(), raising=False)
    monkeypatch.setattr("notion_sync.make_notion_localizer", lambda: "LOCALIZER", raising=False)

    result = gw._run_notion_sync_blocking()

    assert created["localizer"] == "LOCALIZER"
    assert result["companies"]["entity"] == "companies"
    assert result["contacts"]["entity"] == "contacts"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest tests/test_bot_gateway_cleanup.py::test_notion_sync_blocking_passes_env_localizer -v
```

Expected: FAIL because `_run_notion_sync_blocking` imports only `NotionSync`, `_make_db`, and `_make_notion`.

- [ ] **Step 3: Wire localizer in `bot/gateway.py`**

In `_run_notion_sync_blocking`, replace:

```python
    from notion_sync import NotionSync, _make_db, _make_notion

    sync = NotionSync(notion=_make_notion(), db=_make_db())
```

with:

```python
    from notion_sync import NotionSync, _make_db, _make_notion, make_notion_localizer

    sync = NotionSync(
        notion=_make_notion(),
        db=_make_db(),
        localizer=make_notion_localizer(),
    )
```

- [ ] **Step 4: Run gateway test**

Run:

```bash
python -m pytest tests/test_bot_gateway_cleanup.py::test_notion_sync_blocking_passes_env_localizer -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add bot/gateway.py tests/test_bot_gateway_cleanup.py
git commit -m "feat(notion): use localizer in bot sync"
```

---

### Task 8: Remove Runtime Dependence on Cached Translation Gateway

**Files:**
- Modify: `ARCHITECTURE.md`
- Optional Modify: `scripts/translate.py`
- Optional Modify: `tests/test_translate.py`

- [ ] **Step 1: Add documentation diff**

In `ARCHITECTURE.md`, replace the section that describes `scripts/translate.py` as cached runtime translation with:

```markdown
#### `scripts/notion_localization.py`

Notion-only localization boundary. New agent output is generated in Russian by
prompt contract. Legacy English prose is localized immediately before Notion
writes and is not persisted back to Supabase.

| Function/class | Description |
|---|---|
| `NotionTextLocalizer` | Localizes whitelisted presentation prose, skips structural fields and Russian text, applies failure policy |
| `GeminiTranslationBackend` | Calls Gemini `generateContent` with a translation/editor prompt |
| `make_notion_localizer(env=None)` | Builds the production localizer from `KVETIO_NOTION_LOCALIZATION`, `KVETIO_TRANSLATION_PROVIDER`, `KVETIO_TRANSLATION_MODEL`, and `GEMINI_API_KEY` |

The legacy `translations` table may remain in the database temporarily, but it
is not used by the Notion localization path.
```

- [ ] **Step 2: Decide whether to keep `scripts/translate.py`**

Keep `scripts/translate.py` and `tests/test_translate.py` unchanged for now unless no code imports them after Tasks 1-7. This avoids mixing runtime behavior with DB cleanup. Removal of the `translations` table and old gateway is a separate cleanup phase after production validation.

- [ ] **Step 3: Run docs/schema grep**

Run:

```bash
rg -n "Notion-only localization|notion_localization|translations table may remain" ARCHITECTURE.md
rg -n "Translator\\(|get_or_translate\\(" scripts bot tests -S
```

Expected:

- First command prints the new architecture lines.
- Second command may still find `scripts/translate.py` and `tests/test_translate.py`, but should not find runtime imports in `scripts/notion_sync.py`, `scripts/notion_render.py`, or `bot/gateway.py`.

- [ ] **Step 4: Commit**

```bash
git add ARCHITECTURE.md
git commit -m "docs: document Notion-only localization"
```

---

### Task 9: Full Verification

**Files:**
- No source changes expected unless verification exposes a bug.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
python -m pytest tests/test_notion_localization.py tests/test_notion_sync.py tests/test_notion_render.py tests/test_notion_profile.py tests/test_pipeline_prompts.py tests/test_bot_gateway_cleanup.py -q
```

Expected: PASS.

- [ ] **Step 2: Run full test suite**

Run:

```bash
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 3: Run Notion sync dry-run with localization disabled**

Run:

```bash
KVETIO_NOTION_LOCALIZATION= python scripts/notion_sync.py --entity companies --forward --dry-run
```

Expected: JSON output with `entity: companies` and no Gemini/API key requirement.

- [ ] **Step 4: Run Notion sync validation with localization enabled but no Notion write**

Run:

```bash
KVETIO_NOTION_LOCALIZATION=hybrid KVETIO_TRANSLATION_PROVIDER=gemini KVETIO_TRANSLATION_MODEL=gemini-2.5-flash-lite python scripts/notion_sync.py --validate --dry-run
```

Expected: `{"valid": true}`. This does not require `GEMINI_API_KEY` because validation returns before `NotionSync` construction.

- [ ] **Step 5: Optional live smoke test**

Only run this when `GEMINI_API_KEY`, `NOTION_TOKEN`, `SUPABASE_URL`, `SUPABASE_KEY`, and Notion DB IDs are configured:

```bash
KVETIO_NOTION_LOCALIZATION=hybrid KVETIO_TRANSLATION_PROVIDER=gemini KVETIO_TRANSLATION_MODEL=gemini-2.5-flash-lite KVETIO_TRANSLATION_ON_FAILURE=fail_sync python scripts/notion_sync.py --entity companies --forward --dry-run
```

Expected: dry-run counts companies without writing pages. `sync_forward` builds Notion
properties before the dry-run branch, so this can still call Gemini for legacy
English prose. Use it only after `GEMINI_API_KEY` is configured and the API cost
is acceptable. Use a single real company sync in a controlled environment to
inspect localized Notion output.

- [ ] **Step 6: Commit verification fixes if needed**

If verification required any fixes:

```bash
git add scripts/notion_localization.py scripts/notion_sync.py scripts/notion_render.py scripts/notion_profile.py bot/gateway.py tests/test_notion_localization.py tests/test_notion_sync.py tests/test_notion_render.py tests/test_notion_profile.py tests/test_pipeline_prompts.py tests/test_bot_gateway_cleanup.py agents/prompts/analysis_task.md agents/prompts/analysis_section_task.md agents/prompts/analysis_audit_task.md agents/prompts/conclusions_task.md ARCHITECTURE.md
git commit -m "fix(notion): stabilize Russian localization"
```

If no fixes were required, do not create an empty commit.

---

## Execution Notes

- Do not store translated text in Supabase.
- Do not remove the `translations` table in this implementation. That cleanup should happen only after the new Notion localization path has run successfully in production.
- Do not translate controlled Notion options dynamically.
- Keep `OpenAI` fallback out of the first implementation unless explicitly requested. The approved default is Gemini-first; OpenAI fallback can be a follow-up provider implementation.
- Prefer `fail_sync` for production so English text does not silently enter Notion when Gemini fails.
