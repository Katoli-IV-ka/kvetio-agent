# Sales-Brief Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Расширить пайплайн и схему БД для стабильного получения sales-брифа из досье — с данными о боли клиента, углом питча, outreach-хуком и фирмографикой — и синхронизировать эти поля в Notion как колонки таблицы Companies.

**Architecture:** Три слоя изменений: (1) DB migration — новые колонки в `dossiers` и `companies`; (2) Store/enrichment — `patch_company` + `FirmographicsExtractor` читает payloads уже собранных research_records и заполняет фирмографику; (3) Промпт ConclusionAgent — новые поля записываются в dossier при финализации. Notion sync уже обновлён (`notion_mapping.yaml` + `enrich_company_rows`).

**Tech Stack:** Python 3.11, Supabase (postgrest-py), pytest, YAML, Claude Code Routines (промпты в `agents/prompts/`)

---

## Что уже сделано в этой сессии (не реализовывать повторно)

| Файл | Изменение |
|------|-----------|
| `sql/migrations/029_sales_fields_p0p1.sql` | Новые поля dossiers + companies — **создан, не применён к БД** |
| `sql/schema.sql` | Обновлён под новые поля |
| `config/notion_mapping.yaml` | icp_segment, country, founded_year, company_size, funding_info (computed) |
| `scripts/notion_sync.py` | `_format_funding_info()` + `enrich_company_rows()` |
| `docs/PIPELINE-SPEC-2026-06-23.md` | ТЗ-документ |

---

## Карта файлов

| Файл | Действие | Ответственность |
|------|----------|-----------------|
| `sql/migrations/029_sales_fields_p0p1.sql` | Применить к Supabase | Новые колонки DB |
| `scripts/models.py` | Modify | Company dataclass + firmographic fields |
| `scripts/supabase_store.py` | Modify | `patch_company()` — точечное обновление колонок |
| `scripts/dossier_store.py` | Modify | `DOSSIER_COLUMNS` + новые sales-поля в upsert |
| `scripts/enrichment.py` | Modify | `FirmographicsExtractor` + `run_firmographics()` |
| `agents/prompts/conclusions_task.md` | Modify | Инструкция записи sales-brief полей |
| `tests/test_notion_sync.py` | Modify | Исправить сломанный тест + добавить тесты funding_info |
| `tests/test_enrichment.py` | Modify | Тесты FirmographicsExtractor |
| `tests/test_dossier_store.py` | Modify | Тест новых колонок в DOSSIER_COLUMNS |

---

## Task 1: Применить миграцию 029 к Supabase

**Files:**
- Read: `sql/migrations/029_sales_fields_p0p1.sql`

- [ ] **Step 1: Применить миграцию через Supabase MCP**

```bash
# Прочитать содержимое файла и передать в apply_migration
# project_id = qcfygtxkohopxhsathkv
```

Вызвать `mcp__5192de49__apply_migration` с:
- `project_id`: `qcfygtxkohopxhsathkv`
- `name`: `029_sales_fields_p0p1`
- `query`: содержимое `sql/migrations/029_sales_fields_p0p1.sql`

- [ ] **Step 2: Проверить что колонки появились**

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name IN ('dossiers', 'companies')
  AND column_name IN (
    'pain_summary','outreach_hook','pitch_angle',
    'why_interesting','next_step','entry_point_contact_id',
    'country','founded_year','company_size','legal_name'
  )
ORDER BY table_name, column_name;
```

Ожидаемый результат: 10 строк (6 в dossiers, 4 в companies).

- [ ] **Step 3: Commit (только migration file — он уже был в индексе)**

```bash
cd kvetio-agent
git add sql/migrations/029_sales_fields_p0p1.sql sql/schema.sql
git commit -m "feat(db): add sales-brief fields to dossiers + companies (029)"
```

---

## Task 2: patch_company в SupabaseStore

**Files:**
- Modify: `scripts/supabase_store.py` (после строки `upsert_company`)
- Test: `tests/test_supabase_store.py`

- [ ] **Step 1: Написать failing тест**

В `tests/test_supabase_store.py` добавить:

```python
def test_patch_company_updates_only_specified_fields(mock_supabase):
    """patch_company sends only the given fields to Supabase."""
    store = SupabaseStore.__new__(SupabaseStore)
    store._client = mock_supabase

    store.patch_company("acme.com", {"country": "US", "founded_year": 2018})

    mock_supabase.table.assert_called_with("companies")
    mock_supabase.table().update.assert_called_once_with(
        {"country": "US", "founded_year": 2018}
    )
    mock_supabase.table().update().eq.assert_called_once_with("domain", "acme.com")
```

- [ ] **Step 2: Убедиться что тест падает**

```bash
pytest tests/test_supabase_store.py::test_patch_company_updates_only_specified_fields -v
```

Ожидаемый результат: `FAILED — AttributeError: 'SupabaseStore' object has no attribute 'patch_company'`

- [ ] **Step 3: Реализовать patch_company**

В `scripts/supabase_store.py` после метода `upsert_company` добавить:

```python
def patch_company(self, domain: str, fields: dict) -> None:
    """Update specific columns on a company row without overwriting others.

    Use for incremental enrichment (firmographics, linkedin_url resolution, etc.)
    where only a subset of columns is known at call time.
    """
    if not fields:
        return
    self._client.table("companies").update(fields).eq("domain", domain).execute()
    logger.debug("patch_company: %s %s", domain, sorted(fields.keys()))
```

- [ ] **Step 4: Запустить тест**

```bash
pytest tests/test_supabase_store.py::test_patch_company_updates_only_specified_fields -v
```

Ожидаемый результат: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add scripts/supabase_store.py tests/test_supabase_store.py
git commit -m "feat(store): add patch_company for incremental column updates"
```

---

## Task 3: Обновить DOSSIER_COLUMNS в dossier_store

**Files:**
- Modify: `scripts/dossier_store.py`
- Test: `tests/test_dossier_store.py`

- [ ] **Step 1: Написать failing тест**

В `tests/test_dossier_store.py` добавить:

```python
def test_dossier_columns_includes_sales_brief_fields():
    """New sales-brief columns must be in DOSSIER_COLUMNS for upsert to write them."""
    from dossier_store import DOSSIER_COLUMNS
    required = {
        "pain_summary", "outreach_hook", "pitch_angle",
        "why_interesting", "next_step", "entry_point_contact_id",
    }
    missing = required - set(DOSSIER_COLUMNS)
    assert not missing, f"Missing from DOSSIER_COLUMNS: {missing}"
```

- [ ] **Step 2: Убедиться что тест падает**

```bash
pytest tests/test_dossier_store.py::test_dossier_columns_includes_sales_brief_fields -v
```

Ожидаемый результат: `FAILED — Missing from DOSSIER_COLUMNS: {...}`

- [ ] **Step 3: Добавить поля в DOSSIER_COLUMNS**

В `scripts/dossier_store.py` найти `DOSSIER_COLUMNS` и расширить:

```python
DOSSIER_COLUMNS = (
    "company_id",
    "funding_stage",
    "funding_amount_usd",
    "funding_date",
    "product_category",
    "ai_use_case",
    "icp_fit",
    "last_news_date",
    "extra_facts",
    "section_summaries",
    "summary_md",
    "audit_md",
    # Sales-brief fields (029)
    "pain_summary",
    "outreach_hook",
    "pitch_angle",
    "why_interesting",
    "next_step",
    "entry_point_contact_id",
    "notion_page_id",
    "notion_synced_at",
    "derived_from_model",
    "version",
)
```

- [ ] **Step 4: Запустить тест**

```bash
pytest tests/test_dossier_store.py -v
```

Ожидаемый результат: все тесты `PASSED`

- [ ] **Step 5: Commit**

```bash
git add scripts/dossier_store.py tests/test_dossier_store.py
git commit -m "feat(store): add sales-brief fields to DOSSIER_COLUMNS"
```

---

## Task 4: FirmographicsExtractor в enrichment.py

Читает payloads уже записанных Wikidata/OpenCorporates research_records и пишет
`country`, `founded_year`, `company_size` в companies через `patch_company`.

**Files:**
- Modify: `scripts/enrichment.py`
- Test: `tests/test_enrichment.py`

- [ ] **Step 1: Написать failing тесты**

В `tests/test_enrichment.py` добавить:

```python
from enrichment import (
    FirmographicsExtractor,
    _headcount_to_size,
    _jurisdiction_to_country,
    run_firmographics,
)


def test_headcount_to_size_ranges():
    assert _headcount_to_size(1)    == "1-10"
    assert _headcount_to_size(10)   == "1-10"
    assert _headcount_to_size(11)   == "11-50"
    assert _headcount_to_size(50)   == "11-50"
    assert _headcount_to_size(51)   == "51-200"
    assert _headcount_to_size(200)  == "51-200"
    assert _headcount_to_size(201)  == "201-500"
    assert _headcount_to_size(501)  == "501-1000"
    assert _headcount_to_size(1001) == "1000+"


def test_jurisdiction_to_country_parses_prefix():
    assert _jurisdiction_to_country("us_de") == "US"
    assert _jurisdiction_to_country("gb")    == "GB"
    assert _jurisdiction_to_country("de")    == "DE"


def test_firmographics_extractor_reads_wikidata_payload():
    class FakeStore:
        def get_research_records_for_company(self, domain):
            return [
                {
                    "source": "wikidata_resolver",
                    "payload": {"inception": "2015-03-01", "employees": "+120"},
                }
            ]

    extractor = FirmographicsExtractor()
    result = extractor.extract({"domain": "acme.com"}, FakeStore())
    assert result["founded_year"] == 2015
    assert result["company_size"] == "51-200"


def test_firmographics_extractor_reads_opencorporates_payload():
    class FakeStore:
        def get_research_records_for_company(self, domain):
            return [
                {
                    "source": "opencorporates_resolver",
                    "payload": {"jurisdiction": "us_ca"},
                }
            ]

    extractor = FirmographicsExtractor()
    result = extractor.extract({"domain": "acme.com"}, FakeStore())
    assert result["country"] == "US"


def test_firmographics_extractor_skips_empty_payload():
    class FakeStore:
        def get_research_records_for_company(self, domain):
            return [{"source": "wikidata_resolver", "payload": {}}]

    extractor = FirmographicsExtractor()
    result = extractor.extract({"domain": "acme.com"}, FakeStore())
    assert result == {}


def test_run_firmographics_calls_patch_when_data_found():
    patched = {}

    class FakeStore:
        def get_research_records_for_company(self, domain):
            return [
                {
                    "source": "wikidata_resolver",
                    "payload": {"inception": "2010-06-01"},
                }
            ]

        def patch_company(self, domain, fields):
            patched.update(fields)

    run_firmographics({"domain": "acme.com"}, FakeStore())
    assert patched == {"founded_year": 2010}
```

- [ ] **Step 2: Убедиться что тесты падают**

```bash
pytest tests/test_enrichment.py -k "firmograph or headcount or jurisdiction" -v
```

Ожидаемый результат: `ImportError` или `FAILED`

- [ ] **Step 3: Реализовать в enrichment.py**

В `scripts/enrichment.py` добавить после `RESOLVERS` и перед `_main()`:

```python
def _headcount_to_size(n: int) -> str:
    """Map raw headcount to a canonical company_size label."""
    if n <= 10:   return "1-10"
    if n <= 50:   return "11-50"
    if n <= 200:  return "51-200"
    if n <= 500:  return "201-500"
    if n <= 1000: return "501-1000"
    return "1000+"


def _jurisdiction_to_country(jurisdiction: str) -> str:
    """'us_de' → 'US', 'gb' → 'GB'. Uses prefix before first underscore."""
    return jurisdiction.split("_")[0].upper()


class FirmographicsExtractor:
    """Reads Wikidata / OpenCorporates payloads already stored as research_records
    and extracts firmographic facts (country, founded_year, company_size).

    Does NOT make network calls — all data is already in the DB from prior resolvers.
    """

    def extract(self, company: dict, store) -> dict:
        """Return dict of firmographic updates for patch_company. Empty dict if nothing found."""
        updates: dict = {}
        for rec in store.get_research_records_for_company(company.get("domain") or ""):
            source = rec.get("source") or ""
            payload = rec.get("payload") or {}

            if "wikidata" in source:
                if not updates.get("founded_year"):
                    inception = payload.get("inception")  # e.g. "2015-03-01"
                    if inception:
                        try:
                            updates["founded_year"] = int(str(inception)[:4])
                        except (ValueError, TypeError):
                            pass

                if not updates.get("company_size"):
                    raw = payload.get("employees")  # e.g. "+120" or "120"
                    if raw:
                        try:
                            n = int(str(raw).lstrip("+").split(".")[0])
                            updates["company_size"] = _headcount_to_size(n)
                        except (ValueError, TypeError):
                            pass

            if "opencorporates" in source:
                if not updates.get("country"):
                    jurisdiction = payload.get("jurisdiction")
                    if jurisdiction:
                        updates["country"] = _jurisdiction_to_country(jurisdiction)

        return updates


def run_firmographics(company: dict, store) -> dict:
    """Extract firmographic fields from existing research_records and patch companies table.

    Call after run_enrichment so Wikidata/OpenCorporates records are already written.
    Returns the dict of fields written (empty dict if nothing found).
    """
    updates = FirmographicsExtractor().extract(company, store)
    if updates:
        store.patch_company(company["domain"], updates)
        logger.info(
            "firmographics %s: %s", company.get("domain"), sorted(updates.keys())
        )
    return updates
```

- [ ] **Step 4: Запустить тесты**

```bash
pytest tests/test_enrichment.py -v
```

Ожидаемый результат: все тесты `PASSED`

- [ ] **Step 5: Commit**

```bash
git add scripts/enrichment.py tests/test_enrichment.py
git commit -m "feat(enrichment): FirmographicsExtractor — country/founded_year/company_size from stored payloads"
```

---

## Task 5: Исправить и расширить тесты notion_sync

Тест `test_companies_mapping_matches_release_schema` устарел — ожидает старый маппинг.
Нужно обновить assertion и добавить тесты для `_format_funding_info` и `enrich_company_rows`.

**Files:**
- Modify: `tests/test_notion_sync.py`

- [ ] **Step 1: Запустить текущие тесты и увидеть падение**

```bash
pytest tests/test_notion_sync.py::test_companies_mapping_matches_release_schema -v
```

Ожидаемый результат: `FAILED — AssertionError`

- [ ] **Step 2: Обновить test_companies_mapping_matches_release_schema**

Найти тест `test_companies_mapping_matches_release_schema` и заменить assertion:

```python
def test_companies_mapping_matches_release_schema():
    mapping = ns.load_mapping()
    fields = {f["db_column"]: f for f in mapping["companies"]["fields"]}

    # Core fields always present
    assert fields["name"]["notion_type"] == "title"
    assert fields["website"]["notion_type"] == "url"
    assert fields["linkedin_url"]["notion_type"] == "url"
    assert fields["description"]["notion_type"] == "rich_text"

    # Firmographic fields (029)
    assert fields["icp_segment"]["notion_type"] == "select"
    assert fields["country"]["notion_type"] == "select"
    assert fields["founded_year"]["notion_type"] == "number"
    assert fields["company_size"]["notion_type"] == "select"

    # Computed field
    assert fields["funding_info"]["notion_type"] == "rich_text"
    assert fields["funding_info"]["direction"] == "forward"

    # All are forward
    for col, f in fields.items():
        assert f["direction"] == "forward", f"{col} should be forward"
```

- [ ] **Step 3: Добавить тесты для _format_funding_info**

```python
def test_format_funding_info_full():
    d = {"funding_stage": "Series A", "funding_amount_usd": 12_000_000, "funding_date": "2024-06-15"}
    result = ns._format_funding_info(d)
    assert result == "Series A · $12M · Jun 2024"


def test_format_funding_info_billions():
    d = {"funding_stage": "Series D", "funding_amount_usd": 1_500_000_000, "funding_date": None}
    result = ns._format_funding_info(d)
    assert result == "Series D · $1.5B"


def test_format_funding_info_thousands():
    d = {"funding_stage": "Seed", "funding_amount_usd": 500_000, "funding_date": "2023-01-10"}
    result = ns._format_funding_info(d)
    assert result == "Seed · $500K · Jan 2023"


def test_format_funding_info_stage_only():
    d = {"funding_stage": "Grant", "funding_amount_usd": None, "funding_date": None}
    assert ns._format_funding_info(d) == "Grant"


def test_format_funding_info_empty_dossier():
    assert ns._format_funding_info({}) is None
```

- [ ] **Step 4: Добавить тест для enrich_company_rows**

```python
def test_enrich_company_rows_adds_funding_info():
    class FakeDb:
        def fetch_for_company(self, table, company_id):
            return [{"funding_stage": "Seed", "funding_amount_usd": 2_000_000, "funding_date": "2022-03-01"}]

    rows = [{"id": "uuid-1", "domain": "acme.com", "name": "Acme"}]
    result = ns.enrich_company_rows(rows, FakeDb())
    assert result[0]["funding_info"] == "Seed · $2M · Mar 2022"


def test_enrich_company_rows_no_dossier_gives_none():
    class FakeDb:
        def fetch_for_company(self, table, company_id):
            return []

    rows = [{"id": "uuid-2", "domain": "empty.com", "name": "Empty"}]
    result = ns.enrich_company_rows(rows, FakeDb())
    assert result[0]["funding_info"] is None
```

- [ ] **Step 5: Запустить все тесты notion_sync**

```bash
pytest tests/test_notion_sync.py -v
```

Ожидаемый результат: все тесты `PASSED`

- [ ] **Step 6: Commit**

```bash
git add tests/test_notion_sync.py
git commit -m "test(notion_sync): update mapping assertion + add funding_info tests"
```

---

## Task 6: Обновить промпт ConclusionAgent

**Files:**
- Modify: `agents/prompts/conclusions_task.md`

- [ ] **Step 1: Обновить секцию "Write dossier"**

Найти блок `## Write dossier` и заменить список полей:

```markdown
## Write dossier

```bash
python scripts/dossier_store.py --upsert-dossier
```

Write typed fields to `dossiers`:

**Существующие поля:**
- `funding_stage`, `funding_amount_usd`, `funding_date`
- `product_category`, `ai_use_case`
- `icp_fit`, `last_news_date`
- `section_summaries`, `summary_md`, `audit_md`

Размер компании не писать в `dossiers`: использовать `companies.company_size`.

**Новые sales-brief поля (обязательно заполнить для dossier_ready):**
- `pain_summary` — 2-4 предложения: какая конкретная боль с данными есть у этой компании исходя из их продукта. Не сухой список типов данных — нарратив специфики и проблемы. Пример: "Компания строит систему сегментации медицинских снимков. Узкое место — размеченные DICOM-датасеты: публичных почти нет, внутренняя разметка дорогая и медленная, а качество критично для регуляторного одобрения."
- `pitch_angle` — 1-2 предложения: наш конкретный угол ценностного предложения для этой компании. Пример: "Мы можем поставить pre-labelled DICOM датасеты от аккредитованных радиологов, что сокращает time-to-model на 3-6 месяцев."
- `why_interesting` — 1-3 предложения: внутренняя заметка, почему лид сильный. Пример: "Свежий раунд Series A, активный найм ML-инженеров, CEO публично жаловался на annotation bottleneck на конференции."
- `outreach_hook` — одно конкретное свежее событие ЛПР для первого сообщения в LinkedIn. Пример: "Выступил на MICCAI 2025 с докладом «Annotation Quality in Medical AI»." Если события нет — оставить null.

Then write `dossier_links` for every contributing `analysis_record`.
```

- [ ] **Step 2: Обновить секцию Notion**

Найти блок `## Notion` и обновить:

```markdown
## Notion

After dossier write, run:

```bash
python scripts/notion_sync.py --entity companies --forward
python scripts/notion_sync.py --entity contacts --forward
```

`enrich_company_rows` автоматически подтянет dossier и синтезирует `Funding Info`.
Новые колонки (ICP Segment, Country, Founded, Company Size, Funding Info) обновятся
в таблице Companies в Notion.

Use the repository sync script. Do not publish ad hoc pages manually.
```

- [ ] **Step 3: Проверить промпт вручную**

```bash
cat agents/prompts/conclusions_task.md
```

Убедиться что pain_summary, pitch_angle, why_interesting, outreach_hook описаны с примерами.

- [ ] **Step 4: Commit**

```bash
git add agents/prompts/conclusions_task.md
git commit -m "feat(agent): ConclusionAgent writes sales-brief fields (pain_summary, pitch_angle, outreach_hook)"
```

---

## Task 7: Применить Notion schema update

- [ ] **Step 1: Запустить ensure-schema**

```bash
python scripts/notion_sync.py --ensure-schema --entity companies --dry-run
```

Ожидаемый результат: JSON с `created_props` включающим: `["Company Size", "Country", "Founded", "Funding Info", "ICP Segment"]`

- [ ] **Step 2: Применить без dry-run**

```bash
python scripts/notion_sync.py --ensure-schema --entity companies
```

Ожидаемый результат: `{"entity": "companies", "created": 5, "created_props": [...]}`

- [ ] **Step 3: Проверить в Notion**

Открыть базу Companies в Notion, убедиться что появились новые колонки.

- [ ] **Step 4: Запустить полный тест-сюит**

```bash
pytest -x -q
```

Ожидаемый результат: все тесты `PASSED` (или известные skip)

---

## Итоговая карта изменений

```
migrations/
  029_sales_fields_p0p1.sql   ← применена к Supabase ✓

scripts/
  supabase_store.py           ← patch_company()
  dossier_store.py            ← DOSSIER_COLUMNS расширен
  enrichment.py               ← FirmographicsExtractor + run_firmographics()
  notion_sync.py              ← _format_funding_info + enrich_company_rows [DONE]

config/
  notion_mapping.yaml         ← icp_segment, country, founded_year,
                                 company_size, funding_info [DONE]

agents/prompts/
  conclusions_task.md         ← инструкция для pain_summary, pitch_angle,
                                 why_interesting, outreach_hook

tests/
  test_supabase_store.py      ← test_patch_company
  test_dossier_store.py       ← test_dossier_columns_includes_sales_brief_fields
  test_enrichment.py          ← FirmographicsExtractor tests
  test_notion_sync.py         ← обновлён + funding_info tests
```

---

## P2 (не реализовывать сейчас)

- `ContactsAgent`: парсинг speaker lists конференций как источник контактов + outreach_hook
- Buying-signal scoring: приоритизация очереди по job_count + news + quote records
