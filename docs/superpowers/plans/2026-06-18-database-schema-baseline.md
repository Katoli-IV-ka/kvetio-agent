# Database Schema Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace historical test-era SQL migrations with one current baseline schema and make audits/tests use that baseline as the only schema contract.

**Architecture:** The project will stop treating `sql/*.sql` as an ordered migration history. A single `sql/schema.sql` will define the current clean runtime schema from scratch. Tests will validate the baseline file and no longer assert behavior of deleted historical migrations.

**Tech Stack:** PostgreSQL/Supabase SQL, Python 3.11, pytest, repository markdown docs.

---

## File Structure

- Delete: `sql/001_init.sql`
- Delete: `sql/003_source_page_url.sql`
- Delete: `sql/004_signals_source_page_url.sql`
- Delete: `sql/005_discover_verify_fields.sql`
- Delete: `sql/006_contacts.sql`
- Delete: `sql/007_dm_enriched_at.sql`
- Delete: `sql/008_source_links.sql`
- Delete: `sql/009_analysis_notes.sql`
- Delete: `sql/010_dossiers.sql`
- Delete: `sql/011_contacts_personal_website.sql`
- Delete: `sql/011_notion_sync_fields.sql`
- Delete: `sql/012_bot.sql`
- Delete: `sql/013_contacts_v2.sql`
- Delete: `sql/014_drop_pipeline_runs.sql`
- Delete: `sql/015_drop_bot_runtime_state.sql`
- Delete: `sql/015_drop_unused_db_objects.sql`
- Delete: `sql/016_bot_default_limit_5.sql`
- Delete: `sql/017_agent_database_cleanup.sql`
- Create: `sql/schema.sql`
- Replace: `tests/test_migrations.py` with current baseline schema tests
- Modify: `docs/DB-FIELD-AUDIT-2026-06-18.md`
- Modify: `docs/AGENT-ECOSYSTEM.md`
- Modify: `README.md`

## Task 1: Add Baseline Schema Contract Test

**Files:**
- Modify: `tests/test_migrations.py`
- Create later: `sql/schema.sql`

- [ ] **Step 1: Replace migration-history tests with baseline tests**

Replace the full contents of `tests/test_migrations.py` with:

```python
"""Contract tests for the current database baseline schema.

The project no longer keeps test-era migration history. `sql/schema.sql` is the
single source of truth for creating the current clean Supabase schema.
"""

from __future__ import annotations

from pathlib import Path

SQL_DIR = Path(__file__).parent.parent / "sql"
SCHEMA = SQL_DIR / "schema.sql"


def _schema() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def test_schema_file_is_the_only_active_sql_contract() -> None:
    sql_files = sorted(path.name for path in SQL_DIR.glob("*.sql"))
    assert sql_files == ["schema.sql"]


def test_schema_creates_current_runtime_tables() -> None:
    sql = _schema()
    for table in (
        "companies",
        "signals",
        "run_logs",
        "contacts",
        "source_links",
        "analysis_notes",
        "dossiers",
    ):
        assert f"CREATE TABLE {table}" in sql


def test_schema_does_not_create_removed_runtime_objects() -> None:
    sql = _schema()
    removed_objects = (
        "pipeline_runs",
        "bot_users",
        "bot_dialog_state",
        "bot_presets",
        "contact_companies",
        "github_org_cache",
        "recent_leads",
        "pipeline_stats",
    )
    for name in removed_objects:
        assert name not in sql


def test_companies_status_contract_is_current() -> None:
    sql = _schema()
    assert "status TEXT NOT NULL DEFAULT 'discovered'" in sql
    for status in (
        "discovered",
        "relevant",
        "not_relevant",
        "manual_review",
        "sources_gathered",
        "analyzed",
        "dossier_ready",
    ):
        assert f"'{status}'" in sql
    for legacy_status in ("qualified", "triaged_out", "pending_enrich", "enriched", "Researching"):
        assert legacy_status not in sql


def test_removed_company_fields_are_not_in_schema() -> None:
    sql = _schema()
    for column in (
        "score",
        "score_bucket",
        "score_version",
        "ai_direction",
        "sources JSONB",
        "latest_signal",
        "reject_reason",
        "outreach_status",
        "outreach_note",
        "source_page_url",
    ):
        assert column not in sql


def test_contacts_use_company_id_without_removed_crm_fields() -> None:
    sql = _schema()
    assert "company_id UUID NOT NULL" in sql
    assert "REFERENCES companies(id)" in sql
    assert "company_domain TEXT NOT NULL" in sql
    assert "notion_page_id TEXT" in sql
    assert "notion_synced_at TIMESTAMPTZ" in sql
    assert "contact_result" not in sql
    assert "outreach_status" not in sql
    assert "outreach_note" not in sql


def test_contact_constraints_match_runtime_code() -> None:
    sql = _schema()
    for email_status in ("verified", "guessed", "bounced", "unknown", "scraped"):
        assert f"'{email_status}'" in sql
    for invalid_hunter_status in ("'valid'", "'invalid'", "'accept_all'"):
        assert invalid_hunter_status not in sql
    for source_vector in ("github", "huggingface", "team_page", "apollo", "wellfound", "arxiv", "contact_page"):
        assert f"'{source_vector}'" in sql
    assert "'Related Person'" in sql


def test_deep_analysis_tables_have_expected_unique_keys() -> None:
    sql = _schema()
    assert "UNIQUE (company_domain, kind, url)" in sql
    assert "UNIQUE (company_domain, section, version)" in sql
    assert "company_domain TEXT PRIMARY KEY" in sql
```

- [ ] **Step 2: Run the new test and verify it fails**

Run:

```bash
python3 -m pytest tests/test_migrations.py -q
```

Expected: fail because `sql/schema.sql` does not exist yet and old SQL files are still present.

## Task 2: Create Current Baseline Schema

**Files:**
- Create: `sql/schema.sql`

- [ ] **Step 1: Add the current baseline schema**

Create `sql/schema.sql` with:

```sql
-- Kvetio Agent current Supabase baseline schema.
-- This is the only active SQL schema contract.
-- Historical test-era migrations were intentionally removed on 2026-06-18.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    website TEXT NOT NULL,
    linkedin_url TEXT,
    notion_page_id TEXT,
    status TEXT NOT NULL DEFAULT 'discovered'
        CHECK (status IN (
            'discovered',
            'relevant',
            'not_relevant',
            'manual_review',
            'sources_gathered',
            'analyzed',
            'dossier_ready'
        )),
    last_signal_date DATE,
    last_verified DATE,
    icp_segment TEXT,
    funding_stage TEXT,
    funding_amount TEXT,
    funding_date DATE,
    team_size TEXT,
    site_note TEXT,
    website_snippet TEXT,
    description TEXT,
    dm_enriched_at TIMESTAMPTZ,
    notion_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_companies_status ON companies (status);
CREATE INDEX idx_companies_domain ON companies (domain);
CREATE INDEX idx_companies_manual_review
    ON companies (status)
    WHERE status = 'manual_review';
CREATE INDEX idx_companies_dm_enrichment
    ON companies (status, dm_enriched_at)
    WHERE status IN ('relevant', 'sources_gathered', 'analyzed', 'dossier_ready');

DROP TRIGGER IF EXISTS trg_companies_updated_at ON companies;
CREATE TRIGGER trg_companies_updated_at
BEFORE UPDATE ON companies
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    company_name TEXT NOT NULL,
    domain TEXT,
    normalized_domain TEXT,
    linkedin_url TEXT,
    evidence_url TEXT UNIQUE NOT NULL,
    signal_date DATE NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high', 'medium', 'low')),
    parser_version TEXT,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_signals_normalized_domain ON signals (normalized_domain);
CREATE INDEX idx_signals_signal_date ON signals (signal_date DESC);
CREATE INDEX idx_signals_signal_type ON signals (signal_type);

CREATE TABLE run_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    companies_found INTEGER NOT NULL DEFAULT 0,
    companies_enriched INTEGER NOT NULL DEFAULT 0,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes TEXT
);

CREATE INDEX idx_run_logs_task_name ON run_logs (task_name);
CREATE INDEX idx_run_logs_started_at ON run_logs (started_at DESC);

CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id),
    company_domain TEXT NOT NULL,
    full_name TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    title TEXT,
    title_normalized TEXT,
    dm_priority INTEGER NOT NULL DEFAULT 2
        CHECK (dm_priority BETWEEN 1 AND 3),
    email TEXT,
    email_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (email_status IN ('verified', 'guessed', 'bounced', 'unknown', 'scraped')),
    email_source TEXT,
    linkedin_url TEXT,
    twitter_handle TEXT,
    github_username TEXT,
    hf_username TEXT,
    personal_website TEXT,
    source_vector TEXT NOT NULL DEFAULT 'github'
        CHECK (source_vector IN (
            'github',
            'huggingface',
            'team_page',
            'apollo',
            'wellfound',
            'arxiv',
            'contact_page'
        )),
    source_url TEXT,
    confidence TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high', 'medium', 'low')),
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    notion_page_id TEXT,
    notion_synced_at TIMESTAMPTZ,
    contact_type TEXT NOT NULL DEFAULT 'Person'
        CHECK (contact_type IN ('Person', 'Company', 'Related Person', 'Other')),
    phone TEXT,
    instagram_url TEXT,
    facebook_url TEXT,
    info TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_contacts_dedup
    ON contacts (company_domain, lower(full_name));
CREATE UNIQUE INDEX idx_contacts_upsert_key
    ON contacts (company_domain, full_name);
CREATE INDEX idx_contacts_company_domain
    ON contacts (company_domain);
CREATE INDEX idx_contacts_company_id
    ON contacts (company_id);
CREATE INDEX idx_contacts_priority
    ON contacts (dm_priority, company_domain);
CREATE INDEX idx_contacts_email_status
    ON contacts (email_status)
    WHERE email IS NOT NULL;
CREATE INDEX idx_contacts_source_vector
    ON contacts (source_vector);

DROP TRIGGER IF EXISTS trg_contacts_updated_at ON contacts;
CREATE TRIGGER trg_contacts_updated_at
BEFORE UPDATE ON contacts
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE source_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_domain TEXT NOT NULL,
    kind TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'unknown',
    confidence TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high', 'medium', 'low')),
    found_via TEXT,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_domain, kind, url)
);

CREATE INDEX idx_source_links_company ON source_links (company_domain);
CREATE INDEX idx_source_links_kind ON source_links (kind);

CREATE TABLE analysis_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_domain TEXT NOT NULL,
    section TEXT NOT NULL
        CHECK (section IN ('company', 'product', 'collaboration', 'financials', 'news', 'audit')),
    facts JSONB NOT NULL DEFAULT '{}'::jsonb,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high', 'medium', 'low')),
    model TEXT,
    version TEXT NOT NULL DEFAULT 'v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_domain, section, version)
);

CREATE INDEX idx_analysis_notes_company ON analysis_notes (company_domain);

CREATE TABLE dossiers (
    company_domain TEXT PRIMARY KEY,
    summary_md TEXT,
    sections JSONB NOT NULL DEFAULT '{}'::jsonb,
    audit_md TEXT,
    table_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    version TEXT NOT NULL DEFAULT 'v1',
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

- [ ] **Step 2: Run the baseline test and verify partial failure**

Run:

```bash
python3 -m pytest tests/test_migrations.py -q
```

Expected: fail only because old `sql/*.sql` files still exist.

## Task 3: Delete Historical SQL Migrations

**Files:**
- Delete all old SQL files listed in File Structure

- [ ] **Step 1: Delete old migration files**

Run:

```bash
rm sql/001_init.sql \
  sql/003_source_page_url.sql \
  sql/004_signals_source_page_url.sql \
  sql/005_discover_verify_fields.sql \
  sql/006_contacts.sql \
  sql/007_dm_enriched_at.sql \
  sql/008_source_links.sql \
  sql/009_analysis_notes.sql \
  sql/010_dossiers.sql \
  sql/011_contacts_personal_website.sql \
  sql/011_notion_sync_fields.sql \
  sql/012_bot.sql \
  sql/013_contacts_v2.sql \
  sql/014_drop_pipeline_runs.sql \
  sql/015_drop_bot_runtime_state.sql \
  sql/015_drop_unused_db_objects.sql \
  sql/016_bot_default_limit_5.sql \
  sql/017_agent_database_cleanup.sql
```

- [ ] **Step 2: Verify only the baseline SQL remains**

Run:

```bash
find sql -maxdepth 1 -type f -name '*.sql' -print | sort
```

Expected:

```text
sql/schema.sql
```

- [ ] **Step 3: Run schema tests**

Run:

```bash
python3 -m pytest tests/test_migrations.py -q
```

Expected: pass.

## Task 4: Update Documentation To Treat Baseline As Source Of Truth

**Files:**
- Modify: `README.md`
- Modify: `docs/AGENT-ECOSYSTEM.md`
- Modify: `docs/DB-FIELD-AUDIT-2026-06-18.md`

- [ ] **Step 1: Update `README.md` SQL section**

In `README.md`, add this paragraph under the architecture constraints:

```markdown
- `sql/schema.sql` is the only active database schema contract. The old
  test-era migration history was removed; current development starts from this
  baseline.
```

- [ ] **Step 2: Update `docs/AGENT-ECOSYSTEM.md` schema wording**

Replace the `## Cleanup Migration` section with:

```markdown
## Database Schema

`sql/schema.sql` is the only active database schema contract. Historical
test-era migrations were removed because they no longer represent production
history and were creating false audit signals.

The baseline schema:

- creates the seven active runtime tables;
- uses the cleaned status model;
- keeps `contacts.company_id -> companies.id` as the canonical contact relation;
- excludes removed score, bot runtime, preset, and contact join-table objects.
```

- [ ] **Step 3: Update the audit source note**

In `docs/DB-FIELD-AUDIT-2026-06-18.md`, replace the initial source note with:

```markdown
Источник аудита: актуальный baseline `sql/schema.sql`, runtime-код
`scripts/*.py` и `bot/*.py`, prompts `agents/prompts/*.md`, Notion mapping
`config/notion_mapping.yaml`, тесты `tests/*.py`.

Важно: старые test-era миграции удалены полностью. Этот аудит не опирается на
исторические SQL-шаги и рассматривает `sql/schema.sql` как единственный контракт
текущей схемы.
```

- [ ] **Step 4: Remove migration-chain language from the audit**

In `docs/DB-FIELD-AUDIT-2026-06-18.md`, replace claims that mention
`sql/017_agent_database_cleanup.sql` as the current source with baseline wording.
Use these replacements:

```text
После cleanup-миграции актуальный runtime-набор таблиц должен состоять из семи
```

becomes:

```text
По baseline `sql/schema.sql` актуальный runtime-набор таблиц состоит из семи
```

```text
`sql/017_agent_database_cleanup.sql` мапит их так:
```

becomes:

```text
При одноразовом live-cleanup эти статусы были смаплены так:
```

- [ ] **Step 5: Run documentation grep**

Run:

```bash
rg -n "017_agent_database_cleanup|old migrations|историческ|цепочк|migration history|bot_presets|contact_companies" README.md docs/AGENT-ECOSYSTEM.md docs/DB-FIELD-AUDIT-2026-06-18.md
```

Expected:

- no references that describe old migrations as active schema;
- `bot_presets` and `contact_companies` may appear only as removed objects.

## Task 5: Update Tests And Comments That Mention Removed History

**Files:**
- Modify: `tests/conftest.py`
- Modify if needed: `tests/test_notion_sync.py`
- Modify if needed: `tests/test_telegram_routines.py`

- [ ] **Step 1: Remove stale scoring import hint**

In `tests/conftest.py`, replace the docstring with:

```python
"""pytest conftest - adds scripts/ to sys.path.

Allows tests to import script modules without installing the project package.
"""
```

- [ ] **Step 2: Check for active references to deleted SQL files**

Run:

```bash
rg -n "001_init|003_source_page_url|004_signals_source_page_url|005_discover_verify_fields|006_contacts|007_dm_enriched_at|008_source_links|009_analysis_notes|010_dossiers|011_notion_sync_fields|012_bot|013_contacts_v2|014_drop_pipeline_runs|015_drop|016_bot_default|017_agent_database_cleanup" tests README.md docs agents scripts config
```

Expected: no references outside historical docs that intentionally mention deletion. If a reference exists in active tests or runtime docs, rewrite it to `sql/schema.sql`.

- [ ] **Step 3: Run broad reference scan for old active schema terms**

Run:

```bash
rg -n "pipeline_runs|bot_presets|contact_companies|score_bucket|score_version|ai_direction|latest_signal|reject_reason|source_page_url|companies\\.sources" scripts bot agents config tests README.md docs/AGENT-ECOSYSTEM.md
```

Expected:

- no runtime/prompts/config references;
- test references only when asserting removed terms are absent.

## Task 6: Verify Full Relevant Test Suite

**Files:**
- No edits expected

- [ ] **Step 1: Run schema and sync related tests**

Run:

```bash
python3 -m pytest tests/test_migrations.py tests/test_notion_sync.py tests/test_contacts_store.py tests/test_dossier_store.py tests/test_status.py tests/test_pipeline_prompts.py -q
```

Expected: all selected tests pass.

- [ ] **Step 2: Run full test suite**

Run:

```bash
python3 -m pytest -q
```

Expected: full suite passes. If unrelated network/API tests fail because they require external services, capture the failing test names and error messages before deciding whether to narrow verification.

- [ ] **Step 3: Inspect git diff**

Run:

```bash
git status --short
git diff --stat
```

Expected:

- old SQL migration files deleted;
- `sql/schema.sql` added;
- `tests/test_migrations.py` rewritten as baseline schema tests;
- docs updated to reference `sql/schema.sql`.

## Task 7: Commit

**Files:**
- All files changed by Tasks 1-5

- [ ] **Step 1: Stage intended files**

Run:

```bash
git add sql tests/test_migrations.py tests/conftest.py README.md docs/AGENT-ECOSYSTEM.md docs/DB-FIELD-AUDIT-2026-06-18.md
```

- [ ] **Step 2: Review staged diff**

Run:

```bash
git diff --cached --stat
git diff --cached --name-status
```

Expected: only intended schema baseline, test, and doc files are staged.

- [ ] **Step 3: Commit**

Run:

```bash
git commit -m "chore: replace test-era migrations with schema baseline"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: the plan deletes old migrations instead of archiving them, creates one baseline schema, rewrites migration tests into baseline tests, and updates docs/audit references.
- Placeholder scan: no TODO/TBD placeholders are present.
- Type consistency: table names, column names, and status values match the current cleanup model and runtime code.
