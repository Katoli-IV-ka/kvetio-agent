# Live Schema Snapshot — 2026-06-18 (before signals redesign)

Captured before `signals-redesign` migration series.

## Row Counts

| Table           | Rows |
|-----------------|------|
| signals         | 74   |
| companies       | 328  |
| contacts        | 0    |
| source_links    | 0    |
| analysis_notes  | 0    |
| dossiers        | 0    |

**No backfill needed** for `source_links`, `analysis_notes`, `dossiers` (empty).

## signals (live columns)

| Column           | Type        | Notes                        |
|------------------|-------------|------------------------------|
| id               | uuid        | PK, gen_random_uuid()        |
| normalized_domain| text        | FK → companies.domain        |
| source           | text        |                              |
| signal_type      | text        |                              |
| evidence_url     | text        | UNIQUE constraint            |
| signal_date      | date        |                              |
| confidence       | text        | default 'medium'             |
| parser_version   | text        | nullable                     |
| raw_data         | jsonb       | nullable, default '{}'       |
| created_at       | timestamptz | nullable, default now()      |

## companies (key columns for backfill)

- `id` uuid PK
- `domain` text UNIQUE

## source_links (live)

PK: id (uuid). Has: `company_domain TEXT`, `kind`, `url`, `source`, `confidence TEXT` (check high/medium/low), `found_via`, `raw`, `fetched_at`

## analysis_notes (live)

PK: id (uuid). Has: `company_domain TEXT`, `section` (check enum), `facts`, `sources JSONB`, `confidence TEXT`, `model`, `version`, `created_at`

## dossiers (live)

PK: `company_domain TEXT`. Has: `summary_md`, `sections`, `audit_md`, `table_fields`, `version`, `generated_at`, `notion_page_id`

## contacts (live)

PK: id. Already has `company_id UUID FK → companies.id`. No `discovered_from_signal_id` yet.
