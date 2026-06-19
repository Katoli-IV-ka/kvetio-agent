# Database Field Audit - 2026-06-18

> SUPERSEDED — see 2026-06-19-database-agent-cleanup-FINAL.md

This audit described the pre-cleanup database shape and is retained only as
historical context. It is not an active schema contract.

Current source of truth:

- `sql/schema.sql` for fresh environments.
- `sql/migrations/` for live upgrade history.
- `scripts/models.py`, `scripts/supabase_store.py`, `scripts/dossier_store.py`,
  and `scripts/contacts_store.py` for runtime data access.
- `config/notion_mapping.yaml` for Notion projection.
- `tests/test_migrations.py` for the clean schema contract.

## Active Runtime Tables

### Данные

| Table | Role |
|---|---|
| `companies` | Company identity and pipeline status |
| `contacts` | People and organization-level contact channels |
| `dossiers` | Final typed profile fields, summaries, and narrative |

### Процессные

| Table | Role |
|---|---|
| `research_records` | Raw observations found by agents and adapters |
| `analysis_records` | Agent interpretation based on research records |

### Технические

| Table | Role |
|---|---|
| `analysis_links` | Research rows behind each analysis row |
| `dossier_links` | Analysis rows behind dossier fields |
| `record_types` | Governed vocabulary for research record types |
| `run_logs` | Agent run history, errors, and diagnostics |

## Current Contacts Contract

`contacts` stores the current outreach path for one company. It supports people
and organization-level channels through:

- `company_id` as the canonical FK to `companies.id`;
- `contact_type` with `person` or `organization`;
- `name` as the display identity;
- primary channel columns for email, phone, LinkedIn, X, Facebook, and Instagram;
- `other_channels` for secondary paths;
- `discovered_from_research_record_id` for provenance.

The dedup contract is `(company_id, contact_type, lower(name))`.

## Current Dossier Contract

`dossiers` stores one final profile per company. Structured fields, section
summaries, narrative markdown, audit markdown, model/version metadata, and
Notion sync fields live together in the final profile row.

Provenance is stored outside the final row:

- `analysis_links` connects analysis conclusions to raw research records.
- `dossier_links` connects dossier fields to analysis records.

## Verification Scope

The active schema and runtime contract are covered by:

- `tests/test_migrations.py`
- `tests/test_docs_no_legacy_schema.py`
- `tests/test_supabase_store.py`
- `tests/test_dossier_store.py`
- `tests/test_contacts_store.py`
- `tests/test_models_cleanup.py`
- `tests/test_notion_sync.py`
- `tests/test_pipeline_prompts.py`
- DM source tests
- `tests/test_contact_enricher.py`
