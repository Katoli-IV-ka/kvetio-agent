# Database & Agent Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current mixed-role schema with a layered contract (identity → raw observations → interpretation → finalized knowledge), and update every script, prompt, and doc to write the new contract exclusively.

**Architecture:** `signals`+`source_links` collapse into one `research_records` table; `analysis_notes`→`analysis_records`; the old markdown `dossiers` table is replaced by a new `dossiers` table (typed columns + section summaries + narrative); `contacts` gains `name`/`contact_type`; `companies` is trimmed of derived shortcut columns. Two provenance junctions (`analysis_links`, `dossier_links`) record why each conclusion was drawn. The live Supabase project is migrated in phases that preserve existing rows and IDs; `sql/schema.sql` is rewritten to the clean target shape for fresh installs.

**Tech Stack:** Python 3.11 (dataclasses, pytest), Supabase (PostgreSQL) via `supabase` client and the Supabase MCP `apply_migration`, Notion sync, Markdown agent prompts.

**Source spec:** `docs/superpowers/specs/2026-06-19-database-agent-cleanup-FINAL.md`

---

## Canonical naming (overrides FINAL spec names)

The FINAL spec used working table names (`research_entries`, `company_profiles`, …). The **authoritative names** for implementation and documentation are below. Wherever this plan, the code, or the docs would have used a FINAL-spec name, use the right-hand name instead.

### Table grouping (this taxonomy drives the documentation in Task 20)

**Данные (Data)** — concrete domain objects; agents and operators work with them directly.

| Table | Role | Was (FINAL spec) |
|---|---|---|
| `companies` | Company identity and pipeline status | `companies` |
| `contacts` | Contacts and channels — people + org-level | `contacts` |
| `dossiers` | Finalized profile: typed fields + summaries + narrative | `company_profiles` |

**Процессные (Process)** — accumulate as agents work; two symmetric layers.

| Table | Role | Was (FINAL spec) |
|---|---|---|
| `research_records` | Raw observations: everything an agent found | `research_entries` |
| `analysis_records` | Interpretations: agent conclusions built on `research_records` | `analysis_entries` |

**Технические (Technical)** — not read directly by agents/operators; integrity, provenance, runtime.

| Table | Role | Was (FINAL spec) |
|---|---|---|
| `analysis_links` | Which `research_records` back each `analysis_record` | `analysis_entry_research_links` |
| `dossier_links` | Which `analysis_records` back each `dossiers` field | `profile_analysis_links` |
| `record_types` | Vocabulary of allowed `research_records` types | `research_entry_types` |
| `run_logs` | Agent run history, errors, diagnostics | `run_logs` |

### Derived identifier renames (columns, dataclasses, helpers)

For internal consistency the column/code identifiers follow the table names. These are decisions made for this plan — call them out in review if a different convention is preferred:

| FINAL spec | This plan |
|---|---|
| column `entry_type` | `record_type` (FK → `record_types.code`) |
| column `entry_role` | `record_role` |
| column `research_entry_id` | `research_record_id` |
| column `analysis_entry_id` | `analysis_record_id` |
| column `discovered_from_research_entry_id` | `discovered_from_research_record_id` |
| dataclass `ResearchEntry` | `ResearchRecord` |
| Literal `ResearchEntryType` / `EntryRole` | `RecordType` / `RecordRole` |
| helper `upsert_research_entry` | `upsert_research_record` |
| helper `get_research_entries_for_analysis` | `get_research_records_for_analysis` |
| helper `upsert_analysis_entry` | `upsert_analysis_record` |
| helper `upsert_company_profile` / `get_company_profile` | `upsert_dossier` / `get_dossier` |
| helper `link_profile_to_analysis` | `link_dossier_to_analysis` |

### `dossiers` name collision during migration

The **new** finalized-profile table is named `dossiers`, but an **old** `dossiers` table (markdown shape) already exists. Both cannot exist at once. Resolution (Task 6 / Task 17):

1. Phase 1 first renames the old table: `ALTER TABLE dossiers RENAME TO dossiers_legacy;`
2. The new `dossiers` table is then created and back-filled from `dossiers_legacy`.
3. Phase 5 drops `dossiers_legacy` (not `dossiers`).

---

## Conventions for this plan

- The live database is changed by applying SQL through the Supabase MCP `apply_migration` tool (named migrations). Each Phase below that contains SQL also has a numbered migration file saved under `sql/migrations/` so the change is reproducible and reviewable in git.
- `sql/schema.sql` is the single clean-install contract. It is rewritten **once** in Task 18 to the final target shape; `tests/test_migrations.py` asserts on its contents and is updated in the same task.
- Tests run with `pytest` from the repo root. Schema-contract tests read `sql/schema.sql` as text — they do **not** require a live DB. Store/agent tests use the existing fakes/fixtures in `tests/` and `tests/conftest.py`.
- The dataclass attribute `raw_payload` is intentionally kept (it maps to DB column `raw_data`) to avoid churn in `supabase_store`. Only `signal_type`/`signal_date` are renamed on the dataclass (to `record_type`/`observed_at`).
- Commit after every task. Migrations are applied to the live DB in Phase order (Tasks 2–8, 17), code lands in Phase 3 (Tasks 9–15), schema.sql + legacy drop land last (Tasks 17–18).

## File map

Created:
- `sql/migrations/020_record_types.sql` … `027_drop_legacy.sql` (one per migration step)

Modified:
- `sql/schema.sql` — rewritten to target shape (Task 18)
- `scripts/models.py` — `ResearchRecord`, `RecordRole`, `ContactType`, `ContactRecord`
- `scripts/supabase_store.py` — `upsert_company`, signal helpers → research-record helpers
- `scripts/dossier_store.py` — drop source-link/old-dossier/note helpers, add new-dossier + analysis-record helpers
- `scripts/enrichment.py` — write via `upsert_research_record`
- `scripts/contacts_store.py` — `name`/`contact_type` payload, new conflict key
- `scripts/dm_github.py`, `dm_huggingface_contacts.py`, `dm_apollo.py`, `dm_wellfound.py`, `dm_team_page.py`, `dm_contact_page.py` — new contact payload
- `scripts/notion_sync.py` — dossier sync reads new shape, contact `name`/`contact_type`
- `agents/prompts/*.md` — new table names and write targets
- `config/notion_mapping.yaml` — contact field names, dossiers new-shape properties
- `tests/test_migrations.py`, `tests/test_models_signals.py`, `tests/test_models_cleanup.py`, `tests/test_dossier_store.py`, `tests/test_contacts_store.py`, `tests/test_enrichment.py`, `tests/test_notion_sync.py`, `tests/test_pipeline_prompts.py`, `tests/test_dedup.py`
- `docs/AGENT-ECOSYSTEM.md`, `docs/DB-FIELD-AUDIT-2026-06-18.md`, `README.md`, the five superseded spec docs

---

# Phase 0 — Preconditions

### Task 1: Record current row counts and confirm `source_links` is empty

**Files:** none (read-only DB check; record output in the migration PR description).

- [ ] **Step 1: Run the precondition queries against the live DB**

Apply via Supabase MCP `execute_sql` (read-only, no migration file):

```sql
SELECT 'source_links' AS t, count(*) FROM source_links
UNION ALL SELECT 'signals',        count(*) FROM signals
UNION ALL SELECT 'analysis_notes', count(*) FROM analysis_notes
UNION ALL SELECT 'analysis_note_signals', count(*) FROM analysis_note_signals
UNION ALL SELECT 'dossiers',       count(*) FROM dossiers
UNION ALL SELECT 'contacts',       count(*) FROM contacts;
```

Expected: `source_links = 0` (confirmed empty per spec), `signals = 74`. Record all counts (the `dossiers` count here is the **old** table; it becomes `dossiers_legacy` in Task 6).

- [ ] **Step 2: Gate check**

If `source_links` is not 0, STOP and escalate — the spec assumes it is empty and does not backfill it. Do not proceed to Phase 1 until this passes.

---

# Phase 1 — Create new tables (additive, no downtime)

Migration files are applied in order. Each `CREATE TABLE` reuses the existing `update_updated_at()` trigger function (already present in the DB).

### Task 2: Create `record_types` vocabulary table

**Files:**
- Create: `sql/migrations/020_record_types.sql`

- [ ] **Step 1: Write the migration**

`sql/migrations/020_record_types.sql`:

```sql
CREATE TABLE record_types (
    code        TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    -- discovery | people | sources | monitoring | financials | crypto
    description TEXT
);

INSERT INTO record_types (code, category, description) VALUES
  ('github_repo',           'discovery',  'Company GitHub repo/org found'),
  ('hf_org',                'discovery',  'HuggingFace organization found'),
  ('hf_model',              'discovery',  'HuggingFace model found'),
  ('job_posting',           'discovery',  'Job posting referencing the company'),
  ('papers_with_code',      'discovery',  'PapersWithCode reference'),
  ('funding_announcement',  'financials', 'Funding/round announcement'),
  ('kaggle_sponsor',        'discovery',  'Kaggle competition sponsor'),
  ('scale_customer',        'discovery',  'Listed as customer of a known vendor'),
  ('wandb_run',             'discovery',  'Weights & Biases public run'),
  ('directory_listing',     'discovery',  'Found in a directory listing'),
  ('contact_found',         'people',     'A person/contact discovered for the company'),
  ('source_link',           'sources',    'A curated source URL for analysis'),
  ('news',                  'monitoring', 'News article about the company'),
  ('product_update',        'monitoring', 'Product/release update detected'),
  ('foundation_model',      'discovery',  'Company uses or develops a foundation model'),
  ('proprietary_ai',        'discovery',  'Company has proprietary AI capability'),
  ('proprietary_models',    'discovery',  'Company has proprietary model(s)');
```

- [ ] **Step 2: Apply via Supabase MCP** as migration `020_record_types`.

- [ ] **Step 3: Verify the seed**

Run: `SELECT count(*) FROM record_types;`
Expected: `17`.

- [ ] **Step 4: Commit**

```bash
git add sql/migrations/020_record_types.sql
git commit -m "feat(db): add record_types vocabulary (renames signal_types)"
```

### Task 3: Create `research_records` and migrate 74 `signals` rows

**Files:**
- Create: `sql/migrations/021_research_records.sql`

- [ ] **Step 1: Write the migration (table + indexes + trigger + data copy)**

`sql/migrations/021_research_records.sql`:

```sql
CREATE TABLE research_records (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id  UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    record_type TEXT NOT NULL REFERENCES record_types(code),
    agent       TEXT,
    source      TEXT NOT NULL,
    title       TEXT,
    url         TEXT,
    summary     TEXT,
    confidence  NUMERIC(3,2) NOT NULL DEFAULT 0.50
                CONSTRAINT rr_confidence_range CHECK (confidence >= 0 AND confidence <= 1),
    observed_at DATE NOT NULL,
    record_role TEXT NOT NULL DEFAULT 'evidence'
                CONSTRAINT rr_record_role_check
                CHECK (record_role IN ('primary', 'verification', 'source', 'monitor', 'evidence')),
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_data    JSONB          DEFAULT '{}'::jsonb,
    run_id      UUID REFERENCES run_logs(id),
    dedupe_key  TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rr_company_id    ON research_records (company_id);
CREATE INDEX idx_rr_company_type  ON research_records (company_id, record_type);
CREATE INDEX idx_rr_observed_at   ON research_records (observed_at DESC);
CREATE INDEX idx_rr_type          ON research_records (record_type);
CREATE INDEX idx_rr_role          ON research_records (record_role);
CREATE INDEX idx_rr_company_role  ON research_records (company_id, record_role);

CREATE TRIGGER trg_rr_updated_at
BEFORE UPDATE ON research_records
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Migrate signals → research_records (preserve all 74 rows and IDs)
INSERT INTO research_records (
    id, company_id, record_type, agent, source, title, url, summary,
    confidence, observed_at, record_role, payload, raw_data,
    run_id, dedupe_key, created_at, updated_at
)
SELECT
    id, company_id,
    signal_type,          -- code values map 1:1 to record_types
    agent, source, title, url, summary, confidence,
    signal_date,          -- → observed_at
    CASE
        WHEN signal_type LIKE 'primary_%'      THEN 'primary'
        WHEN signal_type LIKE 'verification_%' THEN 'verification'
        WHEN signal_type LIKE 'monitor_%'      THEN 'monitor'
        WHEN signal_type = 'source_link'       THEN 'source'
        ELSE 'evidence'
    END,                  -- → record_role
    payload, raw_data, run_id, dedupe_key, created_at, updated_at
FROM signals;
```

- [ ] **Step 2: Apply via Supabase MCP** as migration `021_research_records`.

- [ ] **Step 3: Verify row parity**

Run: `SELECT (SELECT count(*) FROM signals) AS signals, (SELECT count(*) FROM research_records) AS research;`
Expected: both equal (74). If they differ, STOP — a `signal_type` code is missing from `record_types` (FK violation) and must be added before retrying.

- [ ] **Step 4: Commit**

```bash
git add sql/migrations/021_research_records.sql
git commit -m "feat(db): create research_records and migrate signals rows"
```

### Task 4: Create `analysis_records` and migrate `analysis_notes`

**Files:**
- Create: `sql/migrations/022_analysis_records.sql`

- [ ] **Step 1: Write the migration**

`sql/migrations/022_analysis_records.sql`:

```sql
CREATE TABLE analysis_records (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    section    TEXT NOT NULL
               CONSTRAINT ar_section_check
               CHECK (section IN ('company', 'product', 'collaboration',
                                  'financials', 'news', 'audit')),
    facts      JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(3,2) NOT NULL DEFAULT 0.50
               CONSTRAINT ar_confidence_check CHECK (confidence >= 0 AND confidence <= 1),
    model      TEXT,
    version    TEXT NOT NULL DEFAULT 'v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, section, version)
);

CREATE INDEX idx_ar_company ON analysis_records (company_id);

CREATE TRIGGER trg_ar_updated_at
BEFORE UPDATE ON analysis_records
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Migrate analysis_notes → analysis_records (preserve IDs)
INSERT INTO analysis_records (
    id, company_id, section, facts, confidence, model, version,
    created_at, updated_at
)
SELECT id, company_id, section, facts, confidence, model, version,
       created_at, NOW()
FROM analysis_notes;
```

- [ ] **Step 2: Apply via Supabase MCP** as migration `022_analysis_records`.

- [ ] **Step 3: Verify parity**

Run: `SELECT (SELECT count(*) FROM analysis_notes) AS notes, (SELECT count(*) FROM analysis_records) AS records;`
Expected: equal.

- [ ] **Step 4: Commit**

```bash
git add sql/migrations/022_analysis_records.sql
git commit -m "feat(db): create analysis_records and migrate analysis_notes"
```

### Task 5: Create `analysis_links` and migrate junction

**Files:**
- Create: `sql/migrations/023_analysis_links.sql`

- [ ] **Step 1: Write the migration**

`sql/migrations/023_analysis_links.sql`:

```sql
CREATE TABLE analysis_links (
    analysis_record_id UUID NOT NULL REFERENCES analysis_records(id)  ON DELETE CASCADE,
    research_record_id UUID NOT NULL REFERENCES research_records(id)  ON DELETE CASCADE,
    role               TEXT NOT NULL DEFAULT 'supports'
                       CONSTRAINT al_role_check
                       CHECK (role IN ('supports', 'contradicts', 'context')),
    note               TEXT,
    PRIMARY KEY (analysis_record_id, research_record_id)
);

CREATE INDEX idx_al_research_record ON analysis_links (research_record_id);

-- Migrate analysis_note_signals → analysis_links.
-- analysis_note_id and signal_id map directly because IDs were preserved in Tasks 3–4.
INSERT INTO analysis_links (
    analysis_record_id, research_record_id, role, note
)
SELECT analysis_note_id, signal_id, role, note
FROM analysis_note_signals;
```

- [ ] **Step 2: Apply via Supabase MCP** as migration `023_analysis_links`.

- [ ] **Step 3: Verify parity**

Run: `SELECT (SELECT count(*) FROM analysis_note_signals) AS old, (SELECT count(*) FROM analysis_links) AS new;`
Expected: equal.

- [ ] **Step 4: Commit**

```bash
git add sql/migrations/023_analysis_links.sql
git commit -m "feat(db): create analysis_links and migrate junction"
```

### Task 6: Rename old `dossiers`, create new `dossiers`, migrate

**Files:**
- Create: `sql/migrations/024_dossiers.sql`

The new `dossiers` table reuses the name of the old markdown table, so the old one is renamed to `dossiers_legacy` first (see "name collision" note above).

- [ ] **Step 1: Write the migration**

`sql/migrations/024_dossiers.sql`:

```sql
-- Move the old markdown dossiers table out of the way.
ALTER TABLE dossiers RENAME TO dossiers_legacy;

CREATE TABLE dossiers (
    company_id UUID PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,

    -- Typed structured fields
    funding_stage       TEXT,
    funding_amount_usd  BIGINT,
    funding_date        DATE,
    company_size  TEXT,
    product_category    TEXT,
    ai_use_case         TEXT,
    icp_fit             TEXT
                        CONSTRAINT dossiers_icp_fit_check
                        CHECK (icp_fit IN ('strong', 'moderate', 'weak', 'unknown')),
    last_news_date      DATE,
    extra_facts         JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Section text summaries
    section_summaries   JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Narrative
    summary_md          TEXT,
    audit_md            TEXT,

    -- Notion binding
    notion_page_id      TEXT,
    notion_synced_at    TIMESTAMPTZ,

    -- Meta
    derived_from_model  TEXT,
    version             TEXT NOT NULL DEFAULT 'v1',
    derived_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_dossiers_icp_fit       ON dossiers (icp_fit);
CREATE INDEX idx_dossiers_funding_stage ON dossiers (funding_stage);
CREATE INDEX idx_dossiers_derived_at    ON dossiers (derived_at DESC);

CREATE TRIGGER trg_dossiers_updated_at
BEFORE UPDATE ON dossiers
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Migrate dossiers_legacy → dossiers.
-- Typed fields stay NULL; populated on next ConclusionAgent run.
INSERT INTO dossiers (
    company_id, section_summaries, summary_md, audit_md,
    notion_page_id, version, derived_at, updated_at
)
SELECT
    company_id,
    sections,         -- → section_summaries
    summary_md,
    audit_md,
    notion_page_id,
    version,
    generated_at,     -- → derived_at
    NOW()
FROM dossiers_legacy;
```

- [ ] **Step 2: Apply via Supabase MCP** as migration `024_dossiers`.

- [ ] **Step 3: Verify parity**

Run: `SELECT (SELECT count(*) FROM dossiers_legacy) AS legacy, (SELECT count(*) FROM dossiers) AS dossiers;`
Expected: equal.

- [ ] **Step 4: Commit**

```bash
git add sql/migrations/024_dossiers.sql
git commit -m "feat(db): replace markdown dossiers with typed dossiers table"
```

### Task 7: Create `dossier_links` (empty)

**Files:**
- Create: `sql/migrations/025_dossier_links.sql`

- [ ] **Step 1: Write the migration**

`sql/migrations/025_dossier_links.sql`:

```sql
CREATE TABLE dossier_links (
    company_id          UUID NOT NULL REFERENCES dossiers(company_id) ON DELETE CASCADE,
    analysis_record_id  UUID NOT NULL REFERENCES analysis_records(id) ON DELETE CASCADE,
    contributed_to      TEXT,
    PRIMARY KEY (company_id, analysis_record_id)
);

CREATE INDEX idx_dl_analysis_record ON dossier_links (analysis_record_id);
```

- [ ] **Step 2: Apply via Supabase MCP** as migration `025_dossier_links`. No data to migrate (provenance did not exist previously).

- [ ] **Step 3: Verify**

Run: `SELECT count(*) FROM dossier_links;`
Expected: `0` (table exists, empty).

- [ ] **Step 4: Commit**

```bash
git add sql/migrations/025_dossier_links.sql
git commit -m "feat(db): create dossier_links provenance junction"
```

---

# Phase 2 — Migrate `contacts` schema

### Task 8: Add `name`/`contact_type`, backfill, swap dedup index, drop legacy columns

**Files:**
- Create: `sql/migrations/026_contacts_v3.sql`

This migration drops `companies.created_from_signal_id` / `last_signal_id` FK constraints first (those reference `signals`, dropped in Phase 5), and repoints `contacts.discovered_from_signal_id` at `research_records`.

- [ ] **Step 1: Write the migration**

`sql/migrations/026_contacts_v3.sql`:

```sql
-- 1. Drop companies → signals FK constraints (signals dropped in Phase 5).
ALTER TABLE companies
    DROP CONSTRAINT IF EXISTS companies_created_from_signal_id_fkey,
    DROP CONSTRAINT IF EXISTS companies_last_signal_id_fkey;

-- 2. Add new contact columns (nullable for backfill).
ALTER TABLE contacts
    ADD COLUMN contact_type TEXT,
    ADD COLUMN name TEXT,
    ADD COLUMN discovered_from_research_record_id UUID
        REFERENCES research_records(id) ON DELETE SET NULL;

-- 3. Backfill from existing person rows.
--    discovered_from_signal_id values are valid research_records IDs (IDs preserved).
UPDATE contacts SET
    name = trim(first_name || ' ' || last_name),
    contact_type = 'person',
    discovered_from_research_record_id = discovered_from_signal_id;

-- 4. Enforce NOT NULL.
ALTER TABLE contacts
    ALTER COLUMN name SET NOT NULL,
    ALTER COLUMN contact_type SET NOT NULL;

-- 5. New dedup index.
CREATE UNIQUE INDEX idx_contacts_dedup
    ON contacts (company_id, contact_type, lower(name));

-- 6. Drop old indexes and legacy columns.
DROP INDEX IF EXISTS idx_contacts_company_name;
DROP INDEX IF EXISTS idx_contacts_company_name_upsert;
ALTER TABLE contacts
    DROP COLUMN first_name,
    DROP COLUMN last_name,
    DROP COLUMN discovered_from_signal_id;
```

- [ ] **Step 2: Apply via Supabase MCP** as migration `026_contacts_v3`.

- [ ] **Step 3: Verify new shape**

Run:
```sql
SELECT column_name FROM information_schema.columns
WHERE table_name='contacts'
  AND column_name IN ('name','contact_type','first_name','last_name','discovered_from_signal_id');
```
Expected rows: `name`, `contact_type` only.

- [ ] **Step 4: Commit**

```bash
git add sql/migrations/026_contacts_v3.sql
git commit -m "feat(db): contacts name/contact_type, research-record provenance"
```

---

# Phase 3 — Update code

Order is fixed: models → supabase_store → dossier_store → enrichment → contacts_store → dm_* → notion_sync → prompts. Each task is TDD where logic changes.

### Task 9: Rename dataclasses in `scripts/models.py`

**Files:**
- Modify: `scripts/models.py`
- Test: `tests/test_models_signals.py`, `tests/test_models_cleanup.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models_signals.py`:

```python
from datetime import date
from scripts.models import ResearchRecord, RawSignal, ContactRecord


def test_research_record_has_fields_and_default_role():
    e = ResearchRecord(
        source="github",
        record_type="github_repo",
        company_name="Rad AI",
        domain="radai.com",
        linkedin_url=None,
        url="https://github.com/radai",
        observed_at=date(2026, 6, 19),
        confidence=0.8,
    )
    assert e.record_type == "github_repo"
    assert e.observed_at == date(2026, 6, 19)
    assert e.record_role == "evidence"


def test_rawsignal_is_alias_of_research_record():
    assert RawSignal is ResearchRecord


def test_contact_record_uses_name_and_type():
    c = ContactRecord(company_id="cid", name="Sarah Chen")
    assert c.name == "Sarah Chen"
    assert c.contact_type == "person"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_models_signals.py -k research_record or alias or contact_record -v`
Expected: FAIL — `ImportError: cannot import name 'ResearchRecord'`.

- [ ] **Step 3: Edit `scripts/models.py`**

Add the literal aliases near the existing `SignalType` definition:

```python
RecordType = SignalType  # same 17 codes, see record_types table

RecordRole = Literal["primary", "verification", "source", "monitor", "evidence"]

ContactType = Literal["person", "organization"]
```

Rename the `RawSignal` dataclass to `ResearchRecord`, renaming `signal_type`→`record_type`, `signal_date`→`observed_at`, and adding `record_role`. Keep `raw_payload` (maps to DB `raw_data`):

```python
@dataclass(frozen=True)
class ResearchRecord:
    """One atomic observation about a company, keyed to company_id."""

    source: str
    record_type: RecordType
    company_name: str
    domain: str | None
    linkedin_url: str | None
    url: str
    observed_at: date
    confidence: "Confidence | float"
    record_role: RecordRole = "evidence"
    agent: str | None = None
    title: str | None = None
    summary: str | None = None
    payload: dict = field(default_factory=dict)
    raw_payload: dict = field(default_factory=dict)  # → DB column raw_data

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("ResearchRecord.url обязателен")
        if not self.company_name.strip():
            raise ValueError("ResearchRecord.company_name не может быть пустым")


# Deprecated alias — remove after all callers updated:
RawSignal = ResearchRecord
```

Update `ContactRecord`:

```python
@dataclass
class ContactRecord:
    """Current outreach touchpoint for a company (person or organization)."""

    company_id: str
    name: str
    contact_type: ContactType = "person"
    info: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    x_url: str | None = None
    facebook_url: str | None = None
    instagram_url: str | None = None
    other_channels: list[OtherChannel] = field(default_factory=list)
    discovered_from_research_record_id: str | None = None
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_models_signals.py tests/test_models_cleanup.py -v`
Expected: PASS. Fix any cleanup-test assertions that referenced `signal_type`/`signal_date`/`first_name` by updating them to the new names.

- [ ] **Step 5: Commit**

```bash
git add scripts/models.py tests/test_models_signals.py tests/test_models_cleanup.py
git commit -m "refactor(models): RawSignal→ResearchRecord, ContactRecord name/type"
```

### Task 10: Update `scripts/supabase_store.py` writers and read helpers

**Files:**
- Modify: `scripts/supabase_store.py`
- Test: `tests/test_dedup.py`, new `tests/test_supabase_store.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_supabase_store.py` (use the fake-client pattern from `tests/conftest.py`; mirror how `tests/test_dedup.py` constructs a store):

```python
from datetime import date
from scripts.models import ResearchRecord


def test_upsert_company_writes_only_lean_columns(fake_store):
    fake_store.upsert_company(_company())  # helper builds a Company
    row = fake_store.last_upsert("companies")
    for removed in (
        "last_signal_date", "last_verified", "funding_stage", "funding_amount",
        "funding_date", "team_size", "site_note", "website_snippet",
        "dm_enriched_at", "created_from_signal_id", "last_signal_id",
    ):
        assert removed not in row


def test_upsert_research_record_writes_research_records_table(fake_store):
    e = ResearchRecord(
        source="web", record_type="news", company_name="Rad AI",
        domain="radai.com", linkedin_url=None, url="https://x/y",
        observed_at=date(2026, 6, 19), confidence=0.5, record_role="monitor",
    )
    fake_store.upsert_research_record(e, domain="radai.com")
    row = fake_store.last_upsert("research_records")
    assert row["record_type"] == "news"
    assert row["observed_at"] == "2026-06-19"
    assert row["record_role"] == "monitor"
```

(If the repo has no `fake_store` fixture, add one to `tests/conftest.py` modeled on the store fake already used by `tests/test_dedup.py`; reuse that fake's `last_upsert` API rather than inventing a new mechanism.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_supabase_store.py -v`
Expected: FAIL — `AttributeError: 'SupabaseStore' object has no attribute 'upsert_research_record'`.

- [ ] **Step 3: Edit `scripts/supabase_store.py`**

In `upsert_company` (line ~54), remove every removed column from the written dict; keep only `domain`, `name`, `website`, `linkedin_url`, `status`, `icp_segment`, `description`, `notion_page_id`, `notion_synced_at`.

Rename `upsert_signal` → `upsert_research_record` and rewrite its row to the new columns:

```python
def upsert_research_record(self, entry: ResearchRecord, domain: str | None = None) -> bool:
    cid = self.resolve_company_id(domain=domain or entry.domain, ...)  # unchanged resolution
    if cid is None:
        raise ValueError(
            f"upsert_research_record: cannot resolve company for domain={domain or entry.domain!r}"
        )
    dedupe = self._dedupe_key(cid, entry.record_type, entry.url,
                              fallback=entry.observed_at.isoformat())
    row = {
        "company_id": cid,
        "record_type": entry.record_type,
        "agent": entry.agent,
        "source": entry.source,
        "title": entry.title,
        "url": entry.url,
        "summary": entry.summary,
        "confidence": confidence_to_score(entry.confidence),
        "observed_at": entry.observed_at.isoformat(),
        "record_role": entry.record_role,
        "payload": entry.payload or {},
        "raw_data": entry.raw_payload or {},
        "dedupe_key": dedupe,
    }
    res = (
        self._client.table("research_records")
        .upsert(row, on_conflict="dedupe_key", ignore_duplicates=True)
        .execute()
    )
    return bool(res.data)
```

Update `_dedupe_key` parameter name `signal_type` → `record_type` (string body unchanged). Rename `get_signals_for_company` → `get_research_records_for_company`, changing `.table("signals")` → `.table("research_records")` and `.order("signal_date", ...)` → `.order("observed_at", ...)`.

Add the four read helpers:

```python
def get_latest_research_record(self, company_id: str) -> dict | None:
    res = (self._client.table("research_records")
           .select("*").eq("company_id", company_id)
           .order("observed_at", desc=True).limit(1).execute())
    return res.data[0] if res.data else None

def get_verification_freshness(self, company_id: str) -> str | None:
    res = (self._client.table("research_records")
           .select("observed_at").eq("company_id", company_id)
           .eq("record_role", "verification")
           .order("observed_at", desc=True).limit(1).execute())
    return res.data[0]["observed_at"] if res.data else None

def get_research_records_for_analysis(self, company_id: str) -> list[dict]:
    res = (self._client.table("research_records")
           .select("*").eq("company_id", company_id)
           .in_("record_role", ["primary", "source", "evidence"])
           .order("observed_at", desc=True).execute())
    return res.data or []

def get_funding_records(self, company_id: str) -> list[dict]:
    res = (self._client.table("research_records")
           .select("*").eq("company_id", company_id)
           .eq("record_type", "funding_announcement")
           .order("observed_at", desc=True).execute())
    return res.data or []
```

Keep a thin `upsert_signal = upsert_research_record` alias only if other modules still import it; remove once Task 11/12 land.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_supabase_store.py tests/test_dedup.py -v`
Expected: PASS. Update `tests/test_dedup.py` references from `upsert_signal`/`signal_type` to the new names if present.

- [ ] **Step 5: Commit**

```bash
git add scripts/supabase_store.py tests/test_supabase_store.py tests/test_dedup.py tests/conftest.py
git commit -m "refactor(store): research_records writers + freshness read helpers"
```

### Task 11: Rework `scripts/dossier_store.py` (remove source-link/old-dossier; add new-dossier helpers)

**Files:**
- Modify: `scripts/dossier_store.py`
- Test: `tests/test_dossier_store.py`

- [ ] **Step 1: Write the failing test**

Replace the source-link/old-dossier tests in `tests/test_dossier_store.py` with:

```python
from scripts.dossier_store import (
    upsert_analysis_record, link_analysis_to_research,
    upsert_dossier, get_dossier,
    link_dossier_to_analysis, get_research_records,
)


def test_upsert_dossier_writes_typed_and_narrative(fake_store):
    upsert_dossier(fake_store, {
        "company_id": "cid",
        "funding_stage": "seed",
        "icp_fit": "strong",
        "section_summaries": {"financials": "Raised seed."},
        "summary_md": "# Rad AI\nSeed-stage.",
    })
    row = fake_store.last_upsert("dossiers")
    assert row["funding_stage"] == "seed"
    assert row["icp_fit"] == "strong"
    assert row["summary_md"].startswith("# Rad AI")


def test_link_dossier_to_analysis_one_row_per_record(fake_store):
    link_dossier_to_analysis(
        fake_store, "cid", ["ar1", "ar2"],
        {"ar1": "funding_stage", "ar2": "financials"},
    )
    rows = fake_store.upserts("dossier_links")
    assert {r["analysis_record_id"] for r in rows} == {"ar1", "ar2"}
    assert {r["contributed_to"] for r in rows} == {"funding_stage", "financials"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_dossier_store.py -v`
Expected: FAIL — `ImportError: cannot import name 'upsert_dossier'` (with the new signature) / `link_dossier_to_analysis`.

- [ ] **Step 3: Edit `scripts/dossier_store.py`**

Remove `upsert_source_link`, `get_source_links`, the OLD `upsert_dossier`/`get_dossier` (markdown shape), and the related CLI flags/branches. Rename `upsert_analysis_note` → `upsert_analysis_record` (write `.table("analysis_records")`, conflict `company_id,section,version`). Rename `link_note_to_signals` → `link_analysis_to_research` (write `.table("analysis_links")`, columns `analysis_record_id,research_record_id,role,note`, conflict `analysis_record_id,research_record_id`).

Add the new-shape dossier helpers:

```python
DOSSIER_COLUMNS = (
    "company_id", "funding_stage", "funding_amount_usd", "funding_date",
    "company_size", "product_category", "ai_use_case", "icp_fit",
    "last_news_date", "extra_facts", "section_summaries", "summary_md",
    "audit_md", "notion_page_id", "notion_synced_at", "derived_from_model",
    "version",
)

def upsert_dossier(store: SupabaseStore, dossier: dict) -> None:
    row = {k: dossier[k] for k in DOSSIER_COLUMNS if k in dossier}
    row["company_id"] = dossier["company_id"]
    store._client.table("dossiers").upsert(
        row, on_conflict="company_id"
    ).execute()

def get_dossier(store: SupabaseStore, company_id: str) -> dict | None:
    res = (store._client.table("dossiers")
           .select("*").eq("company_id", company_id).limit(1).execute())
    return res.data[0] if res.data else None

def link_dossier_to_analysis(
    store: SupabaseStore, company_id: str,
    analysis_record_ids: list[str], contributed_to_map: dict[str, str],
) -> None:
    if not analysis_record_ids:
        return
    rows = [
        {"company_id": company_id, "analysis_record_id": aid,
         "contributed_to": contributed_to_map.get(aid)}
        for aid in analysis_record_ids
    ]
    store._client.table("dossier_links").upsert(
        rows, on_conflict="company_id,analysis_record_id"
    ).execute()

def get_research_records(store: SupabaseStore, company_id: str) -> list[dict]:
    return store.get_research_records_for_analysis(company_id)
```

Update the CLI `_build_parser`/`_run`: keep `--upsert-dossier`, `--get-dossier` (now new shape); drop the source-link flags. Update the module docstring (currently references `source_links, analysis_notes, dossiers`) to `research_records, analysis_records, analysis_links, dossiers, dossier_links`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_dossier_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/dossier_store.py tests/test_dossier_store.py
git commit -m "refactor(dossier_store): drop source_links, typed dossiers + dossier_links"
```

### Task 12: Update `scripts/enrichment.py` to write research records

**Files:**
- Modify: `scripts/enrichment.py`
- Test: `tests/test_enrichment.py`

- [ ] **Step 1: Write the failing test**

Update `tests/test_enrichment.py` so the assertion checks the resolver output is written via `upsert_research_record`:

```python
def test_run_enrichment_writes_research_records(fake_store, monkeypatch):
    calls = []
    monkeypatch.setattr(fake_store, "upsert_research_record",
                        lambda entry, **kw: calls.append(entry))
    # ... arrange one enabled resolver returning a source URL ...
    run_enrichment(fake_store, client=..., resolvers=[stub_resolver])
    assert calls, "expected a research_record write"
    assert calls[0].record_role == "source"
    assert calls[0].record_type == "source_link"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_enrichment.py -v`
Expected: FAIL — `enrichment` still imports/calls `upsert_source_link`.

- [ ] **Step 3: Edit `scripts/enrichment.py`**

Remove `from dossier_store import upsert_source_link` and the `upsert_source_link(store, link)` call in `run_enrichment`. Resolvers now return `ResearchRecord`-shaped data (or a dict the loop maps into a `ResearchRecord` with `record_type="source_link"`, `record_role="source"`, resolver metadata — `kind`, `found_via`, external IDs, `fetched_at` — placed in `payload`). Write through `store.upsert_research_record(entry, domain=company["domain"])`. Update the module docstring (line 1–4) to say research records, not `source_links`.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_enrichment.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/enrichment.py tests/test_enrichment.py
git commit -m "refactor(enrichment): write source evidence to research_records"
```

### Task 13: Update `scripts/contacts_store.py` and `dm_*.py` payloads

**Files:**
- Modify: `scripts/contacts_store.py`, `scripts/dm_github.py`, `scripts/dm_huggingface_contacts.py`, `scripts/dm_apollo.py`, `scripts/dm_wellfound.py`, `scripts/dm_team_page.py`, `scripts/dm_contact_page.py`
- Test: `tests/test_contacts_store.py`, the six `tests/test_dm_*.py`

- [ ] **Step 1: Write the failing test**

Update `tests/test_contacts_store.py`:

```python
def test_upsert_contact_uses_name_and_type(fake_store):
    upsert_contact(fake_store, {
        "company_domain": "radai.com", "name": "Sarah Chen",
    })
    row = fake_store.last_upsert("contacts")
    assert row["name"] == "Sarah Chen"
    assert row["contact_type"] == "person"
    assert "first_name" not in row


def test_upsert_contact_accepts_organization(fake_store):
    upsert_contact(fake_store, {
        "company_domain": "radai.com", "name": "Rad AI GitHub",
        "contact_type": "organization",
    })
    assert fake_store.last_upsert("contacts")["contact_type"] == "organization"


def test_upsert_contact_back_compat_first_last(fake_store):
    upsert_contact(fake_store, {
        "company_domain": "radai.com", "first_name": "Sarah", "last_name": "Chen",
    })
    assert fake_store.last_upsert("contacts")["name"] == "Sarah Chen"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_contacts_store.py -v`
Expected: FAIL — store still writes `first_name`/`last_name` and conflict key `company_id,first_name,last_name`.

- [ ] **Step 3: Edit `scripts/contacts_store.py`**

Replace `split_contact_name` usage. Build `name` as: `contact["name"]` if present, else `trim(first_name + " " + last_name)` (transition shim; remove after first migration cycle). Default `contact_type = contact.get("contact_type", "person")`. Row dict writes `name`, `contact_type`, channels as before, and `discovered_from_research_record_id` when `contact.get("discovered_from_research_record_id")` is set. Change `on_conflict` to `"company_id,contact_type,name"`. Remove `mark_enriched`. In `list_contacts`, change `.order("first_name")` → `.order("contact_type").order("name")`.

- [ ] **Step 4: Edit the six `dm_*.py` scripts**

In each, change emitted contact payloads to use `name` (not `first_name`/`last_name`); set `contact_type="person"` for named people and `contact_type="organization"` for shared inboxes, company/org profiles, and generic contact forms; set `discovered_from_research_record_id` when the contact originated from a known research record. Concretely:
- `dm_github.py`: org profile → `organization`; named maintainers → `person`.
- `dm_huggingface_contacts.py`: HF org → `organization`; named members → `person`.
- `dm_apollo.py`, `dm_wellfound.py`: named people → `person`.
- `dm_team_page.py`: named team members → `person`.
- `dm_contact_page.py`: generic contact form / shared inbox → `organization`.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_contacts_store.py tests/test_dm_github.py tests/test_dm_huggingface_contacts.py tests/test_dm_apollo.py tests/test_dm_wellfound.py tests/test_dm_team_page.py tests/test_dm_contact_page.py -v`
Expected: PASS. Update each dm test's expected payload to `name`/`contact_type`.

- [ ] **Step 6: Commit**

```bash
git add scripts/contacts_store.py scripts/dm_*.py tests/test_contacts_store.py tests/test_dm_*.py
git commit -m "refactor(contacts): name/contact_type payload across store and dm_* scripts"
```

### Task 14: Update `scripts/notion_sync.py` and `config/notion_mapping.yaml`

**Files:**
- Modify: `scripts/notion_sync.py`, `config/notion_mapping.yaml`
- Test: `tests/test_notion_sync.py`

The Notion entity stays named `dossiers` (the table kept its name), only its field mapping changes to the new shape.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_notion_sync.py`:

```python
def test_contact_display_name_uses_name_field():
    from scripts.notion_sync import contact_display_name
    assert contact_display_name({"name": "Sarah Chen"}) == "Sarah Chen"


def test_sync_dossiers_reads_typed_fields(fake_notion, fake_db):
    fake_db.seed("dossiers", [{
        "company_id": "cid", "summary_md": "# Rad AI",
        "section_summaries": {"financials": "Seed."},
        "funding_stage": "seed", "icp_fit": "strong",
    }])
    sync = NotionSync(fake_notion, fake_db, mapping=_mapping())
    result = sync.sync_dossiers(dry_run=True)
    assert result["entity"] == "dossiers"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_notion_sync.py -v`
Expected: FAIL — `contact_display_name` reads `first_name`/`last_name`; `sync_dossiers` reads old `sections`/`table_fields`.

- [ ] **Step 3: Edit `scripts/notion_sync.py`**

`contact_display_name` (line ~148) returns `str(row.get("name") or "").strip()`. In `_sync_contacts_reverse` (lines ~369–370) write `changes["name"] = title` and `changes["contact_type"] = <select value>` instead of splitting into first/last. Rewrite `sync_dossiers` (line ~437) to map the new columns: `summary_md` → page body, `section_summaries` → section blocks, and project `funding_stage`, `company_size`, `icp_fit`, `product_category`, `last_news_date` as Notion properties; sync `notion_page_id`/`notion_synced_at` back to `dossiers`. Keep `--entity dossiers` (line ~489) and its dispatch (line ~523). Remove any reads of the old `sections`/`table_fields`/`generated_at` columns.

- [ ] **Step 4: Edit `config/notion_mapping.yaml`**

Rename contact field mappings `first_name`/`last_name` → `name`, add `contact_type` select mapping; update the `dossiers` entity block to the new properties (`funding_stage`, `company_size`, `icp_fit`, `product_category`, `last_news_date`; body from `summary_md`).

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_notion_sync.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/notion_sync.py config/notion_mapping.yaml tests/test_notion_sync.py
git commit -m "refactor(notion): dossiers new-shape sync, contact name/type projection"
```

### Task 15: Update agent prompts

**Files:**
- Modify: `agents/prompts/*.md` (all 15)
- Test: `tests/test_pipeline_prompts.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_pipeline_prompts.py`:

```python
from pathlib import Path
import pytest

PROMPTS = sorted(Path("agents/prompts").glob("*.md"))
FORBIDDEN = ["source_links", "last_signal_date", "last_verified",
             "dm_enriched_at", "analysis_notes", "analysis_note_signals",
             "signal_types"]

@pytest.mark.parametrize("path", PROMPTS, ids=lambda p: p.name)
def test_prompt_has_no_removed_schema_references(path):
    text = path.read_text(encoding="utf-8")
    for token in FORBIDDEN:
        assert token not in text, f"{path.name} still references {token}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_prompts.py -v`
Expected: FAIL on prompts that still mention `source_links`, removed `companies` fields, `analysis_notes`, etc.

- [ ] **Step 3: Edit the prompts**

Apply the Agent Prompt Contract from the spec, per prompt, using the canonical table names:
- `discovery_task.md`, `collection_task.md`, `research_task.md`: write lean `companies` + `research_records` with `record_role='primary'`; never write `created_from_signal_id`/`last_signal_id`/`last_signal_date`.
- `relevance_task.md`, `verify_task.md`, `discover_verify_task.md`: update only `companies.status`; verification evidence → `research_records` `record_role='verification'`; never write `last_verified`.
- `source_expansion_task.md`, `enrichment_task.md`: supporting URLs → `research_records` `record_role='source'` (not `source_links`); resolver metadata in `payload`; set `status='sources_gathered'` only after evidence stored.
- `monitor_task.md`: new findings → `research_records` `record_role='monitor'`.
- `analysis_task.md`, `analysis_section_task.md`, `analysis_audit_task.md`: read `research_records`; write `analysis_records` (one row/section); link via `analysis_links`; do not read `source_links` or removed company fields.
- `conclusions_task.md`: implement the ConclusionAgent flow (read `analysis_records`, extract typed facts per section, write `section_summaries`, upsert `dossiers`, write `dossier_links`, generate `summary_md`/`audit_md`, set `status='dossier_ready'`, run notion_sync for companies + dossiers). The write target is the new typed `dossiers` table.
- `dm_enrich_task.md`: write `contacts` with `name`/`contact_type`; `organization` for company-level channels; do not set `dm_enriched_at`; write a `contact_found` research record for auditability.
- `pipeline_task.md`, `pipeline_main_task.md`: update any table-name references to the new contract.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_pipeline_prompts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add agents/prompts/*.md tests/test_pipeline_prompts.py
git commit -m "docs(prompts): align all agent prompts to layered DB contract"
```

---

# Phase 4 — Smoke test (live)

### Task 16: Run one company end-to-end and verify new shape

**Files:** none (live verification; record output in PR).

- [ ] **Step 1: Run discovery → analysis → conclusions for one company**

Use the existing pipeline entrypoint for a single domain (per `agents/prompts/pipeline_main_task.md`). Then run the verification queries via Supabase MCP `execute_sql`:

```sql
SELECT record_type, record_role, source, observed_at, agent
FROM research_records ORDER BY created_at DESC LIMIT 5;

SELECT ar.section, count(al.research_record_id) AS linked
FROM analysis_records ar
LEFT JOIN analysis_links al ON al.analysis_record_id = ar.id
GROUP BY ar.section;

SELECT funding_stage, icp_fit, company_size,
       section_summaries->>'financials' AS fin_summary,
       length(summary_md) AS narrative_chars,
       (SELECT count(*) FROM dossier_links WHERE company_id = d.company_id) AS provenance_links
FROM dossiers d LIMIT 3;

SELECT contact_type, name, email FROM contacts LIMIT 10;
```

- [ ] **Step 2: Gate check**

Expected: research records written with correct `record_role`; each analysis section links ≥1 research record; the test company's dossier has typed fields + non-empty `summary_md` + provenance links; contacts show `contact_type`/`name`. If any check fails, fix the responsible Phase 3 code before proceeding to Phase 5. Do NOT drop legacy tables until this passes.

---

# Phase 5 — Drop legacy tables and columns (live)

### Task 17: Drop legacy tables and trim `companies`

**Files:**
- Create: `sql/migrations/027_drop_legacy.sql`

- [ ] **Step 1: Write the migration**

`sql/migrations/027_drop_legacy.sql`:

```sql
DROP TABLE IF EXISTS analysis_note_signals;
DROP TABLE IF EXISTS analysis_notes;
DROP TABLE IF EXISTS source_links;
DROP TABLE IF EXISTS dossiers_legacy;   -- old markdown dossiers, renamed in 024
DROP TABLE IF EXISTS signals;
DROP TABLE IF EXISTS signal_types;

-- FK constraints to signals already dropped in 026_contacts_v3.sql.
ALTER TABLE companies
    DROP COLUMN IF EXISTS last_signal_date,
    DROP COLUMN IF EXISTS last_verified,
    DROP COLUMN IF EXISTS funding_stage,
    DROP COLUMN IF EXISTS funding_amount,
    DROP COLUMN IF EXISTS funding_date,
    DROP COLUMN IF EXISTS team_size,
    DROP COLUMN IF EXISTS site_note,
    DROP COLUMN IF EXISTS website_snippet,
    DROP COLUMN IF EXISTS dm_enriched_at,
    DROP COLUMN IF EXISTS created_from_signal_id,
    DROP COLUMN IF EXISTS last_signal_id;

-- Drop the dm_enrichment partial index that referenced dm_enriched_at.
DROP INDEX IF EXISTS idx_companies_dm_enrichment;
```

- [ ] **Step 2: Apply via Supabase MCP** as migration `027_drop_legacy`. Run only after Task 16 passes.

- [ ] **Step 3: Commit**

```bash
git add sql/migrations/027_drop_legacy.sql
git commit -m "feat(db): drop legacy tables and trim companies columns"
```

---

# Phase 6 — Final verification + schema.sql + docs

### Task 18: Rewrite `sql/schema.sql` to the clean target and update contract tests

**Files:**
- Modify: `sql/schema.sql`, `tests/test_migrations.py`

- [ ] **Step 1: Write the failing test**

Rewrite `tests/test_migrations.py` expectations to the new contract:

```python
def test_schema_creates_current_runtime_tables() -> None:
    sql = _schema()
    for table in (
        "companies", "run_logs", "record_types", "research_records",
        "contacts", "analysis_records", "analysis_links",
        "dossiers", "dossier_links",
    ):
        assert f"CREATE TABLE {table}" in sql


def test_schema_has_no_legacy_tables() -> None:
    sql = _schema()
    for legacy in ("signals", "signal_types", "source_links",
                   "analysis_notes", "analysis_note_signals", "dossiers_legacy"):
        assert f"CREATE TABLE {legacy} (" not in sql


def test_companies_has_no_legacy_columns() -> None:
    body = _table_body(_schema(), "companies")
    for col in ("last_signal_date", "last_verified", "funding_stage",
                "funding_amount", "funding_date", "team_size", "site_note",
                "website_snippet", "dm_enriched_at",
                "created_from_signal_id", "last_signal_id"):
        assert col not in body


def test_contacts_uses_name_and_type() -> None:
    body = _table_body(_schema(), "contacts")
    assert "name" in body
    assert "contact_type" in body
    assert "first_name" not in body
    assert "last_name" not in body


def test_research_records_has_record_role() -> None:
    body = _table_body(_schema(), "research_records")
    assert "record_role" in body
    assert "observed_at" in body
    assert "record_type" in body
```

Remove the old assertions that required `signals`, `source_links`, `analysis_notes`, the old `dossiers` shape, and the `(company_id, lower(first_name), lower(last_name))` contact index.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_migrations.py -v`
Expected: FAIL — `schema.sql` still defines the legacy tables/columns.

- [ ] **Step 3: Rewrite `sql/schema.sql`**

Produce the clean target in FK-resolution order: `companies` (trimmed columns: `id, domain, name, website, linkedin_url, notion_page_id, notion_synced_at, status, icp_segment, description, created_at, updated_at`; keep `idx_companies_status/domain/segment/manual_review`, drop `idx_companies_dm_enrichment`) → `run_logs` (unchanged) → `record_types` (Task 2 body) → `research_records` (Task 3 table/index/trigger) → `contacts` (target DDL with `idx_contacts_dedup`, `idx_contacts_company_id`, `idx_contacts_email`, and `discovered_from_research_record_id`) → `analysis_records` (Task 4) → `analysis_links` (Task 5) → `dossiers` (Task 6 new shape, without the rename/copy) → `dossier_links` (Task 7). Update the header comment block (lines 1–9) to describe the new order and the three-group taxonomy. No legacy tables, no `companies → signals` provenance FKs.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add sql/schema.sql tests/test_migrations.py
git commit -m "feat(db): rewrite schema.sql to layered contract; update contract tests"
```

### Task 19: Final live verification

**Files:** none (live verification; record output in PR).

- [ ] **Step 1: Run the Phase 6 queries via Supabase MCP `execute_sql`**

```sql
SELECT table_name FROM information_schema.tables
WHERE table_schema='public' ORDER BY table_name;
-- Expected set: analysis_links, analysis_records, companies, contacts,
-- dossier_links, dossiers, record_types, research_records, run_logs

SELECT table_name FROM information_schema.tables
WHERE table_schema='public'
  AND table_name IN ('signals','signal_types','source_links',
    'analysis_notes','analysis_note_signals','dossiers_legacy');
-- Expected: 0 rows

SELECT column_name FROM information_schema.columns
WHERE table_name='companies'
  AND column_name IN ('last_signal_date','last_verified','funding_stage',
    'funding_amount','funding_date','team_size','site_note','website_snippet',
    'dm_enriched_at','created_from_signal_id','last_signal_id');
-- Expected: 0 rows

SELECT count(*) FROM research_records;            -- ≥ 74
SELECT record_role, count(*) FROM research_records GROUP BY record_role;
SELECT count(*) FROM dossiers;
```

- [ ] **Step 2: Gate check** — all expectations met. If not, identify which migration was skipped and re-apply.

### Task 20: Update documentation and mark superseded specs

**Files:**
- Modify: `docs/AGENT-ECOSYSTEM.md`, `docs/DB-FIELD-AUDIT-2026-06-18.md`, `README.md`, and the five superseded spec files
- Test: a doc-reference guard test

- [ ] **Step 1: Write the failing test**

Add `tests/test_docs_no_legacy_schema.py`:

```python
from pathlib import Path

ACTIVE_DOCS = [
    Path("docs/AGENT-ECOSYSTEM.md"),
    Path("README.md"),
]
LEGACY = ["source_links", "analysis_notes", "analysis_note_signals", "signal_types"]

def test_active_docs_have_no_legacy_tables():
    for doc in ACTIVE_DOCS:
        text = doc.read_text(encoding="utf-8")
        for token in LEGACY:
            assert token not in text, f"{doc} still references {token}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_docs_no_legacy_schema.py -v`
Expected: FAIL — active docs still mention legacy tables.

- [ ] **Step 3: Edit the docs**

In `docs/AGENT-ECOSYSTEM.md`: replace the table list with the three-group taxonomy and update each agent's write targets and the signal-model section (now research records). Use this exact grouping (it is the authoritative table catalogue):

```
### Данные
| Таблица | Роль |
|---|---|
| companies | Идентичность компании и статус в пайплайне |
| contacts  | Контакты и каналы — люди и орг-уровень |
| dossiers  | Финализированный профиль: структурные поля + саммари + нарратив |

### Процессные
| Таблица | Роль |
|---|---|
| research_records | Сырые наблюдения: всё что агент нашёл |
| analysis_records | Интерпретации: выводы агента на основе research_records |

### Технические
| Таблица | Роль |
|---|---|
| analysis_links | Какие research_records стоят за каждым analysis_record |
| dossier_links  | Какие analysis_records стоят за каждым полем dossiers |
| record_types   | Словарь допустимых типов для research_records |
| run_logs       | История запусков агентов, ошибки, диагностика |
```

In `docs/DB-FIELD-AUDIT-2026-06-18.md`: add a `> SUPERSEDED` banner and stop presenting removed fields as active. In `README.md`: update the storage section and status-model references to the new table names and grouping. Prepend this banner to each of the five superseded specs:

```
> SUPERSEDED — see 2026-06-19-database-agent-cleanup-FINAL.md
```

The five files: `2026-06-19-database-agent-cleanup-consolidated-design.md`, `2026-06-19-database-agent-cleanup-supplement.md`, `2026-06-19-company-profiles-dossier-consolidation.md`, `2026-06-19-company-contacts-cleanup-design.md`, `2026-06-19-signals-source-links-consolidation-design.md` (all under `docs/superpowers/specs/`).

- [ ] **Step 4: Run tests + full suite**

Run: `pytest tests/test_docs_no_legacy_schema.py -v && pytest -q`
Expected: PASS (whole suite green).

- [ ] **Step 5: Commit**

```bash
git add docs/ README.md tests/test_docs_no_legacy_schema.py
git commit -m "docs: three-group table taxonomy, mark superseded specs"
```

---

## Self-review notes (spec coverage + naming)

- **Naming scheme** (Данные/Процессные/Технические; `research_records`, `analysis_records`, `dossiers`, `analysis_links`, `dossier_links`, `record_types`) is applied in every migration, helper, prompt, and the docs (Task 20). The FINAL-spec names are mapped in the "Canonical naming" section.
- **`dossiers` collision** handled by renaming old → `dossiers_legacy` (Task 6) and dropping it in Task 17. `sql/schema.sql` (fresh install) only ever contains the new `dossiers`.
- **Target DDL** (all 9 tables) → Tasks 2–8, 18.
- **Migration Plan Phases 0–6** → Tasks 1–19 map 1:1 to spec phases.
- **Script Contract** (`supabase_store`, `dossier_store`, `enrichment`, `contacts_store`, dm scripts, `notion_sync`, `models`) → Tasks 9–14.
- **Agent Prompt Contract** (all agents incl. crypto guidance folded into source/monitor/analysis prompts) → Task 15.
- **Notion Projection** → Task 14.
- **Common Query Patterns** → read helpers in Task 10 and ConclusionAgent flow in Task 15.
- **Incremental Update Pattern** → supported by `upsert_dossier` (partial dict upsert) in Task 11 and the conclusions prompt in Task 15.
- **Testing** section requirements → distributed across Tasks 9–20.
- **Documentation Updates** → Task 20.

Deferred/None-goals respected: no scoring-model changes, no `source_links` compat view, no dossier history, no `source_links` backfill (Task 1 gate confirms it is empty).
