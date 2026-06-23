# Database & Agent Cleanup — Final Spec
**Date:** 2026-06-19
**Status:** Ready for implementation planning
**Supersedes:**
- `docs/superpowers/specs/2026-06-19-database-agent-cleanup-consolidated-design.md`
- `docs/superpowers/specs/2026-06-19-database-agent-cleanup-supplement.md`
- `docs/superpowers/specs/2026-06-19-company-profiles-dossier-consolidation.md`
- `docs/superpowers/specs/2026-06-19-company-contacts-cleanup-design.md`
- `docs/superpowers/specs/2026-06-19-signals-source-links-consolidation-design.md`

---

## Goal

Replace the current schema — which mixes current state, raw evidence, and
derived shortcuts into the same tables — with a layered contract where each
table has exactly one role. Scripts and agents must work with this contract
exclusively; no legacy fields or removed tables.

---

## Problems Being Solved

- `companies` stores derived shortcuts: last signal date, verification date,
  funding fields, team size, website snippets, DM enrichment status. These
  create write conflicts between agents and go stale silently.
- `signals` and `source_links` both represent raw evidence but are separate
  tables, so analysis must read two places.
- `contacts` models only people through `first_name`/`last_name`. Agents also
  need to store org-level channels: company inboxes, GitHub orgs, Discord,
  social pages.
- `dossiers` stores the final narrative as markdown, so there is no finalized
  structured data. Updating one fact (e.g. a new funding round) requires
  regenerating the entire narrative.
- Several prompts still write old fields: `source_links`, `funding_stage` on
  `companies`, split contact names.

---

## Non-Goals

- Do not redesign the scoring model.
- Do not define the final research entry type vocabulary beyond what exists.
- Do not preserve backward-compatible reads from `source_links`.
- Do not keep `source_links` as a compatibility view.
- Do not backfill `source_links` (confirmed empty before this spec).
- Do not version dossier history; one profile per company is sufficient.

---

## All Decisions Confirmed

| Decision | Resolution |
|---|---|
| `research_entries` vs `signals` | `signals` is renamed to `research_entries`. It absorbs `source_links` conceptually. Both represent raw observations. |
| `signal_types` vocabulary table | Renamed to `research_entry_types`. All 17 codes preserved. |
| Provenance junction table | `analysis_note_signals` renamed and extended to `analysis_entry_research_links` with updated FK targets. |
| 74 existing `signals` rows | Copied into `research_entries` during Phase 1 with explicit field mapping. |
| `entry_role` column | Added to `research_entries` now with DEFAULT `'evidence'`. Not deferred — needed for efficient querying by pipeline stage. |
| `dossiers` table | Removed. Contents absorbed into new `company_profiles` table. |
| `dossiers` vs `companies` | Not merged into `companies` — `companies` is queried by every agent and must stay lean. |
| Contact name fields | `first_name` + `last_name` → single `name TEXT`. `contact_type` added. |
| DM enrichment completion | Derive from existence of contacts; or write a `contact_found` research entry for auditability. |
| Contacts dedup key | `(company_id, contact_type, lower(name))`. |
| Signal/source type vocabulary | Existing codes preserved as-is in `research_entry_types`. |

---

## Global Data Model

```
┌──────────────────────────────────────────────────────────────────┐
│  IDENTITY + STATE                                                 │
│  companies          domain · name · website · status             │
└────────────┬─────────────────────────────────────────────────────┘
             │ company_id FK
     ┌───────┴───────────────────────────────┐
     │                                       │
     ▼                                       ▼
┌─────────────────────────┐     ┌─────────────────────────────┐
│  RAW OBSERVATION        │     │  TOUCHPOINTS                │
│  research_entries       │     │  contacts                   │
│  one row = one finding  │     │  person or organization     │
└──────────┬──────────────┘     └─────────────────────────────┘
           │ research_entry_id FK
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  PROVENANCE: research → analysis                                  │
│  analysis_entry_research_links   supports / contradicts / context │
└──────────────────────────┬───────────────────────────────────────┘
                           │ analysis_entry_id FK
                           ▼
┌─────────────────────────┐
│  INTERPRETATION         │
│  analysis_entries       │
│  one row = one section  │
└──────────┬──────────────┘
           │ analysis_entry_id FK
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  PROVENANCE: analysis → profile                                   │
│  profile_analysis_links   contributed_to field/section            │
└──────────────────────────┬───────────────────────────────────────┘
                           │ company_id FK
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  FINALIZED KNOWLEDGE                                              │
│  company_profiles                                                 │
│  typed structured facts · section summaries · narrative dossier  │
└──────────────────────────────────────────────────────────────────┘

VOCABULARY     research_entry_types
TECHNICAL      run_logs
```

### Table role summary

| Table | Role | Writers | Replaces |
|---|---|---|---|
| `companies` | Identity + workflow state | discovery, status agents | — (trimmed) |
| `research_entries` | Raw observations | all pipeline agents | `signals` + `source_links` |
| `analysis_entries` | Section-level interpretation | analysis agent | `analysis_notes` |
| `analysis_entry_research_links` | Provenance: research → analysis | analysis agent | `analysis_note_signals` |
| `company_profiles` | Finalized knowledge: structured + narrative | conclusions agent | `dossiers` (new shape) |
| `profile_analysis_links` | Provenance: analysis → profile | conclusions agent | new |
| `contacts` | Touchpoints: people + orgs | dm_enrich, source agents | — (extended) |
| `research_entry_types` | Vocabulary: entry type codes | migrations only | `signal_types` |
| `run_logs` | Runtime audit | agent runner | — |

### What does NOT belong where

| Data | Wrong place | Correct place |
|---|---|---|
| Funding stage conclusion | `companies.funding_stage` | `company_profiles.funding_stage` |
| Latest signal date | `companies.last_signal_date` | `MAX(observed_at) FROM research_entries WHERE company_id = ?` |
| Verification freshness | `companies.last_verified` | `MAX(observed_at) FROM research_entries WHERE entry_role = 'verification'` |
| Raw funding article URL | `source_links` | `research_entries` (entry_type: `funding_announcement`) |
| GitHub org channel | `contacts.other_channels` where `contact_type='person'` | separate `contacts` row with `contact_type='organization'` |
| Agent execution errors | `research_entries` | `run_logs` |
| DM enrichment completion flag | `companies.dm_enriched_at` | derive from contacts existence |
| Section narrative text | `dossiers.sections` | `company_profiles.section_summaries` |
| Typed facts (funding, team size) | `dossiers.table_fields` JSONB | named columns on `company_profiles` |

---

## Target DDL

Table creation order: `companies` → `run_logs` → `research_entry_types` →
`research_entries` → `contacts` → `analysis_entries` →
`analysis_entry_research_links` → `company_profiles` → `profile_analysis_links`.

### `companies` (trimmed)

Remove FK constraints referencing `signals`, then remove legacy columns.
Final column set after cleanup:

```sql
-- Remove FK constraints (signals will be dropped)
ALTER TABLE companies
    DROP CONSTRAINT IF EXISTS companies_created_from_signal_id_fkey,
    DROP CONSTRAINT IF EXISTS companies_last_signal_id_fkey;

-- Remove legacy derived-state columns
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

Remaining columns: `id`, `domain`, `name`, `website`, `linkedin_url`,
`notion_page_id`, `notion_synced_at`, `status`, `icp_segment`, `description`,
`created_at`, `updated_at`. The `description` column already exists.

### `research_entry_types` (renamed from `signal_types`)

```sql
CREATE TABLE research_entry_types (
    code        TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    -- discovery | people | sources | monitoring | financials | crypto
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
  -- Crypto types (add as needed via migration):
  -- ('token_page', 'crypto', 'Token/coin listing page')
  -- ('exchange_listing', 'crypto', 'Exchange listing event')
  -- ('ecosystem_reference', 'crypto', 'Reference in an ecosystem report')
```

### `research_entries` (renamed from `signals`)

Field mapping from `signals`:

| `signals` | `research_entries` | Change |
|---|---|---|
| `signal_type` | `entry_type` | renamed; FK → `research_entry_types.code` |
| `signal_date` | `observed_at` | renamed for domain-neutrality |
| all other fields | same names | unchanged |
| *(new)* | `entry_role` | added; DEFAULT `'evidence'` |

`entry_role` values:

| Value | Meaning |
|---|---|
| `primary` | First signal that brought the company into the pipeline |
| `verification` | Evidence gathered during relevance or verification stage |
| `source` | Supporting URL gathered during source expansion |
| `monitor` | New signal for an already-known company |
| `evidence` | Generic (default; use when role is not yet determined) |

```sql
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
                CONSTRAINT re_confidence_range CHECK (confidence >= 0 AND confidence <= 1),
    observed_at DATE NOT NULL,
    entry_role  TEXT NOT NULL DEFAULT 'evidence'
                CONSTRAINT re_entry_role_check
                CHECK (entry_role IN ('primary', 'verification', 'source', 'monitor', 'evidence')),
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_data    JSONB          DEFAULT '{}'::jsonb,
    run_id      UUID REFERENCES run_logs(id),
    dedupe_key  TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_re_company_id    ON research_entries (company_id);
CREATE INDEX idx_re_company_type  ON research_entries (company_id, entry_type);
CREATE INDEX idx_re_observed_at   ON research_entries (observed_at DESC);
CREATE INDEX idx_re_type          ON research_entries (entry_type);
CREATE INDEX idx_re_role          ON research_entries (entry_role);
CREATE INDEX idx_re_company_role  ON research_entries (company_id, entry_role);

CREATE TRIGGER trg_re_updated_at
BEFORE UPDATE ON research_entries
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### Deduplication for `research_entries`

URL-backed entries: `company_id + entry_type + url` (SHA-1 stored in `dedupe_key`).

Non-URL entries fallback: `company_id + entry_type + source + external_id` where
`external_id` is stored in `payload`.

### `analysis_entries` (renamed from `analysis_notes`)

Field mapping from `analysis_notes`: all fields unchanged; `updated_at` added.

```sql
CREATE TABLE analysis_entries (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    section    TEXT NOT NULL
               CONSTRAINT ae_section_check
               CHECK (section IN ('company', 'product', 'collaboration',
                                  'financials', 'news', 'audit')),
    facts      JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(3,2) NOT NULL DEFAULT 0.50
               CONSTRAINT ae_confidence_check CHECK (confidence >= 0 AND confidence <= 1),
    model      TEXT,
    version    TEXT NOT NULL DEFAULT 'v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, section, version)
);

CREATE INDEX idx_ae_company ON analysis_entries (company_id);

CREATE TRIGGER trg_ae_updated_at
BEFORE UPDATE ON analysis_entries
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### `analysis_entry_research_links` (renamed from `analysis_note_signals`)

```sql
CREATE TABLE analysis_entry_research_links (
    analysis_entry_id UUID NOT NULL REFERENCES analysis_entries(id)  ON DELETE CASCADE,
    research_entry_id UUID NOT NULL REFERENCES research_entries(id)  ON DELETE CASCADE,
    role              TEXT NOT NULL DEFAULT 'supports'
                      CONSTRAINT aerl_role_check
                      CHECK (role IN ('supports', 'contradicts', 'context')),
    note              TEXT,
    PRIMARY KEY (analysis_entry_id, research_entry_id)
);

CREATE INDEX idx_aerl_research_entry ON analysis_entry_research_links (research_entry_id);
```

### `company_profiles` (replaces `dossiers`)

Single source of finalized knowledge per company. Updated by ConclusionAgent.
Two kinds of data live here side-by-side: typed structured fields (machine-readable,
filterable) and text content (section summaries + full narrative).

**When to use a named typed column vs `extra_facts`:**
- Named column: the fact is expected for most companies, has a stable type,
  and needs to be filtered or sorted (Notion table view, bot queries).
- `extra_facts`: company-specific, rare, or type still evolving. Promote to a
  named column via migration when the key becomes common and queryable.

```sql
CREATE TABLE company_profiles (
    company_id UUID PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,

    -- ── Typed structured fields ──────────────────────────────────────────
    funding_stage       TEXT,
    -- 'pre-seed' | 'seed' | 'series_a' | 'series_b' | 'series_c_plus'
    -- | 'bootstrapped' | 'unknown'
    funding_amount_usd  BIGINT,       -- latest round in USD
    funding_date        DATE,         -- latest round close date
    company_size  TEXT,         -- '1-10' | '10-50' | '50-200' | '200-500' | '500+'
    product_category    TEXT,         -- e.g. 'MLOps', 'Data Infrastructure'
    ai_use_case         TEXT,         -- short phrase: what the company does with AI
    icp_fit             TEXT
                        CONSTRAINT cp_icp_fit_check
                        CHECK (icp_fit IN ('strong', 'moderate', 'weak', 'unknown')),
    last_news_date      DATE,

    -- Overflow: structured facts without a named column yet.
    -- Example keys: token_ticker, tech_stack, key_customers, exchange_listings
    extra_facts         JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- ── Section text summaries ───────────────────────────────────────────
    -- One short paragraph per analysis section.
    -- Keys: company · product · collaboration · financials · news · audit
    section_summaries   JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- ── Narrative (replaces dossiers.summary_md / dossiers.sections) ────
    summary_md          TEXT,     -- full human-readable dossier narrative
    audit_md            TEXT,     -- audit section text

    -- ── Notion binding ───────────────────────────────────────────────────
    notion_page_id      TEXT,
    notion_synced_at    TIMESTAMPTZ,

    -- ── Meta ─────────────────────────────────────────────────────────────
    derived_from_model  TEXT,
    version             TEXT NOT NULL DEFAULT 'v1',
    derived_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_cp_icp_fit       ON company_profiles (icp_fit);
CREATE INDEX idx_cp_funding_stage ON company_profiles (funding_stage);
CREATE INDEX idx_cp_derived_at    ON company_profiles (derived_at DESC);

CREATE TRIGGER trg_cp_updated_at
BEFORE UPDATE ON company_profiles
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### `profile_analysis_links`

Provenance: which `analysis_entries` rows were used to derive which field or
section in `company_profiles`.

```sql
CREATE TABLE profile_analysis_links (
    company_id          UUID NOT NULL REFERENCES company_profiles(company_id) ON DELETE CASCADE,
    analysis_entry_id   UUID NOT NULL REFERENCES analysis_entries(id) ON DELETE CASCADE,
    contributed_to      TEXT,
    -- field name or section: 'funding_stage', 'company_size', 'financials', etc.
    PRIMARY KEY (company_id, analysis_entry_id)
);

CREATE INDEX idx_pal_analysis_entry ON profile_analysis_links (analysis_entry_id);
```

### `contacts` (extended)

`first_name` + `last_name` → `name`. `contact_type` added.
`discovered_from_signal_id` → `discovered_from_research_entry_id`.

```sql
CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id),

    contact_type  TEXT NOT NULL DEFAULT 'person'
                  CONSTRAINT contacts_type_check
                  CHECK (contact_type IN ('person', 'organization')),
    name          TEXT NOT NULL,
    info          TEXT,

    email         TEXT,
    phone         TEXT,
    linkedin_url  TEXT,
    x_url         TEXT,
    facebook_url  TEXT,
    instagram_url TEXT,

    other_channels JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT contacts_channels_array CHECK (jsonb_typeof(other_channels) = 'array'),

    discovered_from_research_entry_id UUID REFERENCES research_entries(id) ON DELETE SET NULL,

    notion_page_id   TEXT,
    notion_synced_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_contacts_dedup
    ON contacts (company_id, contact_type, lower(name));
CREATE INDEX idx_contacts_company_id ON contacts (company_id);
CREATE INDEX idx_contacts_email ON contacts (email) WHERE email IS NOT NULL;

CREATE TRIGGER trg_contacts_updated_at
BEFORE UPDATE ON contacts
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### `run_logs` and `research_entry_types`

No schema changes. `run_logs` stays as-is. `research_entry_types` replaces
`signal_types` with the same structure and seed rows.

---

## Common Query Patterns

Replaces patterns that previously read shortcut fields from `companies`.

```sql
-- Latest observation date for a company
SELECT MAX(observed_at)
FROM research_entries
WHERE company_id = '<id>';

-- Verification freshness
SELECT MAX(observed_at)
FROM research_entries
WHERE company_id = '<id>' AND entry_role = 'verification';

-- All evidence for analysis
SELECT id, entry_type, url, summary, confidence, observed_at, payload
FROM research_entries
WHERE company_id = '<id>'
  AND entry_role IN ('primary', 'source', 'evidence')
ORDER BY observed_at DESC;

-- Funding evidence
SELECT payload, observed_at, url, confidence
FROM research_entries
WHERE company_id = '<id>' AND entry_type = 'funding_announcement'
ORDER BY observed_at DESC;

-- All touchpoints for outreach
SELECT contact_type, name, email, linkedin_url, other_channels
FROM contacts
WHERE company_id = '<id>'
ORDER BY contact_type, name;

-- Which research entries support an analysis conclusion
SELECT re.entry_type, re.url, re.summary, aerl.role
FROM analysis_entry_research_links aerl
JOIN research_entries re ON re.id = aerl.research_entry_id
WHERE aerl.analysis_entry_id = '<analysis_entry_id>';

-- Why did the agent conclude this funding stage?
SELECT ae.section, ae.facts, pal.contributed_to
FROM profile_analysis_links pal
JOIN analysis_entries ae ON ae.id = pal.analysis_entry_id
WHERE pal.company_id = '<id>' AND pal.contributed_to = 'funding_stage';

-- Companies by ICP fit and funding stage (structured, no text parsing)
SELECT c.name, c.domain, cp.icp_fit, cp.funding_stage, cp.company_size
FROM company_profiles cp
JOIN companies c ON c.id = cp.company_id
WHERE cp.icp_fit = 'strong' AND cp.funding_stage IN ('series_a', 'series_b')
ORDER BY cp.derived_at DESC;
```

---

## Script Contract

### `scripts/supabase_store.py`

- `upsert_company()` writes only: `domain`, `name`, `website`, `linkedin_url`,
  `status`, `icp_segment`, `description`, `notion_page_id`, `notion_synced_at`.
  Stop writing all removed columns.
- Rename `upsert_signal()` → `upsert_research_entry()`. Write to
  `research_entries`. Use `entry_type`, `observed_at`, `entry_role`.
- Update all `signals` table references in read helpers to `research_entries`.
- Add read helpers:
  - `get_latest_research_entry(company_id)` — newest by `observed_at`
  - `get_verification_freshness(company_id)` — `MAX(observed_at)` where
    `entry_role = 'verification'`
  - `get_research_entries_for_analysis(company_id)` — `entry_role IN
    ('primary', 'source', 'evidence')`
  - `get_funding_entries(company_id)` — `entry_type = 'funding_announcement'`

### `scripts/dossier_store.py`

- Remove: `upsert_source_link()`, `get_source_links()`, all source-link CLI
  commands.
- Remove: `upsert_dossier()`, `get_dossier()`, all dossier CLI commands.
- Remove: `upsert_analysis_note()` → replace with `upsert_analysis_entry()`.
- Remove: `link_note_to_signals()` → replace with `link_analysis_to_research()`.
- Add: `upsert_company_profile(store, profile: dict) → None` — upsert by
  `company_id`.
- Add: `get_company_profile(store, company_id: str) → dict | None`.
- Add: `link_profile_to_analysis(store, company_id, analysis_entry_ids,
  contributed_to_map: dict[str, str]) → None`.
- Keep: `upsert_analysis_entry()`, `link_analysis_to_research()`.
- Add: convenience read helper `get_research_entries(store, company_id)` for
  analysis agent input (replaces `get_source_links`).

### `scripts/enrichment.py`

- Remove import and calls to `upsert_source_link()`.
- Resolvers return research-entry-shaped payloads.
- Write through `upsert_research_entry()` in `supabase_store.py`.
- Resolver-specific metadata (`kind`, `found_via`, external IDs, fetched
  timestamps) lives in `research_entries.payload`.

### `scripts/contacts_store.py`

- Accept `name` and `contact_type`. Remove `first_name`/`last_name`.
- Upsert conflict key: `company_id, contact_type, name`.
- For migration transition: accept `first_name` + `last_name` inbound and
  convert to `name = trim(first_name || ' ' || last_name)` with
  `contact_type = 'person'`. Remove this shim after first migration cycle.
- Remove `mark_enriched()`.
- `list_contacts()` orders by `contact_type, name`.
- Use `discovered_from_research_entry_id` (not `discovered_from_signal_id`).

### DM and contact source scripts

`dm_github.py`, `dm_huggingface_contacts.py`, `dm_apollo.py`, `dm_wellfound.py`,
`dm_team_page.py`, `dm_contact_page.py`:

- Output `contact_type = 'person'` for named people.
- Output `contact_type = 'organization'` for shared inboxes, company pages, org
  profiles, and generic contact forms.
- Use `name` instead of `first_name`/`last_name`.
- Set `discovered_from_research_entry_id` when the contact came from a known
  research entry.

### `scripts/notion_sync.py`

- **Contacts:** title → `contacts.name`; add Notion select for
  `contacts.contact_type`; company relation → `contacts.company_id →
  companies.notion_page_id`. Reverse sync writes `name` and `contact_type`.
- **Company profiles (replaces dossier sync):** `--entity company_profiles`
  replaces `--entity dossiers`. Read:
  - `summary_md` → Notion dossier page body
  - `section_summaries` → section blocks
  - `funding_stage`, `company_size`, `icp_fit`, `product_category`,
    `last_news_date` → Notion properties (select or text)
  - Sync `notion_page_id` and `notion_synced_at` back to `company_profiles`.
- Remove all references to `dossiers` table.

### `scripts/models.py`

```python
ResearchEntryType = Literal[
    "github_repo", "hf_org", "hf_model", "job_posting", "papers_with_code",
    "funding_announcement", "kaggle_sponsor", "scale_customer", "wandb_run",
    "directory_listing", "contact_found", "source_link", "news",
    "product_update", "foundation_model", "proprietary_ai", "proprietary_models",
]

EntryRole = Literal["primary", "verification", "source", "monitor", "evidence"]

ContactType = Literal["person", "organization"]

@dataclass(frozen=True)
class ResearchEntry:
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

# Deprecated alias — remove after all callers updated:
RawSignal = ResearchEntry

@dataclass
class ContactRecord:
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

## Agent Prompt Contract

All prompts must treat this spec as the active database contract.

### Discovery agent

- Write `companies` with current card fields only.
- Write primary evidence as `research_entries` with `entry_role = 'primary'`.
- Do not write `created_from_signal_id`, `last_signal_id`, `last_signal_date`,
  or any other removed field on `companies`.

### Relevance and verification agents

- Update only `companies.status` for workflow state.
- Write verification evidence as `research_entries` with
  `entry_role = 'verification'`.
- Do not write `last_verified` on `companies`.

### Source expansion and enrichment agents

- Write supporting URLs as `research_entries` with `entry_role = 'source'`.
  Do not write to `source_links`.
- Keep resolver-specific metadata in `research_entries.payload`.
- Set `companies.status = 'sources_gathered'` only after evidence is stored as
  research entries.

### Monitor agent

- Write new findings as `research_entries` with `entry_role = 'monitor'`.

### Analysis agent

- Read `research_entries` as evidence input.
- Write interpretations to `analysis_entries` (one row per section).
- Link each `analysis_entries` row to the `research_entries` rows it used via
  `analysis_entry_research_links` with appropriate role
  (`supports` / `contradicts` / `context`).
- Do not read `source_links` or removed company fields.

### Conclusions agent

```
1. SELECT companies WHERE status = 'analyzed'
2. For each company:
   a. Read analysis_entries for company_id
   b. Extract typed facts from analysis_entries.facts:
      - funding_stage, funding_amount_usd, funding_date  ← section 'financials'
      - company_size                                ← section 'company'
      - product_category, ai_use_case                    ← section 'product'
      - icp_fit                                           ← section 'collaboration'
      - last_news_date                                    ← section 'news'
      - everything else → extra_facts
   c. Write section_summaries (one paragraph per section)
   d. Write company_profiles (upsert by company_id)
   e. Write profile_analysis_links
      (one row per analysis_entry used, with contributed_to value)
   f. Generate summary_md from section_summaries + typed fields
   g. Update company_profiles.summary_md and audit_md
   h. UPDATE companies SET status = 'dossier_ready'
3. Run notion_sync for companies and company_profiles
```

Do not write to `dossiers` (table removed). Final output target is
`company_profiles`.

### DM enrichment agent

- Write touchpoints to `contacts`.
- Use `contact_type = 'person'` for named people; `contact_type = 'organization'`
  for company-level channels (GitHub org, Discord, Telegram, shared inbox, etc.).
- Do not set `companies.dm_enriched_at`.
- For auditability: write a `contact_found` research entry linked to the contact.

### Crypto agents

- Token pages, exchange listings, GitHub repos, docs, funding announcements,
  ecosystem references → `research_entries`.
- Discord, Telegram, X, docs site, GitHub org, contact forms →
  `contacts` with `contact_type = 'organization'` unless a named person is
  identified.
- Interpreted maturity, traction, funding, collaboration fit →
  `analysis_entries`.
- Final narrative → `company_profiles`.
- Do not use removed company fields or `source_links`.

---

## Notion Projection

### Companies

- title: `companies.name`
- ICP segment, website, LinkedIn, status (optional)
- No derived evidence fields

### Contacts

- title: `contacts.name`
- type select: `contacts.contact_type`
- company relation: `contacts.company_id → companies.notion_page_id`
- primary channels: email, phone, LinkedIn, X, Facebook, Instagram
- secondary channels: rendered from `other_channels`

### Company profiles (replaces dossier Notion pages)

- page body: `company_profiles.summary_md`
- section blocks: `company_profiles.section_summaries`
- Notion properties (table view): `funding_stage`, `company_size`,
  `icp_fit`, `product_category`, `last_news_date`
- Notion binding: `company_profiles.notion_page_id` / `notion_synced_at`

---

## Incremental Update Pattern

After the initial profile is generated, monitor runs trigger partial updates:

```
1. MonitorAgent writes new research_entries (entry_role = 'monitor')
2. AnalysisAgent re-runs only affected sections:
   - UPDATE analysis_entries WHERE section = 'financials' AND company_id = ?
   - UPDATE analysis_entries WHERE section = 'news' AND company_id = ?
3. ConclusionAgent updates only changed fields:
   - UPDATE company_profiles SET funding_stage = ?, funding_date = ?, ...
   - UPDATE company_profiles SET section_summaries['financials'] = ?
   - UPDATE profile_analysis_links for changed sections
4. summary_md regeneration is explicit, triggered separately
```

This is the core gain of structured storage: typed fields update without
regenerating the full narrative.

---

## Migration Plan

### Phase 0 — Preconditions

```sql
SELECT count(*) FROM source_links;  -- must be 0
SELECT count(*) FROM signals;       -- record: expected 74
SELECT count(*) FROM analysis_notes;
SELECT count(*) FROM dossiers;
```

### Phase 1 — Create new tables (additive, no downtime)

```sql
-- 1a. Vocabulary
CREATE TABLE research_entry_types ...;
INSERT INTO research_entry_types ... (all 17 rows);

-- 1b. Raw observation table
CREATE TABLE research_entries ...;

-- 1c. Migrate signals → research_entries (preserve all 74 rows and IDs)
INSERT INTO research_entries (
    id, company_id, entry_type, agent, source, title, url, summary,
    confidence, observed_at, entry_role, payload, raw_data,
    run_id, dedupe_key, created_at, updated_at
)
SELECT
    id, company_id,
    signal_type,    -- code values map 1:1 to research_entry_types
    agent, source, title, url, summary, confidence,
    signal_date,    -- → observed_at
    CASE
        WHEN signal_type LIKE 'primary_%'      THEN 'primary'
        WHEN signal_type LIKE 'verification_%' THEN 'verification'
        WHEN signal_type LIKE 'monitor_%'      THEN 'monitor'
        WHEN signal_type = 'source_link'       THEN 'source'
        ELSE 'evidence'
    END,            -- → entry_role
    payload, raw_data, run_id, dedupe_key, created_at, updated_at
FROM signals;

SELECT count(*) FROM research_entries; -- must equal signals count

-- 1d. Interpretation table
CREATE TABLE analysis_entries ...;

-- 1e. Migrate analysis_notes → analysis_entries (preserve IDs)
INSERT INTO analysis_entries (
    id, company_id, section, facts, confidence, model, version,
    created_at, updated_at
)
SELECT id, company_id, section, facts, confidence, model, version,
       created_at, NOW()
FROM analysis_notes;

-- 1f. Provenance junction
CREATE TABLE analysis_entry_research_links ...;

-- 1g. Migrate analysis_note_signals → analysis_entry_research_links
-- signal_id maps directly to research_entry_id because IDs were preserved
INSERT INTO analysis_entry_research_links (
    analysis_entry_id, research_entry_id, role, note
)
SELECT analysis_note_id, signal_id, role, note
FROM analysis_note_signals;

-- 1h. Company profiles (replaces dossiers)
CREATE TABLE company_profiles ...;

-- 1i. Migrate dossiers → company_profiles
INSERT INTO company_profiles (
    company_id, section_summaries, summary_md, audit_md,
    notion_page_id, version, derived_at, updated_at
)
SELECT
    company_id,
    sections,       -- → section_summaries
    summary_md,
    audit_md,
    notion_page_id,
    version,
    generated_at,   -- → derived_at
    NOW()
FROM dossiers;
-- Typed fields (funding_stage, etc.) will be populated on next ConclusionAgent run.
-- profile_analysis_links: no data to migrate (provenance didn't exist).

-- 1j. Provenance junction for profiles
CREATE TABLE profile_analysis_links ...;
```

### Phase 2 — Migrate `contacts` schema

```sql
-- 2a. Add new columns (nullable for backfill)
ALTER TABLE contacts
    ADD COLUMN contact_type TEXT,
    ADD COLUMN name TEXT,
    ADD COLUMN discovered_from_research_entry_id UUID
        REFERENCES research_entries(id) ON DELETE SET NULL;

-- 2b. Backfill
UPDATE contacts SET
    name = trim(first_name || ' ' || last_name),
    contact_type = 'person',
    discovered_from_research_entry_id = discovered_from_signal_id;

-- 2c. Add NOT NULL
ALTER TABLE contacts
    ALTER COLUMN name SET NOT NULL,
    ALTER COLUMN contact_type SET NOT NULL;

-- 2d. New unique index
CREATE UNIQUE INDEX idx_contacts_dedup
    ON contacts (company_id, contact_type, lower(name));

-- 2e. Drop old indexes and columns
DROP INDEX IF EXISTS idx_contacts_company_name;
DROP INDEX IF EXISTS idx_contacts_company_name_upsert;
ALTER TABLE contacts
    DROP COLUMN first_name,
    DROP COLUMN last_name,
    DROP COLUMN discovered_from_signal_id;
```

### Phase 3 — Update code

Order:
1. `scripts/models.py` — rename dataclasses, add `RawSignal` alias
2. `scripts/supabase_store.py` — update `upsert_company()`, rename signal helpers
3. `scripts/dossier_store.py` — remove source-link and dossier helpers, add
   company profile helpers
4. `scripts/enrichment.py` — switch to `upsert_research_entry()`
5. `scripts/contacts_store.py` — new payload shape, new conflict key
6. `scripts/dm_*.py` — new contact payload
7. `scripts/notion_sync.py` — company profiles sync, updated contacts sync
8. `agents/prompts/*.md` — new table names throughout

### Phase 4 — Smoke test

Run one company through discovery → analysis → conclusions. Verify:

```sql
-- Research entries written correctly
SELECT entry_type, entry_role, source, observed_at, agent
FROM research_entries
ORDER BY created_at DESC LIMIT 5;

-- Analysis provenance intact
SELECT ae.section, count(aerl.research_entry_id) AS linked
FROM analysis_entries ae
LEFT JOIN analysis_entry_research_links aerl ON aerl.analysis_entry_id = ae.id
GROUP BY ae.section;

-- Company profile has structured fields and narrative
SELECT funding_stage, icp_fit, company_size,
       section_summaries->>'financials' AS fin_summary,
       length(summary_md) AS narrative_chars,
       (SELECT count(*) FROM profile_analysis_links
        WHERE company_id = cp.company_id) AS provenance_links
FROM company_profiles cp LIMIT 3;

-- Contacts have new shape
SELECT contact_type, name, email FROM contacts LIMIT 10;
```

### Phase 5 — Drop legacy tables and columns

Run only after Phase 4 passes.

```sql
DROP TABLE IF EXISTS analysis_note_signals;
DROP TABLE IF EXISTS analysis_notes;
DROP TABLE IF EXISTS source_links;
DROP TABLE IF EXISTS dossiers;
DROP TABLE IF EXISTS signals;
DROP TABLE IF EXISTS signal_types;

-- Remove legacy companies columns (FK constraints already dropped in Phase 1)
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

### Phase 6 — Final verification

```sql
-- Active tables only
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
ORDER BY table_name;
-- Expected: analysis_entries, analysis_entry_research_links,
--           companies, company_profiles, contacts,
--           profile_analysis_links, research_entries, research_entry_types,
--           run_logs

-- No legacy tables
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN (
    'signals', 'signal_types', 'source_links',
    'analysis_notes', 'analysis_note_signals', 'dossiers'
  );
-- Expected: 0 rows

-- No legacy companies columns
SELECT column_name FROM information_schema.columns
WHERE table_name = 'companies'
  AND column_name IN (
    'last_signal_date', 'last_verified', 'funding_stage', 'funding_amount',
    'funding_date', 'team_size', 'site_note', 'website_snippet',
    'dm_enriched_at', 'created_from_signal_id', 'last_signal_id'
  );
-- Expected: 0 rows

-- Contacts new shape
SELECT column_name FROM information_schema.columns
WHERE table_name = 'contacts'
  AND column_name IN (
    'name', 'contact_type',
    'first_name', 'last_name', 'discovered_from_signal_id'
  );
-- Expected: name, contact_type only

-- Research entries migrated
SELECT count(*) FROM research_entries; -- must be >= 74

-- Company profiles populated
SELECT count(*) FROM company_profiles;

-- entry_role distribution
SELECT entry_role, count(*) FROM research_entries GROUP BY entry_role;
```

---

## Testing

Update or add tests for:

- **Schema:** `source_links`, `signals`, `signal_types`, `analysis_notes`,
  `analysis_note_signals`, `dossiers` absent; legacy `companies` columns absent;
  `contacts.name` and `contacts.contact_type` exist; `research_entries.entry_role`
  exists.
- **Research entries:** insert/dedupe behavior; `entry_role` defaults and
  constraint; `observed_at` field.
- **Enrichment:** resolvers write to `research_entries`, not `source_links`.
- **Analysis entries:** insert/upsert by `(company_id, section, version)`;
  `analysis_entry_research_links` rows created with correct role.
- **Company profiles:** upsert by `company_id`; typed fields populated from
  analysis; `profile_analysis_links` rows created; `summary_md` present.
- **Contacts store:** new payload shape; dedup by `(company_id, contact_type,
  lower(name))`; `organization` type accepted.
- **Notion sync:** contact title uses `name`, type projected; company profile
  sync reads `company_profiles` not `dossiers`; `funding_stage` and `icp_fit`
  projected.
- **Prompts:** no mention of `source_links`, removed `companies` fields, or
  `dossiers` as write targets.
- **Documentation:** active docs do not reference removed schema.

---

## Documentation Updates Required

After implementation:

- `docs/AGENT-ECOSYSTEM.md` — update table list, agent write targets, signal
  model section (now research entries)
- `docs/DB-FIELD-AUDIT-2026-06-18.md` — mark superseded; do not present removed
  fields as active
- `README.md` — update storage section, status model references
- `agents/prompts/*.md` — all prompts updated (covered in Phase 3)
- `config/notion_mapping.yaml` — update contact field names, dossier → company
  profile references
- Active contract reference: this file —
  `docs/superpowers/specs/2026-06-19-database-agent-cleanup-FINAL.md`

Old design docs keep historical context but must carry a header:

```
> SUPERSEDED — see 2026-06-19-database-agent-cleanup-FINAL.md
```
