# Notion Company Profile Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a deterministic Notion company profile from `companies + dossiers + computed` fields, add a translation cache for Russian output, and wire everything into the existing sync pipeline.

**Architecture:** A new pure `notion_profile.py` module handles profile building with no I/O; a new `translate.py` module provides a cache-backed translation gateway injected into `NotionSync`; `notion_mapping.yaml` is updated to the full 11-field companies schema (profile_builder flag), contacts renamed to English. Tests stay offline via stub translator.

**Tech Stack:** Python 3.11+, PyYAML, hashlib (stdlib), pytest; existing `notion_sync.py`/`notion_render.py` patterns extended.

---

## File map

| Action | Path | What it does |
|--------|------|-------------|
| Create | `sql/migrations/029_notion_profile_fields.sql` | Migration: hq_country, hq_location on companies; source, outreach_status on contacts; translations table |
| Modify | `sql/schema.sql` | Add same columns/table to clean-install schema |
| Create | `config/potential_data.yaml` | Segment→data-type mapping for Potential Data field |
| Create | `scripts/notion_profile.py` | `_format_amount`, `_compute_funding_info`, `_compute_potential_data`, `_compute_last_info_update`, `build_company_notion_profile`, `build_company_profiles`, `load_potential_cfg` |
| Create | `scripts/translate.py` | `get_or_translate`, `Translator` class |
| Modify | `config/notion_mapping.yaml` | Companies: 11 fields + `profile_builder: true`; contacts: English names + outreach_status/source; remove dossiers entity |
| Modify | `scripts/notion_sync.py` | `validate_mapping` accepts `source`; `sync_forward` calls profile builder; `sync_dossiers` translates prose; `NotionSync.__init__` accepts `translator` |
| Modify | `scripts/notion_render.py` | `render_and_write_body` translates dossier prose via `sync.translator` |
| Create | `tests/test_notion_profile.py` | All profile-builder tests |
| Create | `tests/test_translate.py` | All translator tests |
| Modify | `tests/test_notion_sync.py` | Update mapping-shape tests; add profile-builder integration tests |

---

## Task 1: SQL migration + schema.sql

**Files:**
- Create: `sql/migrations/029_notion_profile_fields.sql`
- Modify: `sql/schema.sql`

- [ ] **Step 1.1: Create migration file**

```sql
-- sql/migrations/029_notion_profile_fields.sql
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS hq_country  text,
  ADD COLUMN IF NOT EXISTS hq_location text;

ALTER TABLE contacts
  ADD COLUMN IF NOT EXISTS source text,
  ADD COLUMN IF NOT EXISTS outreach_status text NOT NULL DEFAULT 'new'
    CONSTRAINT contacts_outreach_check
    CHECK (outreach_status IN ('new','queued','contacted','replied','bounced','skip'));

CREATE TABLE IF NOT EXISTS translations (
  source_hash     text NOT NULL,
  target_lang     text NOT NULL DEFAULT 'ru',
  source_text     text NOT NULL,
  translated_text text NOT NULL,
  model           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_hash, target_lang)
);
```

- [ ] **Step 1.2: Add hq_country/hq_location to companies table in schema.sql**

In `sql/schema.sql`, after the `description TEXT,` line in the companies table, add:

```sql
    hq_country TEXT,
    hq_location TEXT,
```

- [ ] **Step 1.3: Add source/outreach_status to contacts table in schema.sql**

In `sql/schema.sql`, in the contacts table definition (after the existing columns), add before the closing `)`  and constraint lines:

```sql
    source          text,
    outreach_status text NOT NULL DEFAULT 'new'
        CONSTRAINT contacts_outreach_check
        CHECK (outreach_status IN ('new','queued','contacted','replied','bounced','skip')),
```

- [ ] **Step 1.4: Add translations table to schema.sql**

At the end of `sql/schema.sql`, append:

```sql
-- ─── translations ────────────────────────────────────────────────────────────

CREATE TABLE translations (
  source_hash     text NOT NULL,
  target_lang     text NOT NULL DEFAULT 'ru',
  source_text     text NOT NULL,
  translated_text text NOT NULL,
  model           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_hash, target_lang)
);
```

- [ ] **Step 1.5: Commit**

```bash
git add sql/migrations/029_notion_profile_fields.sql sql/schema.sql
git commit -m "feat: add hq_country/hq_location, contacts.source/outreach_status, translations table"
```

---

## Task 2: potential_data.yaml config

**Files:**
- Create: `config/potential_data.yaml`

- [ ] **Step 2.1: Create the file**

```yaml
# config/potential_data.yaml
# Maps icp_segment → list of Potential Data multi_select values.
# status_overrides adds values based on pipeline status.
# All 15 values: Medical Data, Images, Annotation, Video, Synthetic Data,
# Audio, Voice Data, Transcription, Camera Data, Sensor Data, Geospatial Data,
# Text, LLM Data, Human Feedback, Data Supplier

segments:
  medical-imaging:
    - Medical Data
    - Images
    - Annotation

  autonomous-vehicles:
    - Images
    - Annotation
    - Video
    - Camera Data
    - Sensor Data
    - Geospatial Data
    - Synthetic Data

  speech-and-audio:
    - Audio
    - Voice Data
    - Transcription

  generative-ai:
    - Text
    - LLM Data
    - Human Feedback
    - Synthetic Data

  agriculture-ai:
    - Images
    - Annotation
    - Geospatial Data
    - Camera Data

  robotics-ai:
    - Images
    - Annotation
    - Video
    - Synthetic Data
    - Camera Data
    - Sensor Data

  video-photo-ai:
    - Video
    - Images
    - Annotation
    - Synthetic Data

status_overrides:
  data_partner:
    - Data Supplier
```

- [ ] **Step 2.2: Commit**

```bash
git add config/potential_data.yaml
git commit -m "feat: add potential_data.yaml segment→data-type mapping"
```

---

## Task 3: notion_profile.py — _format_amount + funding_info (TDD)

**Files:**
- Create: `scripts/notion_profile.py`
- Create: `tests/test_notion_profile.py`

- [ ] **Step 3.1: Write failing tests for _format_amount and _compute_funding_info**

Create `tests/test_notion_profile.py`:

```python
"""Tests for notion_profile: pure profile-builder functions."""
from __future__ import annotations
import pytest
import notion_profile as np_mod


# ---------------------------------------------------------------------------
# _format_amount
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("usd,expected", [
    (12_000_000,        "$12M"),
    (3_500_000,         "$3.5M"),
    (750_000,           "$750K"),
    (1_000_000_000,     "$1B"),
    (1_200_000_000,     "$1.2B"),
    (500,               "$500"),
    (1_000,             "$1K"),
    (1_100,             "$1.1K"),
    (100_000_000,       "$100M"),
])
def test_format_amount(usd, expected):
    assert np_mod._format_amount(usd) == expected


# ---------------------------------------------------------------------------
# _compute_funding_info
# ---------------------------------------------------------------------------

def test_funding_info_both():
    result = np_mod._compute_funding_info("Series A", 12_000_000)
    assert result == "Series A · $12M"


def test_funding_info_stage_only():
    result = np_mod._compute_funding_info("Seed", None)
    assert result == "Seed"


def test_funding_info_amount_only():
    result = np_mod._compute_funding_info(None, 3_000_000)
    assert result == "$3M"


def test_funding_info_none():
    result = np_mod._compute_funding_info(None, None)
    assert result is None
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent/.claude/worktrees/strange-gauss-feb25d
python -m pytest tests/test_notion_profile.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'notion_profile'`

- [ ] **Step 3.3: Create scripts/notion_profile.py with these two functions**

```python
"""Company Notion profile builder.

Pure functions — zero I/O. Takes DB rows, returns flat profile dicts
ready for to_notion_property mapping.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parent.parent
POTENTIAL_DATA_PATH = _REPO_ROOT / "config" / "potential_data.yaml"


def load_potential_cfg(path: Path = POTENTIAL_DATA_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _format_amount(usd: float | int) -> str:
    """Format USD amount as compact string: $12M, $3.5M, $750K, $1B."""
    if usd >= 1_000_000_000:
        v = round(usd / 1_000_000_000, 1)
        return f"${v:g}B"
    if usd >= 1_000_000:
        v = round(usd / 1_000_000, 1)
        return f"${v:g}M"
    if usd >= 1_000:
        v = round(usd / 1_000, 1)
        return f"${v:g}K"
    return f"${int(usd)}"


def _compute_funding_info(stage: str | None, amount_usd: float | None) -> str | None:
    amount_str = _format_amount(amount_usd) if amount_usd is not None else None
    if stage and amount_str:
        return f"{stage} · {amount_str}"
    if stage:
        return stage
    if amount_str:
        return amount_str
    return None
```

- [ ] **Step 3.4: Run tests to confirm they pass**

```bash
python -m pytest tests/test_notion_profile.py::test_format_amount tests/test_notion_profile.py::test_funding_info_both tests/test_notion_profile.py::test_funding_info_stage_only tests/test_notion_profile.py::test_funding_info_amount_only tests/test_notion_profile.py::test_funding_info_none -v
```

Expected: 13 passed.

- [ ] **Step 3.5: Commit**

```bash
git add scripts/notion_profile.py tests/test_notion_profile.py
git commit -m "feat: add _format_amount and _compute_funding_info to notion_profile"
```

---

## Task 4: notion_profile.py — potential_data + last_info_update (TDD)

**Files:**
- Modify: `scripts/notion_profile.py`
- Modify: `tests/test_notion_profile.py`

- [ ] **Step 4.1: Add failing tests for _compute_potential_data and _compute_last_info_update**

Append to `tests/test_notion_profile.py`:

```python
# ---------------------------------------------------------------------------
# _compute_potential_data
# ---------------------------------------------------------------------------

_POTENTIAL_CFG = {
    "segments": {
        "medical-imaging": ["Medical Data", "Images", "Annotation"],
        "generative-ai": ["Text", "LLM Data", "Human Feedback"],
    },
    "status_overrides": {
        "data_partner": ["Data Supplier"],
    },
}


def test_potential_data_by_segment():
    result = np_mod._compute_potential_data("medical-imaging", "relevant", _POTENTIAL_CFG)
    assert result == ["Medical Data", "Images", "Annotation"]


def test_potential_data_union_with_status_override():
    result = np_mod._compute_potential_data("generative-ai", "data_partner", _POTENTIAL_CFG)
    assert result == ["Text", "LLM Data", "Human Feedback", "Data Supplier"]


def test_potential_data_no_duplicate_when_override_already_in_segment():
    cfg = {
        "segments": {"seg": ["A", "B"]},
        "status_overrides": {"data_partner": ["B", "C"]},
    }
    result = np_mod._compute_potential_data("seg", "data_partner", cfg)
    assert result == ["A", "B", "C"]


def test_potential_data_unknown_segment_returns_empty():
    result = np_mod._compute_potential_data("unknown-segment", "relevant", _POTENTIAL_CFG)
    assert result == []


def test_potential_data_none_segment_returns_empty():
    result = np_mod._compute_potential_data(None, None, _POTENTIAL_CFG)
    assert result == []


# ---------------------------------------------------------------------------
# _compute_last_info_update
# ---------------------------------------------------------------------------

def test_last_info_update_max_across_all_sources():
    company = {"updated_at": "2026-01-01T00:00:00"}
    dossier = {"updated_at": "2026-03-15T00:00:00"}
    aggregates = {
        "last_research_created_at": "2026-02-10",
        "last_contact_updated_at": "2026-04-01",
    }
    result = np_mod._compute_last_info_update(company, dossier, aggregates)
    assert result == "2026-04-01"


def test_last_info_update_ignores_none():
    company = {"updated_at": "2026-05-01T00:00:00"}
    result = np_mod._compute_last_info_update(company, None, {})
    assert result == "2026-05-01"


def test_last_info_update_returns_none_when_all_none():
    result = np_mod._compute_last_info_update({}, None, {})
    assert result is None
```

- [ ] **Step 4.2: Run to confirm failures**

```bash
python -m pytest tests/test_notion_profile.py -k "potential_data or last_info_update" -v 2>&1 | head -20
```

Expected: `AttributeError: module 'notion_profile' has no attribute '_compute_potential_data'`

- [ ] **Step 4.3: Implement both functions in scripts/notion_profile.py**

Append after `_compute_funding_info`:

```python
def _compute_potential_data(
    icp_segment: str | None,
    status: str | None,
    potential_cfg: dict,
) -> list[str]:
    segments = potential_cfg.get("segments", {})
    status_overrides = potential_cfg.get("status_overrides", {})
    base = list(segments.get(icp_segment or "", []))
    overrides = list(status_overrides.get(status or "", []))
    seen: set[str] = set()
    result: list[str] = []
    for item in base + overrides:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _compute_last_info_update(
    company: dict,
    dossier: dict | None,
    aggregates: dict,
) -> str | None:
    candidates: list[str] = []
    if company.get("updated_at"):
        candidates.append(str(company["updated_at"])[:10])
    if dossier and dossier.get("updated_at"):
        candidates.append(str(dossier["updated_at"])[:10])
    if aggregates.get("last_research_created_at"):
        candidates.append(str(aggregates["last_research_created_at"])[:10])
    if aggregates.get("last_contact_updated_at"):
        candidates.append(str(aggregates["last_contact_updated_at"])[:10])
    return max(candidates) if candidates else None
```

- [ ] **Step 4.4: Run all notion_profile tests**

```bash
python -m pytest tests/test_notion_profile.py -v
```

Expected: all pass.

- [ ] **Step 4.5: Commit**

```bash
git add scripts/notion_profile.py tests/test_notion_profile.py
git commit -m "feat: add _compute_potential_data and _compute_last_info_update"
```

---

## Task 5: notion_profile.py — build_company_notion_profile (TDD)

**Files:**
- Modify: `scripts/notion_profile.py`
- Modify: `tests/test_notion_profile.py`

- [ ] **Step 5.1: Add failing tests for build_company_notion_profile**

Append to `tests/test_notion_profile.py`:

```python
# ---------------------------------------------------------------------------
# build_company_notion_profile
# ---------------------------------------------------------------------------

_COMPANY = {
    "id": "co-uuid",
    "domain": "acme.ai",
    "name": "Acme AI",
    "website": "https://acme.ai",
    "linkedin_url": "https://linkedin.com/company/acme",
    "icp_segment": "medical-imaging",
    "status": "relevant",
    "description": "AI-powered radiology platform.",
    "hq_country": "US",
    "notion_page_id": "np-123",
    "notion_synced_at": "2026-06-01T00:00:00",
    "updated_at": "2026-06-01T00:00:00",
}

_DOSSIER = {
    "company_id": "co-uuid",
    "team_size_estimate": "11-50",
    "funding_stage": "Series A",
    "funding_amount_usd": 12_000_000,
    "updated_at": "2026-06-10T00:00:00",
}

_AGGREGATES = {
    "last_research_created_at": "2026-06-15",
    "last_contact_updated_at": None,
}


def test_profile_contains_expected_fields():
    profile = np_mod.build_company_notion_profile(
        _COMPANY, _DOSSIER, _AGGREGATES, _POTENTIAL_CFG
    )
    assert profile["name"] == "Acme AI"
    assert profile["website"] == "https://acme.ai"
    assert profile["linkedin_url"] == "https://linkedin.com/company/acme"
    assert profile["icp_segment"] == "medical-imaging"
    assert profile["status"] == "relevant"
    assert profile["description"] == "AI-powered radiology platform."
    assert profile["hq_country"] == "US"
    assert profile["team_size_estimate"] == "11-50"
    assert profile["funding_info"] == "Series A · $12M"
    assert profile["potential_data"] == ["Medical Data", "Images", "Annotation"]
    assert profile["last_info_update"] == "2026-06-15"


def test_profile_preserves_service_keys():
    profile = np_mod.build_company_notion_profile(
        _COMPANY, _DOSSIER, _AGGREGATES, _POTENTIAL_CFG
    )
    assert profile["id"] == "co-uuid"
    assert profile["domain"] == "acme.ai"
    assert profile["notion_page_id"] == "np-123"
    assert profile["notion_synced_at"] == "2026-06-01T00:00:00"


def test_profile_none_dossier():
    profile = np_mod.build_company_notion_profile(
        _COMPANY, None, {}, _POTENTIAL_CFG
    )
    assert profile["team_size_estimate"] is None
    assert profile["funding_info"] is None


def test_profile_translator_translates_description():
    class StubTranslator:
        def translate(self, text: str) -> str:
            return f"RU:{text}"

    profile = np_mod.build_company_notion_profile(
        _COMPANY, None, {}, _POTENTIAL_CFG, translator=StubTranslator()
    )
    assert profile["description"] == "RU:AI-powered radiology platform."


def test_profile_translator_does_not_translate_select_fields():
    class StubTranslator:
        def translate(self, text: str) -> str:
            return f"RU:{text}"

    profile = np_mod.build_company_notion_profile(
        _COMPANY, None, {}, _POTENTIAL_CFG, translator=StubTranslator()
    )
    assert profile["icp_segment"] == "medical-imaging"
    assert profile["status"] == "relevant"
    assert profile["hq_country"] == "US"
```

- [ ] **Step 5.2: Run to confirm failures**

```bash
python -m pytest tests/test_notion_profile.py -k "profile" -v 2>&1 | head -20
```

Expected: `AttributeError: module 'notion_profile' has no attribute 'build_company_notion_profile'`

- [ ] **Step 5.3: Implement build_company_notion_profile in scripts/notion_profile.py**

Append after `_compute_last_info_update`:

```python
def build_company_notion_profile(
    company: dict,
    dossier: dict | None,
    aggregates: dict,
    potential_cfg: dict,
    translator=None,
) -> dict:
    """Pure function. Returns flat profile dict for forward mapping.

    Includes both presentation keys (matching db_column from YAML) and
    service keys required for writeback (id, domain, notion_page_id, notion_synced_at).
    """
    d = dossier or {}

    description = company.get("description")
    if translator and description:
        description = translator.translate(description)

    return {
        # db_column keys (match notion_mapping.yaml fields)
        "name": company.get("name"),
        "website": company.get("website"),
        "linkedin_url": company.get("linkedin_url"),
        "icp_segment": company.get("icp_segment"),
        "status": company.get("status"),
        "description": description,
        "hq_country": company.get("hq_country"),
        "team_size_estimate": d.get("team_size_estimate"),
        "funding_info": _compute_funding_info(d.get("funding_stage"), d.get("funding_amount_usd")),
        "potential_data": _compute_potential_data(
            company.get("icp_segment"), company.get("status"), potential_cfg
        ),
        "last_info_update": _compute_last_info_update(company, dossier, aggregates),
        # service keys — required for writeback and body render
        "id": company.get("id"),
        "domain": company.get("domain"),
        "notion_page_id": company.get("notion_page_id"),
        "notion_synced_at": company.get("notion_synced_at"),
    }
```

- [ ] **Step 5.4: Run all notion_profile tests**

```bash
python -m pytest tests/test_notion_profile.py -v
```

Expected: all pass.

- [ ] **Step 5.5: Commit**

```bash
git add scripts/notion_profile.py tests/test_notion_profile.py
git commit -m "feat: add build_company_notion_profile with translator support"
```

---

## Task 6: notion_profile.py — build_company_profiles prefetch (TDD)

**Files:**
- Modify: `scripts/notion_profile.py`
- Modify: `tests/test_notion_profile.py`

- [ ] **Step 6.1: Add failing tests for build_company_profiles**

Append to `tests/test_notion_profile.py`:

```python
# ---------------------------------------------------------------------------
# build_company_profiles
# ---------------------------------------------------------------------------

class _CountingFakeDb:
    """Fake DB that counts fetch calls per table."""
    def __init__(self):
        self.fetch_calls: list[str] = []
        self.tables: dict[str, list[dict]] = {
            "dossiers": [
                {
                    "company_id": "co1",
                    "team_size_estimate": "11-50",
                    "funding_stage": "Series A",
                    "funding_amount_usd": 12_000_000,
                    "updated_at": "2026-06-10T00:00:00",
                }
            ],
            "research_records": [
                {"company_id": "co1", "created_at": "2026-06-15T00:00:00"},
                {"company_id": "co2", "created_at": "2026-06-01T00:00:00"},
            ],
            "contacts": [
                {"company_id": "co1", "updated_at": "2026-06-20T00:00:00"},
            ],
        }

    def fetch(self, table, status_filter=None):
        self.fetch_calls.append(table)
        return list(self.tables.get(table, []))


_COMPANIES_TWO = [
    {
        "id": "co1", "domain": "acme.ai", "name": "Acme", "website": "https://acme.ai",
        "linkedin_url": None, "icp_segment": "medical-imaging", "status": "relevant",
        "description": "Radiology AI.", "hq_country": "US",
        "notion_page_id": None, "notion_synced_at": None,
        "updated_at": "2026-06-01T00:00:00",
    },
    {
        "id": "co2", "domain": "beta.io", "name": "Beta", "website": "https://beta.io",
        "linkedin_url": None, "icp_segment": "generative-ai", "status": "analyzed",
        "description": "LLM platform.", "hq_country": None,
        "notion_page_id": None, "notion_synced_at": None,
        "updated_at": "2026-06-02T00:00:00",
    },
]


def test_build_company_profiles_constant_fetch_count():
    db = _CountingFakeDb()
    profiles = np_mod.build_company_profiles(_COMPANIES_TWO, db, _POTENTIAL_CFG)
    assert len(profiles) == 2
    assert db.fetch_calls.count("dossiers") == 1
    assert db.fetch_calls.count("research_records") == 1
    assert db.fetch_calls.count("contacts") == 1
    assert len(db.fetch_calls) == 3


def test_build_company_profiles_correct_dossier_lookup():
    db = _CountingFakeDb()
    profiles = np_mod.build_company_profiles(_COMPANIES_TWO, db, _POTENTIAL_CFG)
    co1 = next(p for p in profiles if p["domain"] == "acme.ai")
    assert co1["team_size_estimate"] == "11-50"
    assert co1["funding_info"] == "Series A · $12M"


def test_build_company_profiles_aggregates_max_dates():
    db = _CountingFakeDb()
    profiles = np_mod.build_company_profiles(_COMPANIES_TWO, db, _POTENTIAL_CFG)
    co1 = next(p for p in profiles if p["domain"] == "acme.ai")
    # research 2026-06-15 < contact 2026-06-20 → last_info_update = 2026-06-20
    assert co1["last_info_update"] == "2026-06-20"


def test_build_company_profiles_no_dossier_for_company():
    db = _CountingFakeDb()
    profiles = np_mod.build_company_profiles(_COMPANIES_TWO, db, _POTENTIAL_CFG)
    co2 = next(p for p in profiles if p["domain"] == "beta.io")
    assert co2["team_size_estimate"] is None
    assert co2["funding_info"] is None
```

- [ ] **Step 6.2: Run to confirm failures**

```bash
python -m pytest tests/test_notion_profile.py -k "build_company_profiles" -v 2>&1 | head -10
```

Expected: `AttributeError: module 'notion_profile' has no attribute 'build_company_profiles'`

- [ ] **Step 6.3: Implement build_company_profiles in scripts/notion_profile.py**

Append after `build_company_notion_profile`:

```python
def build_company_profiles(
    company_rows: list[dict],
    db,
    potential_cfg: dict,
    translator=None,
) -> list[dict]:
    """Prefetch all data in 3 constant-count queries, then build profiles in memory."""
    dossiers = db.fetch("dossiers")
    research_rows = db.fetch("research_records")
    contacts_rows = db.fetch("contacts")

    dossier_by_cid: dict[str, dict] = {
        d["company_id"]: d for d in dossiers if d.get("company_id")
    }

    max_research: dict[str, str] = {}
    for r in research_rows:
        cid = r.get("company_id")
        val = r.get("created_at")
        if cid and val:
            s = str(val)[:10]
            if s > max_research.get(cid, ""):
                max_research[cid] = s

    max_contact: dict[str, str] = {}
    for c in contacts_rows:
        cid = c.get("company_id")
        val = c.get("updated_at")
        if cid and val:
            s = str(val)[:10]
            if s > max_contact.get(cid, ""):
                max_contact[cid] = s

    profiles = []
    for company in company_rows:
        cid = company.get("id")
        aggregates = {
            "last_research_created_at": max_research.get(cid),
            "last_contact_updated_at": max_contact.get(cid),
        }
        profiles.append(
            build_company_notion_profile(
                company,
                dossier_by_cid.get(cid),
                aggregates,
                potential_cfg,
                translator=translator,
            )
        )
    return profiles
```

- [ ] **Step 6.4: Run all notion_profile tests**

```bash
python -m pytest tests/test_notion_profile.py -v
```

Expected: all pass.

- [ ] **Step 6.5: Commit**

```bash
git add scripts/notion_profile.py tests/test_notion_profile.py
git commit -m "feat: add build_company_profiles with N+1-free prefetch"
```

---

## Task 7: translate.py — get_or_translate (TDD)

**Files:**
- Create: `scripts/translate.py`
- Create: `tests/test_translate.py`

- [ ] **Step 7.1: Write failing tests**

Create `tests/test_translate.py`:

```python
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
```

- [ ] **Step 7.2: Run to confirm failures**

```bash
python -m pytest tests/test_translate.py -v 2>&1 | head -10
```

Expected: `ModuleNotFoundError: No module named 'translate'`

- [ ] **Step 7.3: Create scripts/translate.py**

```python
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
```

- [ ] **Step 7.4: Run all translate tests**

```bash
python -m pytest tests/test_translate.py -v
```

Expected: all 6 pass.

- [ ] **Step 7.5: Commit**

```bash
git add scripts/translate.py tests/test_translate.py
git commit -m "feat: add translate.py with get_or_translate and Translator gateway"
```

---

## Task 8: Update notion_mapping.yaml + fix broken tests

**Files:**
- Modify: `config/notion_mapping.yaml`
- Modify: `tests/test_notion_sync.py`

This task updates the YAML and the tests that check its exact shape in one atomic step so the test suite stays green.

- [ ] **Step 8.1: Rewrite config/notion_mapping.yaml**

Replace the entire file content:

```yaml
# Декларативный маппинг БД → Notion. Единственный рычаг настройки полей.
# direction: forward = БД авторитетна (БД→Notion); reverse = Notion авторитетен (Notion→БД).
# source: db_column | dossier | computed — откуда берётся значение (для build_company_profiles).
# Чтобы добавить поле: дописать строку + `notion_sync.py --ensure-schema`.
# Чтобы убрать: удалить строку (свойство в Notion остаётся, если не --prune).

companies:
  notion_database_id_env: NOTION_COMPANIES_DB_ID
  db_table: companies
  db_key: domain
  db_status_filter: [relevant, sources_gathered, analyzed, dossier_ready, data_partner]
  profile_builder: true
  fields:
    - { db_column: name,               notion_property: "Company Name",    notion_type: title,        direction: forward, source: db_column }
    - { db_column: website,            notion_property: "Website",         notion_type: url,          direction: forward, source: db_column }
    - { db_column: linkedin_url,       notion_property: "LinkedIn",        notion_type: url,          direction: forward, source: db_column }
    - { db_column: icp_segment,        notion_property: "ICP Segment",     notion_type: select,       direction: forward, source: db_column }
    - { db_column: status,             notion_property: "Pipeline Status", notion_type: select,       direction: forward, source: db_column }
    - { db_column: description,        notion_property: "AI Summary",      notion_type: rich_text,    direction: forward, source: db_column }
    - { db_column: funding_info,       notion_property: "Funding Info",    notion_type: rich_text,    direction: forward, source: computed }
    - { db_column: team_size_estimate, notion_property: "Team Size",       notion_type: select,       direction: forward, source: dossier }
    - { db_column: potential_data,     notion_property: "Potential Data",  notion_type: multi_select, direction: forward, source: computed }
    - { db_column: hq_country,         notion_property: "Country",         notion_type: select,       direction: forward, source: db_column }
    - { db_column: last_info_update,   notion_property: "Last Info Update",notion_type: date,         direction: forward, source: computed }

contacts:
  notion_database_id_env: NOTION_CONTACTS_DB_ID
  db_table: contacts
  db_key: id
  fields:
    - { db_column: name,             notion_property: "Name",           notion_type: title,        direction: forward }
    - { db_column: contact_type,     notion_property: "Contact Type",   notion_type: select,       direction: forward }
    - { db_column: info,             notion_property: "Contact Info",   notion_type: rich_text,    direction: forward }
    - { db_column: email,            notion_property: "Email",          notion_type: email,        direction: forward }
    - { db_column: phone,            notion_property: "Phone",          notion_type: phone_number, direction: forward }
    - { db_column: linkedin_url,     notion_property: "LinkedIn",       notion_type: url,          direction: forward }
    - { db_column: facebook_url,     notion_property: "Facebook",       notion_type: url,          direction: forward }
    - { db_column: instagram_url,    notion_property: "Instagram",      notion_type: url,          direction: forward }
    - { db_column: company_page_ids, notion_property: "Company",        notion_type: relation,     direction: forward }
    - { db_column: outreach_status,  notion_property: "Outreach Status",notion_type: select,       direction: forward }
    - { db_column: source,           notion_property: "Source",         notion_type: select,       direction: forward }
```

- [ ] **Step 8.2: Update test_companies_mapping_matches_release_schema in tests/test_notion_sync.py**

Find `test_companies_mapping_matches_release_schema` (around line 357) and replace the entire function:

```python
def test_companies_mapping_matches_release_schema():
    mapping = ns.load_mapping()
    fields = {f["db_column"]: f for f in mapping["companies"]["fields"]}

    expected_columns = {
        "name", "website", "linkedin_url", "icp_segment", "status",
        "description", "funding_info", "team_size_estimate", "potential_data",
        "hq_country", "last_info_update",
    }
    assert set(fields.keys()) == expected_columns
    assert fields["name"]["notion_property"] == "Company Name"
    assert fields["name"]["notion_type"] == "title"
    assert fields["description"]["notion_property"] == "AI Summary"
    assert fields["funding_info"]["source"] == "computed"
    assert fields["team_size_estimate"]["source"] == "dossier"
    assert fields["potential_data"]["notion_type"] == "multi_select"
    assert fields["last_info_update"]["notion_type"] == "date"
    assert mapping["companies"].get("profile_builder") is True
    for f in mapping["companies"]["fields"]:
        assert f["direction"] == "forward"
```

- [ ] **Step 8.3: Update test_contacts_mapping_matches_compact_schema in tests/test_notion_sync.py**

Find `test_contacts_mapping_matches_compact_schema` (around line 341) and replace:

```python
def test_contacts_mapping_matches_compact_schema():
    mapping = ns.load_mapping()
    contacts_fields = {f["notion_property"] for f in mapping["contacts"]["fields"]}
    assert contacts_fields == {
        "Name",
        "Contact Type",
        "Contact Info",
        "Email",
        "Phone",
        "LinkedIn",
        "Facebook",
        "Instagram",
        "Company",
        "Outreach Status",
        "Source",
    }
```

- [ ] **Step 8.4: Update test_contacts_mapping_has_company_relation_and_name in tests/test_notion_sync.py**

Find `test_contacts_mapping_has_company_relation_and_name` (around line 21) and replace:

```python
def test_contacts_mapping_has_company_relation_and_name():
    mapping = ns.load_mapping()
    fields = mapping["contacts"]["fields"]
    by_column = {field["db_column"]: field for field in fields}

    assert by_column["company_page_ids"]["notion_type"] == "relation"
    assert by_column["company_page_ids"]["notion_property"] == "Company"
    assert by_column["name"]["notion_property"] == "Name"
    assert by_column["contact_type"]["notion_type"] == "select"
    assert "contact" + "_result" not in by_column
```

- [ ] **Step 8.5: Verify no dossiers entity in mapping**

Add a new test at the bottom of `tests/test_notion_sync.py`:

```python
def test_no_dossiers_entity_in_mapping():
    mapping = ns.load_mapping()
    assert "dossiers" not in mapping
```

- [ ] **Step 8.6: Run the mapping-related tests**

```bash
python -m pytest tests/test_notion_sync.py -k "mapping" -v
```

Expected: all pass (including the new `test_no_dossiers_entity_in_mapping`).

- [ ] **Step 8.7: Commit**

```bash
git add config/notion_mapping.yaml tests/test_notion_sync.py
git commit -m "feat: update notion_mapping.yaml to 11-field companies schema and English contacts"
```

---

## Task 9: validate_mapping — accept source, reject computed+reverse

**Files:**
- Modify: `scripts/notion_sync.py`
- Modify: `tests/test_notion_sync.py`

- [ ] **Step 9.1: Add failing tests for new validate_mapping rules**

Append to `tests/test_notion_sync.py`:

```python
def test_validate_mapping_accepts_source_field():
    mapping = {
        "companies": {
            "notion_database_id_env": "NOTION_COMPANIES_DB_ID",
            "fields": [
                {"db_column": "name", "notion_property": "Name",
                 "notion_type": "title", "direction": "forward", "source": "db_column"},
                {"db_column": "funding_info", "notion_property": "Funding Info",
                 "notion_type": "rich_text", "direction": "forward", "source": "computed"},
            ],
        }
    }
    errors = ns.validate_mapping(mapping)
    assert errors == []


def test_validate_mapping_rejects_computed_with_reverse():
    mapping = {
        "companies": {
            "notion_database_id_env": "NOTION_COMPANIES_DB_ID",
            "fields": [
                {"db_column": "funding_info", "notion_property": "Funding Info",
                 "notion_type": "rich_text", "direction": "reverse", "source": "computed"},
            ],
        }
    }
    errors = ns.validate_mapping(mapping)
    assert any("computed" in e and "reverse" in e for e in errors)
```

- [ ] **Step 9.2: Run to confirm failures**

```bash
python -m pytest tests/test_notion_sync.py -k "validate_mapping_accepts_source or validate_mapping_rejects_computed" -v
```

Expected: `test_validate_mapping_rejects_computed_with_reverse` FAILS (no such error raised yet).

- [ ] **Step 9.3: Update validate_mapping in scripts/notion_sync.py**

In `scripts/notion_sync.py`, find the `validate_mapping` function and add a source check inside the `for f in cfg.get("fields", []):` loop, after the direction check:

```python
def validate_mapping(mapping: dict) -> list[str]:
    """Возвращает список ошибок конфига (пустой = валиден)."""
    errors: list[str] = []
    for entity, cfg in mapping.items():
        if "notion_database_id_env" not in cfg:
            errors.append(f"{entity}: отсутствует notion_database_id_env")
        for f in cfg.get("fields", []):
            col = f.get("db_column", "<?>")
            nt = f.get("notion_type")
            direction = f.get("direction")
            source = f.get("source")
            if nt not in VALID_NOTION_TYPES:
                errors.append(f"{entity}.{col}: недопустимый notion_type '{nt}'")
            if direction not in VALID_DIRECTIONS:
                errors.append(f"{entity}.{col}: недопустимый direction '{direction}'")
            if source == "computed" and direction == "reverse":
                errors.append(
                    f"{entity}.{col}: computed-поле не может иметь direction=reverse"
                )
    return errors
```

- [ ] **Step 9.4: Run validate_mapping tests**

```bash
python -m pytest tests/test_notion_sync.py -k "validate_mapping" -v
```

Expected: all pass.

- [ ] **Step 9.5: Commit**

```bash
git add scripts/notion_sync.py tests/test_notion_sync.py
git commit -m "feat: validate_mapping accepts source field, rejects computed+reverse"
```

---

## Task 10: Wire profile builder into sync_forward + test

**Files:**
- Modify: `scripts/notion_sync.py`
- Modify: `tests/test_notion_sync.py`

- [ ] **Step 10.1: Add failing integration test for profile builder in sync_forward**

Append to `tests/test_notion_sync.py`:

```python
COMPANIES_PROFILE_MAPPING = {
    "companies": {
        "notion_database_id_env": "NOTION_COMPANIES_DB_ID",
        "db_table": "companies",
        "db_key": "domain",
        "db_status_filter": ["relevant"],
        "profile_builder": True,
        "fields": [
            {"db_column": "name",           "notion_property": "Company Name",   "notion_type": "title",        "direction": "forward", "source": "db_column"},
            {"db_column": "icp_segment",    "notion_property": "ICP Segment",    "notion_type": "select",       "direction": "forward", "source": "db_column"},
            {"db_column": "funding_info",   "notion_property": "Funding Info",   "notion_type": "rich_text",    "direction": "forward", "source": "computed"},
            {"db_column": "potential_data", "notion_property": "Potential Data", "notion_type": "multi_select", "direction": "forward", "source": "computed"},
        ],
    }
}

_PROFILE_POTENTIAL_CFG = {
    "segments": {"medical-imaging": ["Medical Data", "Images"]},
    "status_overrides": {},
}


def test_forward_with_profile_builder_creates_page_with_computed_fields():
    notion = FakeNotion()
    notion.databases["DBID"] = {"properties": {"Company Name": {"type": "title"}}}

    class ProfileFakeDb(FakeDb):
        def __init__(self, rows):
            super().__init__(rows)
            self.tables.setdefault("dossiers", [
                {"company_id": "co-uuid", "funding_stage": "Series A",
                 "funding_amount_usd": 12_000_000, "team_size_estimate": "11-50",
                 "updated_at": "2026-06-10T00:00:00"}
            ])
            self.tables.setdefault("research_records", [])
            self.tables.setdefault("contacts", [])

        def fetch(self, table, status_filter=None):
            rows = self.tables.get(table, [])
            if status_filter:
                rows = [r for r in rows if r.get("status") in status_filter]
            return list(rows)

    rows = [{"id": "co-uuid", "domain": "acme.ai", "name": "Acme", "website": "https://acme.ai",
             "linkedin_url": None, "icp_segment": "medical-imaging", "status": "relevant",
             "description": "Radiology AI", "hq_country": "US",
             "notion_page_id": None, "notion_synced_at": None,
             "updated_at": "2026-06-01T00:00:00"}]

    db = ProfileFakeDb(rows)
    sync = ns.NotionSync(
        notion=notion, db=db,
        mapping=COMPANIES_PROFILE_MAPPING,
        env={"NOTION_COMPANIES_DB_ID": "DBID"},
    )

    # Patch load_potential_cfg to return test config
    import notion_profile as np_mod
    original = np_mod.load_potential_cfg
    np_mod.load_potential_cfg = lambda: _PROFILE_POTENTIAL_CFG
    try:
        result = sync.sync_forward("companies")
    finally:
        np_mod.load_potential_cfg = original

    assert result["created"] == 1
    page_id = db.tables["companies"][0]["notion_page_id"]
    assert page_id is not None
    props = notion.pages[page_id]["properties"]
    assert props["Company Name"] == {"title": [{"text": {"content": "Acme"}}]}
    assert props["Funding Info"] == {"rich_text": [{"text": {"content": "Series A · $12M"}}]}
    assert props["Potential Data"] == {"multi_select": [{"name": "Medical Data"}, {"name": "Images"}]}
```

- [ ] **Step 10.2: Run to confirm failure**

```bash
python -m pytest tests/test_notion_sync.py::test_forward_with_profile_builder_creates_page_with_computed_fields -v
```

Expected: FAIL — profile builder not yet called.

- [ ] **Step 10.3: Update NotionSync.__init__ to accept translator + wire profile builder in sync_forward**

In `scripts/notion_sync.py`, replace `NotionSync.__init__`:

```python
class NotionSync:
    def __init__(self, notion, db, mapping=None, env=None, translator=None):
        self.notion = notion
        self.db = db
        self.mapping = mapping if mapping is not None else load_mapping()
        self.env = env if env is not None else os.environ
        self.translator = translator
```

In `sync_forward`, replace the section after `rows = self.db.fetch(...)`:

```python
    def sync_forward(self, entity, dry_run=False) -> dict:
        cfg = self._cfg(entity)
        db_id = self._db_id(entity)
        fields = self._fields(entity, "forward")
        rows = self.db.fetch(cfg["db_table"], cfg.get("db_status_filter"))
        if entity == "contacts":
            rows = enrich_contact_rows(rows, self.db)
        elif cfg.get("profile_builder"):
            from notion_profile import build_company_profiles, load_potential_cfg  # noqa: PLC0415
            potential_cfg = load_potential_cfg()
            rows = build_company_profiles(rows, self.db, potential_cfg,
                                          translator=self.translator)
        created = updated = errors = 0
        # ... rest unchanged
```

- [ ] **Step 10.4: Run the integration test**

```bash
python -m pytest tests/test_notion_sync.py::test_forward_with_profile_builder_creates_page_with_computed_fields -v
```

Expected: PASS.

- [ ] **Step 10.5: Run full test_notion_sync.py**

```bash
python -m pytest tests/test_notion_sync.py -v
```

Expected: all pass.

- [ ] **Step 10.6: Commit**

```bash
git add scripts/notion_sync.py tests/test_notion_sync.py
git commit -m "feat: wire profile builder into sync_forward when profile_builder=true"
```

---

## Task 11: Wire translator into sync_dossiers

**Files:**
- Modify: `scripts/notion_sync.py`
- Modify: `tests/test_notion_sync.py`

- [ ] **Step 11.1: Add failing test for dossier translation**

Append to `tests/test_notion_sync.py`:

```python
def test_sync_dossiers_translates_prose_via_translator():
    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {}, "children": []}
    db = FakeDb([])
    db.tables["companies"] = [{"id": "cid", "domain": "acme.com", "notion_page_id": "page-1"}]
    db.tables["dossiers"] = [{
        "company_id": "cid",
        "summary_md": "Summary text",
        "section_summaries": {"financials": "Seed funding."},
        "audit_md": "Audit content",
    }]

    class StubTranslator:
        def translate(self, text: str) -> str:
            return f"RU:{text}"

    sync = ns.NotionSync(
        notion=notion, db=db, mapping=COMPANIES_MAPPING,
        env={"NOTION_COMPANIES_DB_ID": "DBID"},
        translator=StubTranslator(),
    )
    sync.sync_dossiers()
    children = notion.pages["page-1"]["children"]
    texts = [
        seg["text"]["content"]
        for b in children if b.get("type") in ("heading_2", "paragraph")
        for seg in b.get(b["type"], {}).get("rich_text", [])
    ]
    assert any("RU:Summary text" in t for t in texts)
    assert any("RU:Seed funding." in t for t in texts)
    assert any("RU:Audit content" in t for t in texts)
```

- [ ] **Step 11.2: Run to confirm failure**

```bash
python -m pytest tests/test_notion_sync.py::test_sync_dossiers_translates_prose_via_translator -v
```

Expected: FAIL — no translation happening.

- [ ] **Step 11.3: Update sync_dossiers in scripts/notion_sync.py to translate prose**

Replace `sync_dossiers` body (the inner `try` block) with:

```python
    def sync_dossiers(self, dry_run=False) -> dict:
        """Append typed dossier summaries and narrative to the company page."""
        companies = {c["id"]: c for c in self.db.fetch("companies")
                     if c.get("notion_page_id")}
        dossiers = self.db.fetch("dossiers")
        updated = errors = 0

        def _t(text):
            if self.translator and text:
                return self.translator.translate(text)
            return text

        for d in dossiers:
            company = companies.get(d.get("company_id"))
            if not company:
                continue
            try:
                blocks = []
                if d.get("summary_md"):
                    blocks += md_to_blocks("Досье — саммари", _t(d["summary_md"]))
                for section, body in (d.get("section_summaries") or {}).items():
                    if body:
                        blocks += md_to_blocks(str(section), _t(str(body)))
                if d.get("audit_md"):
                    blocks += md_to_blocks("Аудит", _t(d["audit_md"]))
                if blocks and not dry_run:
                    self.notion.append_children(company["notion_page_id"], blocks)
                if blocks:
                    updated += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("dossier %s: %s", d.get("company_id"), exc)
                errors += 1
        return {"entity": "dossiers", "updated": updated, "errors": errors}
```

- [ ] **Step 11.4: Run dossier-related tests**

```bash
python -m pytest tests/test_notion_sync.py -k "dossier" -v
```

Expected: all pass.

- [ ] **Step 11.5: Commit**

```bash
git add scripts/notion_sync.py tests/test_notion_sync.py
git commit -m "feat: sync_dossiers translates prose via injected translator"
```

---

## Task 12: Wire translator into render_and_write_body

**Files:**
- Modify: `scripts/notion_render.py`
- Modify: `tests/test_notion_render.py`

- [ ] **Step 12.1: Add failing test for render translation**

Append to `tests/test_notion_render.py`:

```python
def test_render_and_write_body_translates_dossier_prose():
    written_blocks: list[dict] = []

    class FakeNotionGW:
        def list_block_children(self, page_id): return []
        def delete_block(self, block_id): pass
        def append_children(self, page_id, children):
            written_blocks.extend(children)

    class FakeDbGW:
        def fetch_one_by_id(self, table, id_value):
            return {"id": "co-uuid", "name": "Acme", "status": "relevant",
                    "description": "Radiology AI", "updated_at": "2026-06-01"}
        def fetch_for_company(self, table, company_id):
            if table == "dossiers":
                return [{
                    "company_id": "co-uuid",
                    "summary_md": "Summary text",
                    "section_summaries": {"financials": "Seed."},
                    "audit_md": "Audit text",
                }]
            return []
        def fetch_news_for_company(self, company_id, limit=10): return []

    class StubTranslator:
        def translate(self, text: str) -> str:
            return f"RU:{text}"

    class FakeSync:
        notion = FakeNotionGW()
        db = FakeDbGW()
        translator = StubTranslator()

    nr.render_and_write_body(FakeSync(), "co-uuid", "page-1")

    all_text = []
    for blk in written_blocks:
        for rt_key in ("heading_2", "paragraph", "quote"):
            for seg in blk.get(rt_key, {}).get("rich_text", []):
                all_text.append(seg.get("text", {}).get("content", ""))
        if blk.get("type") == "callout":
            for child in blk.get("callout", {}).get("children", []):
                for seg in child.get("paragraph", {}).get("rich_text", []):
                    all_text.append(seg.get("text", {}).get("content", ""))

    joined = " ".join(all_text)
    assert "RU:Summary text" in joined or any("RU:" in t for t in all_text)
```

- [ ] **Step 12.2: Run to confirm failure**

```bash
python -m pytest tests/test_notion_render.py::test_render_and_write_body_translates_dossier_prose -v
```

Expected: FAIL — no translation.

- [ ] **Step 12.3: Update render_and_write_body in scripts/notion_render.py**

Replace the `render_and_write_body` function:

```python
def render_and_write_body(
    sync,          # NotionSync instance with .db, .notion, and optionally .translator
    company_id: str,
    page_id: str,
    refresh: bool = False,
) -> None:
    """Fetch data from DB, build blocks, write to Notion.

    If refresh=True, delete all existing page blocks first.
    Translates dossier prose via sync.translator if present.
    """
    company = sync.db.fetch_one_by_id("companies", company_id) or {}
    dossier_rows = sync.db.fetch_for_company("dossiers", company_id)
    dossier = dossier_rows[0] if dossier_rows else None

    translator = getattr(sync, "translator", None)

    if dossier and translator:
        def _t(text):
            return translator.translate(text) if text else text

        dossier = {
            **dossier,
            "summary_md": _t(dossier.get("summary_md")),
            "section_summaries": {
                k: _t(v)
                for k, v in (dossier.get("section_summaries") or {}).items()
            },
            "audit_md": _t(dossier.get("audit_md")),
        }

    analysis_rows = sync.db.fetch_for_company("analysis_records", company_id)
    analysis: dict[str, dict] = {row["section"]: row for row in analysis_rows}

    contacts = sync.db.fetch_for_company("contacts", company_id)
    news = sync.db.fetch_news_for_company(company_id)

    blocks = build_page_blocks(company, dossier, analysis, contacts, news)
    if not blocks:
        return

    if refresh:
        existing = sync.notion.list_block_children(page_id)
        for blk in existing:
            sync.notion.delete_block(blk["id"])

    sync.notion.append_children(page_id, blocks)
```

- [ ] **Step 12.4: Run the new render test**

```bash
python -m pytest tests/test_notion_render.py -v
```

Expected: all pass.

- [ ] **Step 12.5: Commit**

```bash
git add scripts/notion_render.py tests/test_notion_render.py
git commit -m "feat: render_and_write_body translates dossier prose via sync.translator"
```

---

## Task 13: Full test suite

- [ ] **Step 13.1: Run all tests**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent/.claude/worktrees/strange-gauss-feb25d
python -m pytest tests/ -v --tb=short 2>&1 | tail -40
```

Expected: all tests pass, no failures.

- [ ] **Step 13.2: If any failures, investigate**

Common failure patterns:
- `test_companies_mapping_matches_release_schema`: check if Task 8.2 was applied correctly.
- Import errors in `test_notion_profile.py`: ensure `scripts/` is in sys.path (check `tests/conftest.py` — it already adds `scripts/` via `sys.path.insert`).
- `test_sync_dossiers_reads_typed_fields`: uses `COMPANIES_MAPPING` which has no `profile_builder`, so no translation expected — should still pass.

- [ ] **Step 13.3: Update ARCHITECTURE.md**

Add the following to the relevant sections of `ARCHITECTURE.md`:

Under "Схема базы данных":
- `companies`: добавлены `hq_country text`, `hq_location text`
- `contacts`: добавлены `source text`, `outreach_status text NOT NULL DEFAULT 'new'`
- Новая таблица `translations(source_hash, target_lang, source_text, translated_text, model, created_at)`

Under "Скрипты" или аналогичный раздел:
- `scripts/notion_profile.py` — чистый profile builder без I/O. `build_company_profiles(rows, db, potential_cfg, translator)` делает 3 запроса к БД независимо от числа компаний. `build_company_notion_profile` — чистая функция. `_format_amount`, `_compute_funding_info`, `_compute_potential_data`, `_compute_last_info_update` — вычисляемые поля.
- `scripts/translate.py` — кэш-переводчик. `get_or_translate(store, text, backend, lang)` хэширует текст, ищет в `translations`, при промахе вызывает backend. `Translator` — gateway, инжектируется в `NotionSync` и `render_and_write_body`.
- `config/potential_data.yaml` — маппинг icp_segment → Potential Data values + status_overrides.

Under "notion_sync.py":
- `NotionSync.__init__` теперь принимает `translator=None`
- `sync_forward`: при `profile_builder: true` заменяет строки на `build_company_profiles(...)`
- `sync_dossiers`: переводит `summary_md`, секции, `audit_md` через `self.translator`
- `validate_mapping`: принимает опциональный ключ `source`; computed+reverse → ошибка

- [ ] **Step 13.4: Commit ARCHITECTURE.md**

```bash
git add ARCHITECTURE.md
git commit -m "docs: update ARCHITECTURE.md for profile builder, translator, new DB fields"
```

---

## Self-review checklist

- [x] **Spec coverage:**
  - ✅ `hq_country/hq_location`, `contacts.source/outreach_status`, `translations` table — Task 1
  - ✅ `potential_data.yaml` — Task 2
  - ✅ `_format_amount` with $K/$M/$B format — Task 3
  - ✅ `funding_info` 4 branches — Task 3
  - ✅ `potential_data` union + dedup + unknown segment → [] — Task 4
  - ✅ `last_info_update` max across sources, None ignored — Task 4
  - ✅ `build_company_notion_profile` service keys preserved — Task 5
  - ✅ translator translates description only (not select/url) — Task 5
  - ✅ `build_company_profiles` constant 3 fetches (N+1 guard) — Task 6
  - ✅ `get_or_translate` cache hit/miss, dedup — Task 7
  - ✅ `Translator` class with empty/None passthrough — Task 7
  - ✅ `notion_mapping.yaml` 11 companies fields + `profile_builder: true` — Task 8
  - ✅ contacts English names + outreach_status/source — Task 8
  - ✅ dossiers entity removed — Task 8
  - ✅ `validate_mapping` accepts `source`, rejects computed+reverse — Task 9
  - ✅ `sync_forward` calls profile builder — Task 10
  - ✅ `sync_dossiers` translates prose — Task 11
  - ✅ `render_and_write_body` translates dossier prose — Task 12
  - ✅ `ensure_schema` untouched (reads `fields` as before, will create new props) — implicit
  - ✅ `sync_reverse` for companies is no-op (no reverse fields in mapping) — implicit in new YAML
  - ✅ Tests offline with stub translator — Tasks 5, 7, 10, 11, 12

- [x] **Placeholder scan:** all steps have concrete code, no TBDs.

- [x] **Type consistency:**
  - `_compute_potential_data(icp_segment, status, potential_cfg)` — consistent across Tasks 4, 5, 6
  - `build_company_notion_profile(company, dossier, aggregates, potential_cfg, translator=None)` — consistent across Tasks 5, 6
  - `build_company_profiles(company_rows, db, potential_cfg, translator=None)` — consistent across Tasks 6, 10
  - `Translator.translate(text)` — consistent across Tasks 7, 5, 11, 12
