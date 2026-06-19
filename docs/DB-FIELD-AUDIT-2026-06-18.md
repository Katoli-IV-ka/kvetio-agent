# Database Field Audit - 2026-06-18

## Changelog

### signals redesign (2026-06-18)

- `signals` table re-keyed from `normalized_domain TEXT` to `company_id UUID`
  (FK → `companies.id`).
- Added `signal_types` vocabulary table with 17 seed rows; `signal_type` column
  now has an FK constraint.
- Added `dedupe_key TEXT UNIQUE` (SHA-1 of `company_id:signal_type:url`) for
  idempotent upserts.
- `confidence` changed from `TEXT` to `NUMERIC(3,2)` (0.00–1.00).
- Added `payload JSONB` (structured agent fields) and `raw_data JSONB` (optional
  raw snapshot).
- `evidence_url` renamed to `url` in `RawSignal` dataclass and all adapters.
- `source_links`, `analysis_notes`, `dossiers` re-keyed from `company_domain`
  to `company_id UUID`.
- Added `analysis_note_signals` junction table.
- Provenance FKs added: `signals.discovered_from_signal_id`,
  `contacts.discovered_from_signal_id`.
- All prompt files updated; no stale `evidence_url`/`normalized_domain` refs
  remain.
- Test suite: 258 tests pass, ruff clean.

Source of truth: `sql/schema.sql`, runtime scripts under `scripts/`, prompts
under `agents/prompts/`, Notion mapping in `config/notion_mapping.yaml`, and
pytest contracts under `tests/`.

Historical test-era migrations are not part of the active runtime contract.
`sql/schema.sql` is the clean baseline.

## Runtime Tables

Active tables:

- `companies`
- `signals`
- `run_logs`
- `contacts`
- `source_links`
- `analysis_notes`
- `dossiers`

Removed runtime objects:

- `pipeline_runs`
- `bot_users`
- `bot_dialog_state`
- `bot_presets`
- `contact_companies`
- `github_org_cache`
- `recent_leads`
- `pipeline_stats`

## Contacts

`contacts` stores the current outreach contact for one company. It answers:
who the contact is, what context matters, and which channels can reach them.

Fields:

| Field | Type | Required | Default | Purpose |
|---|---|---:|---|---|
| `id` | `UUID` | yes | `gen_random_uuid()` | Primary key |
| `company_id` | `UUID` | yes | none | FK to `companies.id` |
| `first_name` | `TEXT` | yes | none | Structured given name |
| `last_name` | `TEXT` | yes | `''` | Structured family name, empty when unknown |
| `info` | `TEXT` | no | none | Human-readable role/context |
| `email` | `TEXT` | no | none | Primary channel |
| `phone` | `TEXT` | no | none | Primary channel |
| `linkedin_url` | `TEXT` | no | none | Primary channel |
| `x_url` | `TEXT` | no | none | Primary channel |
| `facebook_url` | `TEXT` | no | none | Primary channel |
| `instagram_url` | `TEXT` | no | none | Primary channel |
| `other_channels` | `JSONB` | yes | `[]` | Secondary channels only |
| `notion_page_id` | `TEXT` | no | none | Notion page binding |
| `notion_synced_at` | `TIMESTAMPTZ` | no | none | Last Notion sync timestamp |
| `created_at` | `TIMESTAMPTZ` | yes | `NOW()` | Insert timestamp |
| `updated_at` | `TIMESTAMPTZ` | yes | `NOW()` | Trigger-updated timestamp |

Keys and indexes:

- PK: `id`
- FK: `company_id -> companies.id`
- Unique dedup key: `company_id`, lowercased `first_name`, lowercased `last_name`
- Lookup index: `company_id`
- Email index: `email` where present

`last_name` is intentionally stored as an empty string when unknown so the
unique name key cannot create multiple rows through nullable name parts.

Primary channels (`email`, `phone`, `linkedin_url`, `x_url`, `facebook_url`,
`instagram_url`) are never duplicated in `other_channels`. `other_channels`
stores secondary paths such as GitHub, HuggingFace, personal website, Calendly,
Telegram, Discord, YouTube, Medium, Substack, Google Scholar, Crunchbase,
Wellfound, or `other`.

## Contacts Runtime Ownership

Writers:

- `scripts/contacts_store.py`
- DM source scripts
- `scripts/contact_enricher.py`

Readers:

- `scripts/contacts_store.py`
- `scripts/contact_enricher.py`
- `scripts/notion_sync.py`

Runtime behavior:

- `contacts_store.upsert_contact()` resolves a company to `company_id` before
  writing a contact.
- Upsert conflict target is `company_id,first_name,last_name`.
- Legacy incoming names are accepted by the store layer and split into
  structured name fields.
- Legacy social profile inputs are normalized into full URLs or
  `other_channels`.

## Notion Contacts Projection

Forward mapping:

| DB/computed field | Notion property | Type |
|---|---|---|
| `contact_name` | `Name` | title |
| `info` | `Информация о контакте` | rich text |
| `email` | `Email` | email |
| `phone` | `Phone` | phone |
| `linkedin_url` | `LinkedIn` | url |
| `x_url` | `X` | url |
| `facebook_url` | `Facebook` | url |
| `instagram_url` | `Instagram` | url |
| `other_channels_text` | `Другие каналы` | rich text |
| `company_page_ids` | `Компании` | relation |

`notion_sync.py` computes display-only fields before forward sync:

- `contact_name` from `first_name` and `last_name`
- `other_channels_text` from `other_channels`
- `company_page_ids` from `company_id -> companies.notion_page_id`

Reverse sync for contacts is not part of the active operating model.

## Current Non-Contact Notes

- `signals` remains the append-only evidence table.
- `source_links`, `analysis_notes`, and `dossiers` still use their existing
  company-domain business keys.
- `run_logs.finished_at` is still read by status surfaces and should be closed
  consistently by runners in a later cleanup.
- `scripts/notify.py` still needs a separate pass to remove old score-oriented
  wording.

## Verification Scope

The contacts simplification is covered by:

- `tests/test_migrations.py`
- `tests/test_contacts_store.py`
- `tests/test_models_cleanup.py`
- `tests/test_notion_sync.py`
- `tests/test_pipeline_prompts.py`
- DM source tests
- `tests/test_contact_enricher.py`
