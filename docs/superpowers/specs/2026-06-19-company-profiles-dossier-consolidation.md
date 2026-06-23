> SUPERSEDED — see 2026-06-19-database-agent-cleanup-FINAL.md

# Company Profiles & Dossier Consolidation — Design Supplement
**Date:** 2026-06-19
**Status:** Draft for review
**Supplements:**
- `docs/superpowers/specs/2026-06-19-database-agent-cleanup-consolidated-design.md`
- `docs/superpowers/specs/2026-06-19-database-agent-cleanup-supplement.md`

---

## Decision

`dossiers` is removed as a separate table. Its contents are absorbed into a new
`company_profiles` table, which becomes the single source of finalized knowledge
about a company. `companies` stays lean — identity and workflow state only.

**Why not merge into `companies`:** `companies` is read by every pipeline agent
at every stage just to check status or domain. Adding large text fields (summary_md)
would bloat every such read. The design principle for `companies` is current state
only, not accumulated knowledge.

**Why `company_profiles`:** it is already the finalized knowledge layer
(structured fields + section summaries). The narrative text is finalized knowledge
too, produced by the same ConclusionAgent in the same pass. One table, one
write, one source of truth for everything concluded about a company.

---

## Updated Global Data Model

```
┌──────────────────────────────────────────────────────────────────┐
│  IDENTITY + STATE                                                 │
│  companies          domain, name, website, status, icp_segment   │
└────────────┬─────────────────────────────────────────────────────┘
             │ company_id FK
     ┌───────┴────────────────────────────────┐
     │                                        │
     ▼                                        ▼
┌──────────────────────┐        ┌──────────────────────────┐
│  RAW OBSERVATION     │        │  TOUCHPOINTS             │
│  research_entries    │        │  contacts                │
│  one row = one raw   │        │  person or organization  │
│  finding             │        │  channel                 │
└──────────┬───────────┘        └──────────────────────────┘
           │ research_entry_id FK
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  PROVENANCE LINK                                                  │
│  analysis_entry_research_links                                    │
│  supports / contradicts / context                                 │
└────────────────────────┬─────────────────────────────────────────┘
                         │ analysis_entry_id FK
                         ▼
┌──────────────────────┐
│  INTERPRETATION      │
│  analysis_entries    │
│  one row = one       │
│  section of derived  │
│  conclusions         │
└──────────┬───────────┘
           │ analysis_entry_id FK
           ▼
┌──────────────────────────────────────────────────────────────────┐
│  PROVENANCE LINK (profile ← analysis)                            │
│  profile_analysis_links                                           │
│  which analysis entry contributed to which field / section       │
└────────────────────────┬─────────────────────────────────────────┘
                         │ company_id FK
                         ▼
┌──────────────────────────────────────────────────────────────────┐
│  FINALIZED KNOWLEDGE                                              │
│  company_profiles                                                 │
│  typed structured facts + section summaries + narrative dossier  │
│  one row per company, upsert                                      │
└──────────────────────────────────────────────────────────────────┘

VOCABULARY     research_entry_types
TECHNICAL      run_logs
```

### Complete table role summary (updated)

| Table | Role | Writers | Replaces |
|---|---|---|---|
| `companies` | Identity + workflow state | discovery, status agents | — |
| `research_entries` | Raw observations | all pipeline agents | `signals`, `source_links` |
| `analysis_entries` | Section-level interpretation | analysis agent | `analysis_notes` |
| `analysis_entry_research_links` | Provenance: research → analysis | analysis agent | `analysis_note_signals` |
| `company_profiles` | Finalized knowledge: structured + narrative | conclusions agent | `dossiers` (new) |
| `profile_analysis_links` | Provenance: analysis → profile | conclusions agent | new |
| `contacts` | Touchpoints: people + orgs | dm_enrich, source agents | — |
| `research_entry_types` | Vocabulary: entry type codes | migrations only | `signal_types` |
| `run_logs` | Runtime audit | agent runner | — |

---

## Target DDL

### `company_profiles`

```sql
CREATE TABLE company_profiles (
    company_id UUID PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,

    -- ── Typed structured fields ──────────────────────────────────────────
    -- Machine-readable. Can be filtered, sorted, displayed in Notion table.
    -- All nullable: not every company will have every field determined.

    funding_stage       TEXT,       -- 'pre-seed' | 'seed' | 'series_a' | 'series_b' |
                                    --  'series_c_plus' | 'bootstrapped' | 'unknown'
    funding_amount_usd  BIGINT,     -- latest round size in USD
    funding_date        DATE,       -- latest round close date
    company_size  TEXT,       -- '1-10' | '10-50' | '50-200' | '200-500' | '500+'
    product_category    TEXT,       -- e.g. 'MLOps', 'Data Infrastructure', 'AI Application'
    ai_use_case         TEXT,       -- what the company does with AI (short phrase)
    icp_fit             TEXT        -- 'strong' | 'moderate' | 'weak' | 'unknown'
                        CONSTRAINT company_profiles_icp_fit_check
                        CHECK (icp_fit IN ('strong', 'moderate', 'weak', 'unknown')),
    last_news_date      DATE,       -- date of most recent news signal

    -- Additional structured facts that do not have a named column yet.
    -- Agents may write arbitrary keys here; named columns are added by migration
    -- when a key becomes important enough to index or filter on.
    extra_facts         JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- ── Section text summaries ───────────────────────────────────────────
    -- One short paragraph per analysis section, written by ConclusionAgent.
    -- Keys match analysis_entries.section vocabulary.
    -- {"company": "...", "product": "...", "collaboration": "...",
    --  "financials": "...", "news": "...", "audit": "..."}
    section_summaries   JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- ── Narrative dossier (replaces dossiers table) ──────────────────────
    -- Full human-readable text generated from section_summaries and
    -- structured fields. Used for Notion dossier page and Telegram output.
    summary_md          TEXT,
    audit_md            TEXT,

    -- ── Notion binding ───────────────────────────────────────────────────
    notion_page_id      TEXT,       -- bound Notion dossier/profile page
    notion_synced_at    TIMESTAMPTZ,

    -- ── Meta ─────────────────────────────────────────────────────────────
    derived_from_model  TEXT,       -- model that produced this profile
    version             TEXT NOT NULL DEFAULT 'v1',
    derived_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_company_profiles_icp_fit
    ON company_profiles (icp_fit);
CREATE INDEX idx_company_profiles_funding_stage
    ON company_profiles (funding_stage);
CREATE INDEX idx_company_profiles_derived_at
    ON company_profiles (derived_at DESC);

DROP TRIGGER IF EXISTS trg_company_profiles_updated_at ON company_profiles;
CREATE TRIGGER trg_company_profiles_updated_at
BEFORE UPDATE ON company_profiles
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

### `profile_analysis_links`

Provenance junction: which `analysis_entries` rows were used to derive which
field or section in `company_profiles`.

```sql
CREATE TABLE profile_analysis_links (
    company_id          UUID NOT NULL REFERENCES company_profiles(company_id) ON DELETE CASCADE,
    analysis_entry_id   UUID NOT NULL REFERENCES analysis_entries(id) ON DELETE CASCADE,
    -- Which field or section this entry contributed to.
    -- Examples: 'funding_stage', 'company_size', 'financials', 'product'
    contributed_to      TEXT,
    PRIMARY KEY (company_id, analysis_entry_id)
);

CREATE INDEX idx_pal_analysis_entry ON profile_analysis_links (analysis_entry_id);
```

---

## Field Mapping from `dossiers`

Migration from the current `dossiers` table to `company_profiles`:

| `dossiers` field | `company_profiles` field | Notes |
|---|---|---|
| `company_id` | `company_id` | PK unchanged |
| `summary_md` | `summary_md` | direct copy |
| `sections` | `section_summaries` | direct copy (same JSONB structure) |
| `audit_md` | `audit_md` | direct copy |
| `table_fields` | typed columns + `extra_facts` | extract known keys into named columns; remainder → `extra_facts` |
| `notion_page_id` | `notion_page_id` | direct copy |
| `version` | `version` | direct copy |
| `generated_at` | `derived_at` | renamed |
| *(absent)* | `funding_stage` | extracted from `table_fields` or analysis |
| *(absent)* | `funding_amount_usd` | extracted from `table_fields` or analysis |
| *(absent)* | `company_size` | extracted from `table_fields` or analysis |
| *(absent)* | `icp_fit` | extracted from `table_fields` or analysis |
| *(absent)* | `section_summaries` | was `sections` |
| *(absent)* | `profile_analysis_links` | no provenance existed before; populated on next run |

---

## What Belongs Where in `company_profiles`

### Named typed column (add by migration when needed)

A fact goes into a named column when:
- it needs to be filterable or sortable in a query or Notion view;
- it is expected for most companies in the pipeline;
- its type is stable (TEXT, BIGINT, DATE, bounded enum).

Current named columns cover: funding stage, amount, date, team size, product
category, AI use case, ICP fit, last news date.

### `extra_facts` JSONB

A fact goes into `extra_facts` when:
- it is company-specific or rare;
- it is not yet worth a named column but the agent should preserve it;
- its type or shape is still evolving.

Examples: `{"token_ticker": "ACM", "exchange_listings": ["Binance", "Coinbase"],
"tech_stack": ["PyTorch", "vLLM"], "key_customers": ["OpenAI", "Cohere"]}`.

When a key in `extra_facts` becomes common and queryable, promote it to a named
column via migration.

### `section_summaries` JSONB

One paragraph per analysis section. Do not put typed facts here — typed facts
go in named columns. `section_summaries` is for the narrative explanation of
a section that supports `summary_md` generation.

### `summary_md`

The full human-readable dossier text assembled from `section_summaries` and
typed fields. Written last by ConclusionAgent. Used verbatim in Notion dossier
page body and Telegram summary.

---

## Updated ConclusionAgent Flow

```
1. SELECT companies WHERE status = 'analyzed'

2. For each company:

   a. Read analysis_entries (all sections) for company_id

   b. Extract structured facts from analysis_entries.facts JSONB:
      - funding_stage, funding_amount_usd, funding_date  ← from section 'financials'
      - company_size                                ← from section 'company'
      - product_category, ai_use_case                    ← from section 'product'
      - icp_fit                                           ← from section 'collaboration'
      - last_news_date                                    ← from section 'news'
      - everything else → extra_facts

   c. Write section_summaries (one paragraph per section)

   d. Write company_profiles (upsert by company_id)
      — typed fields, section_summaries, extra_facts, derived_from_model, version

   e. Write profile_analysis_links
      — one row per analysis_entry used, with contributed_to field name/section

   f. Generate summary_md from section_summaries + typed fields

   g. Update company_profiles.summary_md and company_profiles.audit_md

   h. UPDATE companies SET status = 'dossier_ready'

3. Run notion_sync for companies and company_profiles
```

**Key difference from current flow:** ConclusionAgent no longer writes to
`dossiers`. It writes everything to `company_profiles`. The Notion sync reads
`company_profiles` instead of `dossiers`.

---

## Incremental Update Pattern

When new `research_entries` arrive for an already-profiled company (e.g. a
monitor run finds new funding news), only the affected sections need to be
re-derived:

```
1. New research_entries written by MonitorAgent
2. AnalysisAgent re-runs only affected sections:
   - updates analysis_entries WHERE section = 'financials' AND company_id = ?
   - updates analysis_entries WHERE section = 'news' AND company_id = ?
3. ConclusionAgent re-derives only those fields:
   - updates company_profiles SET funding_stage = ?, funding_date = ?, ...
   - updates company_profiles SET section_summaries['financials'] = ?
   - optionally regenerates summary_md if triggered
4. profile_analysis_links updated for changed sections
```

This is the core gain: structured fields can be updated without regenerating the
full narrative. `summary_md` regeneration becomes an explicit step, not implicit.

---

## Script and Prompt Changes

### `scripts/dossier_store.py`

- Remove `upsert_dossier()`, `get_dossier()` and all dossier-related CLI
  commands.
- Add `upsert_company_profile(store, profile: dict) -> None`
  — upsert by `company_id`.
- Add `get_company_profile(store, company_id: str) -> dict | None`.
- Add `link_profile_to_analysis(store, company_id, analysis_entry_ids, contributed_to_map)`.
- Keep existing `upsert_analysis_entry()` and `link_analysis_to_research()` helpers
  (defined in the first supplement).

### `scripts/notion_sync.py`

- Replace `--entity dossiers` sync with `--entity company_profiles`.
- Read `company_profiles.summary_md` for Notion dossier page body.
- Read `company_profiles.section_summaries` for section blocks.
- Project typed columns to Notion properties:
  - `funding_stage` → Notion select
  - `company_size` → Notion select or text
  - `icp_fit` → Notion select
  - `product_category` → Notion text
  - `last_news_date` → Notion date
- Sync `notion_page_id` and `notion_synced_at` back to `company_profiles`.

### `agents/prompts/conclusions_task.md`

- Update input: read `analysis_entries` (not `analysis_notes`).
- Remove references to `dossiers` table.
- Document write target as `company_profiles` with explicit field list.
- Add step: write `profile_analysis_links`.
- Add section: incremental update instructions (which fields to update when only
  certain sections changed).

---

## Migration Steps (append to Phase 1 from first supplement)

After `analysis_entries` and `analysis_entry_research_links` exist:

```sql
-- Create company_profiles
CREATE TABLE company_profiles ...;
CREATE TABLE profile_analysis_links ...;

-- Migrate existing dossiers rows into company_profiles
INSERT INTO company_profiles (
    company_id,
    section_summaries,
    summary_md,
    audit_md,
    notion_page_id,
    version,
    derived_at,
    updated_at
)
SELECT
    company_id,
    sections,          -- maps to section_summaries
    summary_md,
    audit_md,
    notion_page_id,
    version,
    generated_at,
    NOW()
FROM dossiers;

-- profile_analysis_links: no data to migrate (provenance didn't exist before).
-- Links will be populated on the next ConclusionAgent run.
```

Drop `dossiers` in Phase 5 (after code is updated):

```sql
DROP TABLE IF EXISTS dossiers;
```

---

## Verification Queries

```sql
-- Confirm company_profiles exists, dossiers is gone
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name IN ('dossiers', 'company_profiles', 'profile_analysis_links');
-- Expected: company_profiles, profile_analysis_links only

-- Confirm typed columns exist
SELECT column_name FROM information_schema.columns
WHERE table_name = 'company_profiles'
  AND column_name IN (
    'funding_stage', 'funding_amount_usd', 'company_size',
    'icp_fit', 'product_category', 'section_summaries', 'summary_md'
  );
-- Expected: all 7 rows

-- Spot-check a profile after first ConclusionAgent run
SELECT
    cp.funding_stage,
    cp.icp_fit,
    cp.company_size,
    cp.section_summaries->>'financials' AS financials_summary,
    length(cp.summary_md) AS narrative_length,
    count(pal.analysis_entry_id) AS provenance_links
FROM company_profiles cp
LEFT JOIN profile_analysis_links pal ON pal.company_id = cp.company_id
GROUP BY cp.company_id, cp.funding_stage, cp.icp_fit,
         cp.company_size, cp.section_summaries, cp.summary_md
LIMIT 5;
```

---

## What Was Not Changed

- `analysis_entries` and `analysis_entry_research_links` — unchanged from
  first supplement; they remain the interpretation layer.
- `companies` — no new columns added; stays lean.
- `contacts` — unchanged from first supplement.
- `research_entries`, `research_entry_types` — unchanged from first supplement.
- Analysis section vocabulary ('company', 'product', 'collaboration',
  'financials', 'news', 'audit') — preserved in both `analysis_entries.section`
  and `company_profiles.section_summaries` keys.
