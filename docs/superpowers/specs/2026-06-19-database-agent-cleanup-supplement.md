> SUPERSEDED — see 2026-06-19-database-agent-cleanup-FINAL.md

# Database & Agent Cleanup — Supplement
**Date:** 2026-06-19
**Status:** Draft for review
**Supplements:** `docs/superpowers/specs/2026-06-19-database-agent-cleanup-consolidated-design.md`

This document closes the four open gaps identified during review of the consolidated
design and provides the global data model, full target DDL, and a safe migration
order.

---

## Confirmed Decisions

| # | Question | Decision |
|---|---|---|
| 1 | Is `research_entries` the renamed `signals`? | **Yes.** `signals` is renamed to `research_entries`. It absorbs `source_links` conceptually (both represent raw observations). `source_links` is dropped separately after confirming it is empty. |
| 2 | What happens to `signal_types`? | **Renamed to `research_entry_types`.** Same structure, same 17 seed rows. Vocabulary is preserved; existing type codes are kept as-is to avoid backfill. |
| 3 | What is the provenance table? | **`analysis_note_signals` is renamed and extended** into `analysis_entry_research_links`. New FKs reference `analysis_entries` and `research_entries`. The `role` column and `note` column are preserved. |
| 4 | Migration: what happens to the 74 `signals` rows? | **Copied into `research_entries`** during Phase 1 before the old table is dropped. The field mapping is described in the migration section below. |

---

## Global Data Model

This is the complete target picture. Every active table fits one of five roles.

```
┌─────────────────────────────────────────────────────────────────────┐
│  IDENTITY + STATE                                                    │
│  companies          canonical company card, workflow status          │
└────────────┬────────────────────────────────────────────────────────┘
             │ company_id FK
     ┌───────┴────────────────────────────────────┐
     │                                            │
     ▼                                            ▼
┌─────────────────────────┐         ┌─────────────────────────┐
│  RAW OBSERVATION        │         │  TOUCHPOINTS            │
│  research_entries       │         │  contacts               │
│  one row = one finding  │         │  person or organization │
│  about a company        │         │  channel                │
└────────────┬────────────┘         └─────────────────────────┘
             │ research_entry_id FK
             ▼
┌─────────────────────────────────────────────────────────────────────┐
│  PROVENANCE LINK                                                     │
│  analysis_entry_research_links                                       │
│  supports / contradicts / context                                    │
└────────────────────────┬────────────────────────────────────────────┘
                         │ analysis_entry_id FK
                         ▼
┌─────────────────────────┐
│  INTERPRETATION         │
│  analysis_entries       │
│  one row = one section  │
│  of derived conclusions │
└────────────┬────────────┘
             │ company_id FK (via dossiers)
             ▼
┌─────────────────────────┐
│  FINAL OUTPUT           │
│  dossiers               │
│  one row per company    │
│  ready for Notion sync  │
└─────────────────────────┘

VOCABULARY
  research_entry_types   governed codes for entry_type

TECHNICAL / RUNTIME
  run_logs               agent execution history, errors
```

### Table role summary

| Table | Role | Writers | Accumulates? |
|---|---|---|---|
| `companies` | Identity + state | discovery, relevance agents | No — upsert by domain |
| `research_entries` | Raw observation | all pipeline agents | Yes — append per finding |
| `analysis_entries` | Interpretation | analysis agent | Yes — per section per version |
| `analysis_entry_research_links` | Provenance | analysis agent | Yes — per link |
| `contacts` | Touchpoints | dm_enrich, source agents | Yes — per person/org |
| `dossiers` | Final output | conclusions agent | No — upsert by company |
| `research_entry_types` | Vocabulary | migrations only | No |
| `run_logs` | Runtime audit | agent runner | Yes — per run |

### What does NOT belong where

| Data | Wrong place | Right place |
|---|---|---|
| Funding stage conclusion | `companies.funding_stage` | `analysis_entries` (section: financials) |
| Last signal date | `companies.last_signal_date` | derive: `MAX(signal_date) FROM research_entries WHERE company_id = ?` |
| Verification freshness | `companies.last_verified` | derive: `MAX(signal_date) FROM research_entries WHERE entry_type LIKE 'verification_%'` |
| Raw funding article URL | `source_links` | `research_entries` (entry_type: funding_announcement) |
| GitHub org contact URL | `contacts.other_channels` where `contact_type='person'` | `contacts` row with `contact_type='organization'` |
| Agent execution errors | `signals` / `research_entries` | `run_logs` |
| Enrichment completion flag | `companies.dm_enriched_at` | derive from existence of contacts, or write a `contact_found` research entry |

---

## Target DDL

Full schema for the target state. This replaces the relevant sections of
`sql/schema.sql` after migration.

### `research_entry_types` (renamed from `signal_types`)

```sql
-- Renamed from signal_types. Existing 17 codes are preserved unchanged.
CREATE TABLE research_entry_types (
    code        TEXT PRIMARY KEY,
    category    TEXT NOT NULL,   -- discovery | people | sources | monitoring | financials | crypto
    description TEXT
);

INSERT INTO research_entry_types (code, category, description) VALUES
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
  -- Crypto-specific types (add as needed):
  -- ('token_page',           'crypto',     'Token/coin listing page'),
  -- ('exchange_listing',     'crypto',     'Exchange listing event'),
  -- ('ecosystem_reference',  'crypto',     'Reference in an ecosystem report')
```

### `research_entries` (renamed from `signals`)

Field-by-field mapping from `signals`:

| `signals` field | `research_entries` field | Change |
|---|---|---|
| `id` | `id` | — |
| `company_id` | `company_id` | — |
| `signal_type` | `entry_type` | renamed; FK now references `research_entry_types.code` |
| `agent` | `agent` | — |
| `source` | `source` | — |
| `title` | `title` | — |
| `url` | `url` | — |
| `summary` | `summary` | — |
| `confidence` | `confidence` | — |
| `signal_date` | `observed_at` | renamed for domain-neutrality |
| `payload` | `payload` | — |
| `raw_data` | `raw_data` | — |
| `run_id` | `run_id` | — |
| `dedupe_key` | `dedupe_key` | — |
| `created_at` | `created_at` | — |
| `updated_at` | `updated_at` | — |
| *(new)* | `entry_role` | added with DEFAULT 'evidence'; see role values below |

`entry_role` values:

| Value | Meaning |
|---|---|
| `primary` | First signal that brought the company into the pipeline |
| `verification` | Evidence gathered during relevance or verification stage |
| `source` | Supporting URL gathered during source expansion |
| `monitor` | New signal for an already-known company |
| `evidence` | Generic evidence (default; use when role is not yet determined) |

```sql
-- Renamed from signals. All existing rows are migrated (see migration section).
CREATE TABLE research_entries (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id  UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    entry_type  TEXT NOT NULL REFERENCES research_entry_types(code),
    agent       TEXT,
    source      TEXT NOT NULL,
    title       TEXT,
    url         TEXT,
    summary     TEXT,
    confidence  NUMERIC(3,2) NOT NULL DEFAULT 0.50
                CONSTRAINT research_entries_confidence_range
                CHECK (confidence >= 0 AND confidence <= 1),
    observed_at DATE NOT NULL,
    entry_role  TEXT NOT NULL DEFAULT 'evidence'
                CONSTRAINT research_entries_entry_role_check
                CHECK (entry_role IN ('primary', 'verification', 'source', 'monitor', 'evidence')),
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_data    JSONB          DEFAULT '{}'::jsonb,
    run_id      UUID REFERENCES run_logs(id),
    dedupe_key  TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_research_entries_company_id   ON research_entries (company_id);
CREATE INDEX idx_research_entries_company_type ON research_entries (company_id, entry_type);
CREATE INDEX idx_research_entries_observed_at  ON research_entries (observed_at DESC);
CREATE INDEX idx_research_entries_type         ON research_entries (entry_type);
CREATE INDEX idx_research_entries_role         ON research_entries (entry_role);
CREATE INDEX idx_research_entries_company_role ON research_entries (company_id, entry_role);

DROP TRIGGER IF EXISTS trg_research_entries_updated_at ON research_entries;
CREATE TRIGGER trg_research_entries_updated_at
BEFORE UPDATE ON research_entries
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### `analysis_entries` (renamed from `analysis_notes`)

Field mapping from `analysis_notes`:

| `analysis_notes` field | `analysis_entries` field | Change |
|---|---|---|
| `id` | `id` | — |
| `company_id` | `company_id` | — |
| `section` | `section` | check constraint preserved; can be extended |
| `facts` | `facts` | — |
| `confidence` | `confidence` | — |
| `model` | `model` | — |
| `version` | `version` | — |
| `created_at` | `created_at` | — |
| *(new)* | `updated_at` | added for consistency |

```sql
-- Renamed from analysis_notes.
CREATE TABLE analysis_entries (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    section    TEXT NOT NULL
               CONSTRAINT analysis_entries_section_check
               CHECK (section IN ('company', 'product', 'collaboration', 'financials', 'news', 'audit')),
    facts      JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(3,2) NOT NULL DEFAULT 0.50
               CONSTRAINT analysis_entries_confidence_check
               CHECK (confidence >= 0 AND confidence <= 1),
    model      TEXT,
    version    TEXT NOT NULL DEFAULT 'v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, section, version)
);

CREATE INDEX idx_analysis_entries_company ON analysis_entries (company_id);

DROP TRIGGER IF EXISTS trg_analysis_entries_updated_at ON analysis_entries;
CREATE TRIGGER trg_analysis_entries_updated_at
BEFORE UPDATE ON analysis_entries
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### `analysis_entry_research_links` (renamed from `analysis_note_signals`)

```sql
-- Renamed from analysis_note_signals.
-- FKs updated to reference analysis_entries and research_entries.
CREATE TABLE analysis_entry_research_links (
    analysis_entry_id   UUID NOT NULL REFERENCES analysis_entries(id)  ON DELETE CASCADE,
    research_entry_id   UUID NOT NULL REFERENCES research_entries(id)  ON DELETE CASCADE,
    role                TEXT NOT NULL DEFAULT 'supports'
                        CONSTRAINT aerl_role_check
                        CHECK (role IN ('supports', 'contradicts', 'context')),
    note                TEXT,
    PRIMARY KEY (analysis_entry_id, research_entry_id)
);

CREATE INDEX idx_aerl_research_entry ON analysis_entry_research_links (research_entry_id);
```

### `contacts` (modified)

Changes from current:
- `first_name TEXT NOT NULL` and `last_name TEXT NOT NULL DEFAULT ''` → replaced by `name TEXT NOT NULL`
- `contact_type TEXT NOT NULL DEFAULT 'person'` added
- `discovered_from_signal_id` → `discovered_from_research_entry_id` (FK target updated)
- Unique index updated to `(company_id, contact_type, lower(name))`

```sql
-- Modified: first_name/last_name → name, added contact_type,
-- discovered_from_signal_id renamed to discovered_from_research_entry_id.
CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id),

    contact_type TEXT NOT NULL DEFAULT 'person'
                 CONSTRAINT contacts_contact_type_check
                 CHECK (contact_type IN ('person', 'organization')),
    name TEXT NOT NULL,
    info TEXT,

    email        TEXT,
    phone        TEXT,
    linkedin_url TEXT,
    x_url        TEXT,
    facebook_url TEXT,
    instagram_url TEXT,

    other_channels JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT contacts_other_channels_is_array
        CHECK (jsonb_typeof(other_channels) = 'array'),

    discovered_from_research_entry_id UUID REFERENCES research_entries(id) ON DELETE SET NULL,

    notion_page_id   TEXT,
    notion_synced_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_contacts_company_type_name
    ON contacts (company_id, contact_type, lower(name));
CREATE INDEX idx_contacts_company_id
    ON contacts (company_id);
CREATE INDEX idx_contacts_email
    ON contacts (email)
    WHERE email IS NOT NULL;

DROP TRIGGER IF EXISTS trg_contacts_updated_at ON contacts;
CREATE TRIGGER trg_contacts_updated_at
BEFORE UPDATE ON contacts
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### `companies` (columns removed)

The table shape stays. Remove these columns and their FK constraints:

```sql
-- Remove FK constraints that reference signals (now deleted)
ALTER TABLE companies
    DROP CONSTRAINT IF EXISTS companies_created_from_signal_id_fkey,
    DROP CONSTRAINT IF EXISTS companies_last_signal_id_fkey;

-- Remove legacy derived-state and shortcut columns
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
```

`description TEXT` already exists and is kept.

Final `companies` columns after cleanup: `id`, `domain`, `name`, `website`,
`linkedin_url`, `notion_page_id`, `status`, `icp_segment`, `description`,
`notion_synced_at`, `created_at`, `updated_at`.

### `dossiers` and `run_logs`

No changes. Both tables are already correctly structured.

---

## Safe Migration Order

Migration is split into phases to ensure at no point does the runtime write
to a table that doesn't exist.

### Phase 0 — Preconditions

```sql
-- Must be 0 before proceeding
SELECT count(*) FROM source_links;

-- Record current signals count for post-migration verification
SELECT count(*) FROM signals;  -- expected: 74
```

### Phase 1 — Create new tables (additive, no downtime)

```sql
-- 1a. Create research_entry_types (replaces signal_types)
CREATE TABLE research_entry_types ...;
INSERT INTO research_entry_types ... (copy all 17 rows from signal_types);

-- 1b. Create research_entries (replaces signals)
CREATE TABLE research_entries ...;

-- 1c. Migrate data: signals → research_entries
INSERT INTO research_entries (
    id, company_id, entry_type, agent, source, title, url, summary,
    confidence, observed_at, entry_role, payload, raw_data, run_id,
    dedupe_key, created_at, updated_at
)
SELECT
    id,
    company_id,
    signal_type,   -- maps to entry_type; code values are preserved
    agent,
    source,
    title,
    url,
    summary,
    confidence,
    signal_date,   -- maps to observed_at
    -- Derive entry_role from signal_type prefix convention:
    CASE
        WHEN signal_type LIKE 'primary_%'      THEN 'primary'
        WHEN signal_type LIKE 'verification_%' THEN 'verification'
        WHEN signal_type LIKE 'monitor_%'      THEN 'monitor'
        WHEN signal_type = 'source_link'       THEN 'source'
        ELSE 'evidence'
    END,
    payload,
    raw_data,
    run_id,
    dedupe_key,
    created_at,
    updated_at
FROM signals;

-- Verify row count matches
SELECT count(*) FROM research_entries;  -- must equal count from signals

-- 1d. Create analysis_entries (replaces analysis_notes)
CREATE TABLE analysis_entries ...;

-- 1e. Migrate data: analysis_notes → analysis_entries
INSERT INTO analysis_entries (
    id, company_id, section, facts, confidence, model, version, created_at, updated_at
)
SELECT
    id, company_id, section, facts, confidence, model, version, created_at, NOW()
FROM analysis_notes;

-- 1f. Create analysis_entry_research_links (replaces analysis_note_signals)
CREATE TABLE analysis_entry_research_links ...;

-- 1g. Migrate data: analysis_note_signals → analysis_entry_research_links
-- Note: signal_id maps to research_entry_id because signals rows were
-- migrated with their original ids preserved.
INSERT INTO analysis_entry_research_links (
    analysis_entry_id, research_entry_id, role, note
)
SELECT
    analysis_note_id,
    signal_id,
    role,
    note
FROM analysis_note_signals;
```

### Phase 2 — Migrate `contacts` schema (requires brief code compatibility)

```sql
-- 2a. Add new columns (nullable initially to allow backfill)
ALTER TABLE contacts
    ADD COLUMN contact_type TEXT,
    ADD COLUMN name TEXT,
    ADD COLUMN discovered_from_research_entry_id UUID
        REFERENCES research_entries(id) ON DELETE SET NULL;

-- 2b. Backfill name and contact_type from existing data
UPDATE contacts
SET
    name = trim(first_name || ' ' || last_name),
    contact_type = 'person';

-- All existing contacts are people (organization type didn't exist).
-- discovered_from_research_entry_id maps from discovered_from_signal_id
-- because signals rows migrated with their original ids:
UPDATE contacts
SET discovered_from_research_entry_id = discovered_from_signal_id
WHERE discovered_from_signal_id IS NOT NULL;

-- 2c. Add NOT NULL constraints after backfill
ALTER TABLE contacts
    ALTER COLUMN name SET NOT NULL,
    ALTER COLUMN contact_type SET NOT NULL;

-- 2d. Add new unique index
CREATE UNIQUE INDEX idx_contacts_company_type_name
    ON contacts (company_id, contact_type, lower(name));

-- 2e. Drop old unique indexes and columns
DROP INDEX IF EXISTS idx_contacts_company_name;
DROP INDEX IF EXISTS idx_contacts_company_name_upsert;

ALTER TABLE contacts
    DROP COLUMN first_name,
    DROP COLUMN last_name,
    DROP COLUMN discovered_from_signal_id;
```

### Phase 3 — Update code to use new tables

Update in this order (earlier items unblock later ones):

1. `scripts/models.py`
   - Rename `SignalType` → `ResearchEntryType` (or keep alias for compatibility)
   - Rename `RawSignal.signal_date` → `RawSignal.observed_at`
   - Rename `RawSignal.signal_type` → `RawSignal.entry_type`
   - Add `RawSignal.entry_role: str = 'evidence'`
   - Rename `ContactRecord.first_name` / `last_name` → `ContactRecord.name`
   - Add `ContactRecord.contact_type: str = 'person'`

2. `scripts/supabase_store.py`
   - `upsert_company()`: stop writing all removed columns
   - `upsert_signal()` → `upsert_research_entry()`: write to `research_entries`,
     use `entry_type`, `observed_at`, `entry_role`
   - Read helpers: replace all `signals` table references

3. `scripts/dossier_store.py`
   - Remove `upsert_source_link()`, `get_source_links()`, CLI source-link commands
   - Rename `upsert_analysis_note()` → `upsert_analysis_entry()`
   - Rename junction helper: `link_note_to_signals()` → `link_analysis_to_research()`
   - Keep `upsert_dossier()`, `get_dossier()` unchanged

4. `scripts/enrichment.py`
   - Replace `upsert_source_link()` calls with `upsert_research_entry()`

5. `scripts/contacts_store.py`
   - Accept `name` and `contact_type`; remove `first_name`/`last_name`
   - Conflict key: `company_id,contact_type,name`
   - Remove `mark_enriched()`

6. `scripts/notion_sync.py`
   - Contact title: use `contacts.name`
   - Project `contacts.contact_type` to Notion select

7. `agents/prompts/*.md`
   - Replace all `signals` → `research_entries`
   - Replace `source_links` → `research_entries`
   - Replace `analysis_notes` → `analysis_entries`
   - Replace `signal_type` → `entry_type`, `signal_date` → `observed_at`
   - Remove references to dropped `companies` columns

### Phase 4 — Smoke test

Run a minimal end-to-end pass (one company, discovery → analysis → dossier)
and verify:

```sql
-- Research entries written with correct shape
SELECT id, company_id, entry_type, entry_role, source, observed_at, agent
FROM research_entries
ORDER BY created_at DESC
LIMIT 5;

-- Analysis entries reference research entries via provenance
SELECT ae.section, ae.confidence, count(aerl.research_entry_id) AS linked_entries
FROM analysis_entries ae
LEFT JOIN analysis_entry_research_links aerl ON aerl.analysis_entry_id = ae.id
GROUP BY ae.section, ae.confidence;

-- Contacts have new shape
SELECT contact_type, name, email, other_channels
FROM contacts
LIMIT 10;
```

### Phase 5 — Drop old tables and columns

Only run after Phase 4 verification passes.

```sql
-- Drop junction first (FK dependency)
DROP TABLE IF EXISTS analysis_note_signals;
DROP TABLE IF EXISTS analysis_notes;

-- Drop signals after confirming research_entries has all rows
DROP TABLE IF EXISTS source_links;    -- already empty
DROP TABLE IF EXISTS signals;

-- Drop vocabulary (after research_entries FK updated)
DROP TABLE IF EXISTS signal_types;

-- Remove legacy companies columns and FK constraints
ALTER TABLE companies
    DROP CONSTRAINT IF EXISTS companies_created_from_signal_id_fkey,
    DROP CONSTRAINT IF EXISTS companies_last_signal_id_fkey,
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
```

### Phase 6 — Final verification (from consolidated design)

Run all SQL verification queries from the original design spec, plus:

```sql
-- Verify research_entry_types exists and signal_types is gone
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('signal_types', 'research_entry_types', 'signals', 'research_entries',
                     'analysis_notes', 'analysis_entries', 'analysis_note_signals',
                     'analysis_entry_research_links', 'source_links');
-- Expected: only research_entry_types, research_entries, analysis_entries,
--           analysis_entry_research_links

-- Verify entry_role column and index exist
SELECT column_name FROM information_schema.columns
WHERE table_name = 'research_entries' AND column_name = 'entry_role';

-- Verify contacts new shape
SELECT column_name FROM information_schema.columns
WHERE table_name = 'contacts'
  AND column_name IN ('name', 'contact_type',
                      'first_name', 'last_name', 'discovered_from_signal_id');
-- Expected: name, contact_type only (no first_name, last_name, discovered_from_signal_id)
```

---

## Common Query Patterns (new contract)

These replace the patterns that previously read `companies` shortcut fields.

```sql
-- Latest observation date for a company
SELECT MAX(observed_at)
FROM research_entries
WHERE company_id = '<company_id>';

-- Verification freshness
SELECT MAX(observed_at)
FROM research_entries
WHERE company_id = '<company_id>'
  AND entry_role = 'verification';

-- All evidence for analysis (primary + source entries)
SELECT id, entry_type, url, summary, confidence, observed_at, payload
FROM research_entries
WHERE company_id = '<company_id>'
  AND entry_role IN ('primary', 'source', 'evidence')
ORDER BY observed_at DESC;

-- Funding evidence
SELECT payload, observed_at, url, confidence
FROM research_entries
WHERE company_id = '<company_id>'
  AND entry_type = 'funding_announcement'
ORDER BY observed_at DESC;

-- All touchpoints for outreach
SELECT contact_type, name, email, linkedin_url, other_channels
FROM contacts
WHERE company_id = '<company_id>'
ORDER BY contact_type, name;

-- Which research entries support an analysis conclusion
SELECT re.entry_type, re.url, re.summary, aerl.role
FROM analysis_entry_research_links aerl
JOIN research_entries re ON re.id = aerl.research_entry_id
WHERE aerl.analysis_entry_id = '<analysis_entry_id>';
```

---

## `models.py` Target Shapes

```python
# Renamed/updated dataclasses

ResearchEntryType = Literal[
    "job_posting", "hf_org", "hf_model", "github_repo", "papers_with_code",
    "funding_announcement", "kaggle_sponsor", "scale_customer", "wandb_run",
    "directory_listing", "contact_found", "source_link", "news",
    "product_update", "foundation_model", "proprietary_ai", "proprietary_models",
]

EntryRole = Literal["primary", "verification", "source", "monitor", "evidence"]

ContactType = Literal["person", "organization"]

@dataclass(frozen=True)
class ResearchEntry:
    """One raw observation about a company."""
    source: str
    entry_type: ResearchEntryType
    company_name: str
    domain: str | None
    linkedin_url: str | None
    url: str
    observed_at: date
    confidence: "Confidence | float"
    entry_role: EntryRole = "evidence"
    agent: str | None = None
    title: str | None = None
    summary: str | None = None
    payload: dict = field(default_factory=dict)
    raw_data: dict = field(default_factory=dict)

# Keep RawSignal as an alias during migration:
RawSignal = ResearchEntry  # deprecated alias, remove after all callers updated

@dataclass
class ContactRecord:
    """Person or organization-level touchpoint for a company."""
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
    other_channels: list[dict] = field(default_factory=list)
    discovered_from_research_entry_id: str | None = None
```

---

## What Was Not Changed

- `dossiers` — no schema changes needed
- `run_logs` — no schema changes needed
- `companies.status` workflow — no changes
- `companies.icp_segment` — no changes
- Analysis `section` vocabulary ('company', 'product', 'collaboration', 'financials', 'news', 'audit') — preserved
- `confidence` NUMERIC(3,2) convention — preserved across all tables
- `dedupe_key TEXT UNIQUE` on research entries — preserved from signals
- `other_channels JSONB` array convention in contacts — preserved
