# Database Field Audit — 2026-06-16

Supabase project: `Kvetio Project` / `qcfygtxkohopxhsathkv`  
Schema: `public`  
Source of truth for this audit: live Supabase schema, migrations in `sql/`, Python stores, bot code, Notion mapping, agent prompts.

## Summary

Live database has 10 tables and 2 views:

- Active data tables: `companies` (328 rows), `signals` (48 rows), `run_logs` (14 rows), `bot_users` (1 row).
- Empty tables: `contacts`, `source_links`, `analysis_notes`, `dossiers`, `bot_presets`, `bot_dialog_state`, `contact_companies`.
- Views: `pipeline_stats`, `recent_leads`.

Important drift from local SQL/docs:

- `pipeline_runs` is already gone in live DB. `sql/014_drop_pipeline_runs.sql` has been applied as migration `013_drop_pipeline_runs`.
- Live DB has `contact_companies` and Contacts V2 fields from `013_contacts_v2`.
- Live `signals` does **not** have `company_name`, `domain`, `linkedin_url`, `source_page_url`, while `scripts/supabase_store.py` still tries to upsert `company_name` and `domain`, and DM/enrichment code expects `source_page_url` in signal rows.
- Live `companies` does **not** have `source_page_url`, while prompts still expect it.
- Local SQL has `github_org_cache`, but live DB does not.
- Security: RLS is disabled on 8 public tables: `contacts`, `source_links`, `analysis_notes`, `dossiers`, `bot_users`, `bot_presets`, `bot_dialog_state`, `contact_companies`.

Legend:

- Type: `Technical`, `User`, `AI/User`, `Audit`, or mixed.
- Removal difficulty: `Low`, `Medium`, `High`.
- Empty counts are from exact SQL counts on 2026-06-16.

## Recommended Cleanup Order

1. Fix schema drift before deleting fields: decide what to do with `source_page_url`, `signals.company_name/domain/linkedin_url`, and `github_org_cache`.
2. Low-risk field removals from `companies`: `funding_amount`, `funding_date`, `team_size`, `website_snippet`, `score_version`, `notion_synced_at`, possibly `linkedin_url`.
3. Remove or keep the whole empty dossier pipeline as one product decision: `source_links`, `analysis_notes`, `dossiers`.
4. Remove or keep the whole empty contacts pipeline as one product decision: `contacts`, `contact_companies`, `companies.dm_enriched_at`, contact scripts, and Notion contacts mapping.
5. Keep `bot_users` if the Telegram bot remains enabled; it has 1 active row.
6. Enable RLS/policies before exposing or continuing to use the empty public tables.

## `companies` — core lead table, 328 rows

Filled data snapshot: `website`, `icp_segment`, `last_verified`, `status`, `domain`, `name`, `sources` are filled on all rows; `sources` is non-empty on 196 rows. `description` has 214 rows, `notion_page_id` 169, `latest_signal` 134, `reject_reason` 108. Nearly empty: `score`, `score_bucket`, `ai_direction`, `funding_stage`, `last_signal_date` have 1 row; `site_note` 6. Empty: `linkedin_url`, `score_version`, `funding_amount`, `funding_date`, `team_size`, `website_snippet`, `dm_enriched_at`, `outreach_status`, `outreach_note`, `notion_synced_at`.

| Field | Use | Type | Removal |
|---|---|---|---|
| `id` | UUID primary key. Internal row identity. | Technical | High |
| `domain` | Unique dedup key; soft link target for `signals`, contacts, dossiers, source links; used across stores and prompts. | Technical/User | High |
| `name` | Company name in Notion, bot output, prompts, and reports. | User | High |
| `website` | Main company URL for enrichment, verification, Notion, and user inspection. | User/Technical | High |
| `linkedin_url` | Company LinkedIn URL for Notion/profile context. Currently empty. | User | Low-Medium |
| `description` | Agent-generated company summary; used by verification/collection/scoring context. | AI/User | Medium |
| `status` | Pipeline state, queues, stats, bot digests, indexes, views. | Technical | High |
| `icp_segment` | Segment grouping, coverage stats, filtering, Notion. | User/Technical | High |
| `score` | Numeric lead score; used by hot leads and `recent_leads`. Currently almost empty. | User | Medium |
| `score_bucket` | Hot/Warm/Cold or mapped score bucket; used by hot queue and `recent_leads`; indexed. | User/Technical | Medium-High |
| `score_version` | Scoring version metadata. Written only when score exists; currently empty. | Technical/Audit | Low |
| `ai_direction` | LLM score explanation; included in `recent_leads`; prompts write it. | AI/User | Medium |
| `funding_stage` | Business signal used in prompts/scoring. Only 1 row. | User | Medium |
| `funding_amount` | Funding amount. Empty and not meaningfully used. | User | Low |
| `funding_date` | Funding recency signal. Empty. | User/Audit | Low-Medium |
| `team_size` | Company size signal. Empty. | User | Low-Medium |
| `latest_signal` | Human-readable latest reason/signal; Notion and bot summaries. | User | High |
| `last_signal_date` | Signal freshness; `recent_leads` filter. Only 1 row. | Technical/User | Medium |
| `last_verified` | Verification freshness and stale-review queue. | Technical | High |
| `notion_page_id` | Link to Notion company page; needed for update/reverse sync. | Technical | High if Notion stays |
| `created_at` | Creation audit. | Technical/Audit | Medium |
| `updated_at` | Update audit; trigger and code maintain it. | Technical | High |
| `reject_reason` | Qualification rejection reason; indexed and populated on 108 rows. | User/Audit | Medium-High |
| `site_note` | Technical site-access note such as protection/no site. 6 rows. | Technical/Audit | Medium |
| `sources` | JSON provenance list of discovery sources. Non-empty on 196 rows. | Audit/Technical | Medium |
| `website_snippet` | Quick-filter website snippet/audit. Empty. | Audit | Low |
| `dm_enriched_at` | Marker that contact enrichment ran; used as queue guard. Empty. | Technical | Medium if contacts stay; Low if contacts go |
| `outreach_status` | Manual CRM status reverse-synced from Notion. Empty. | User | Medium |
| `outreach_note` | Manual CRM note reverse-synced from Notion. Empty. | User | Medium |
| `notion_synced_at` | Sync timestamp written on Notion page creation; not otherwise read. Empty. | Technical/Audit | Low |

## `signals` — discovery signals, 48 rows

`normalized_domain`, `source`, `signal_type`, `evidence_url`, `signal_date`, `confidence`, `raw_data`, `created_at` are filled on all rows. `raw_data` is non-empty on 14 rows. `parser_version` is empty.

| Field | Use | Type | Removal |
|---|---|---|---|
| `id` | UUID primary key. | Technical | High |
| `normalized_domain` | FK to `companies.domain`; links signal to company. | Technical | High |
| `source` | Discovery source name. | Audit/Technical | Medium |
| `signal_type` | Signal category; used for filtering/scoring context. | Audit/Technical | Medium-High |
| `evidence_url` | Unique proof URL and dedup key. | Technical/Audit | High |
| `signal_date` | Freshness/sorting. | Technical/Audit | Medium |
| `confidence` | Parser/agent confidence. | Audit | Low-Medium |
| `parser_version` | Parser version. Empty. | Technical/Audit | Low |
| `raw_data` | Source payload for debugging/reprocessing. | Technical/Audit | Medium |
| `created_at` | Creation audit. | Technical/Audit | Low-Medium |

Schema drift to resolve: code/prompts still reference `company_name`, `domain`, `linkedin_url`, `source_page_url`, but live table does not have them.

## `run_logs` — lightweight run history, 14 rows

`task_name`, `started_at`, `companies_found`, `companies_enriched`, `errors` are filled on all rows; `notes` on 7; `finished_at` empty; `errors` are all empty arrays.

| Field | Use | Type | Removal |
|---|---|---|---|
| `id` | UUID primary key. | Technical | Medium |
| `task_name` | Pipeline task/stage name; bot `/status` and `/last` read it. | Technical | High |
| `started_at` | Run timestamp; bot orders by it. | Technical | High |
| `finished_at` | Completion timestamp. Empty. | Technical/Audit | Low-Medium |
| `companies_found` | Count found by run. | Reporting | Medium |
| `companies_enriched` | Count enriched/written by run. | Reporting | Medium |
| `errors` | JSON error list. Empty arrays currently. | Technical/Audit | Medium |
| `notes` | Free-form run note. 7 rows. | Audit | Low |

## `contacts` — outreach contacts, 0 rows

This table is empty, but actively represented by `scripts/contacts_store.py`, contact enrichment scripts, tests, and Notion contacts mapping.

| Field | Use | Type | Removal |
|---|---|---|---|
| `id` | UUID primary key; used by `contact_companies` and Notion contact sync. | Technical | High if contacts stay |
| `company_domain` | Primary company domain and upsert key component. | Technical | High |
| `full_name` | Contact identity and upsert key component. | User | High |
| `first_name` | Name parsing/email guessing. | User/Technical | Medium |
| `last_name` | Name parsing/email guessing. | User/Technical | Medium |
| `title` | Raw job title. | User | Medium |
| `title_normalized` | Role category for prioritization. | AI/Technical | Low-Medium |
| `dm_priority` | Outreach priority and ordering. | User/Technical | Medium |
| `email` | Contact email; Notion forward. | User | Medium |
| `email_status` | verified/guessed/bounced/unknown. | User/Technical | Medium |
| `email_source` | Provenance for email. | Audit | Low |
| `linkedin_url` | Contact LinkedIn; Notion forward. | User | Medium |
| `twitter_handle` | Contact social handle. | User | Low |
| `github_username` | GitHub profile enrichment. | User/Technical | Medium |
| `source_vector` | Discovery vector such as github/huggingface/team_page. | Audit/Technical | Medium |
| `source_url` | Evidence URL; Notion forward as source. | Audit/User | Medium |
| `confidence` | Contact confidence. | Audit | Low |
| `outreach_status` | Old contact CRM status; not in current Notion mapping. | User | Low-Medium |
| `raw_payload` | Raw source payload. | Technical/Audit | Medium |
| `created_at` | Creation audit. | Technical/Audit | Low |
| `updated_at` | Update audit. | Technical/Audit | Medium |
| `personal_website` | Contact personal website. | User | Low-Medium |
| `hf_username` | HuggingFace username/profile enrichment. | User/Technical | Medium |
| `notion_page_id` | Notion contact page id. | Technical | Medium if Notion contacts stay |
| `contact_type` | Person/Company/Other; Notion forward. | User | Medium |
| `phone` | Phone; Notion forward. | User | Low-Medium |
| `instagram_url` | Instagram; Notion forward. | User | Low |
| `facebook_url` | Facebook; Notion forward. | User | Low |
| `info` | Free-form contact info; Notion forward. | User | Medium |
| `contact_result` | Manual outreach result reverse-synced from Notion. | User | Medium |

If contacts are not needed, remove the table as a contour, not field-by-field.

## `contact_companies` — contact-company many-to-many, 0 rows

| Field | Use | Type | Removal |
|---|---|---|---|
| `contact_id` | FK to `contacts.id`; part of composite PK. | Technical | High if contacts stay |
| `company_domain` | Soft link to `companies.domain`; part of composite PK. | Technical | High if contacts stay |

Remove with `contacts` if contact many-to-many is not needed.

## `source_links` — deep enrichment URLs, 0 rows

Used by `scripts/dossier_store.py` and analysis/dossier prompts.

| Field | Use | Type | Removal |
|---|---|---|---|
| `id` | UUID primary key. | Technical | Medium |
| `company_domain` | Company owner; part of unique key. | Technical | High |
| `kind` | Link kind such as github_org, linkedin, news. Part of unique key. | Technical/Audit | High |
| `url` | Source URL. Part of unique key. | User/Audit | High |
| `source` | Resolver/source that found the URL. | Audit | Low |
| `confidence` | Resolver confidence. | Audit | Low |
| `found_via` | Extra provenance note. | Audit | Low |
| `raw` | Raw resolver payload. | Technical/Audit | Low-Medium |
| `fetched_at` | Fetch timestamp. | Technical/Audit | Low |

If deep dossiers are not needed, delete the whole table with dossier scripts/prompts.

## `analysis_notes` — AI scratchpad for dossier sections, 0 rows

Used by `scripts/dossier_store.py` and analysis prompts.

| Field | Use | Type | Removal |
|---|---|---|---|
| `id` | UUID primary key. | Technical | Medium |
| `company_domain` | Company owner; part of unique key. | Technical | High |
| `section` | Dossier section; part of unique key. | AI/Technical | High |
| `facts` | Structured facts for section. | AI/User | High |
| `sources` | JSON list of supporting sources. | Audit | Medium |
| `confidence` | Section confidence. | Audit | Low |
| `model` | Model used to generate note. Empty. | Technical/Audit | Low |
| `version` | Version; part of unique key. | Technical | Medium |
| `created_at` | Creation audit. | Technical/Audit | Low |

## `dossiers` — final company dossier, 0 rows

Used by `scripts/dossier_store.py`; `notion_sync.py` appends `summary_md` and `audit_md` into the company Notion page.

| Field | Use | Type | Removal |
|---|---|---|---|
| `company_domain` | Primary key and company link. | Technical | High |
| `summary_md` | Final dossier summary. | AI/User | High |
| `sections` | Structured dossier sections. | AI/User | Medium |
| `audit_md` | Audit/explanation section written to Notion body. | Audit/User | Medium |
| `table_fields` | Structured fields for a table/card; no active reader found. | AI/User | Low |
| `version` | Dossier version. | Technical | Low-Medium |
| `generated_at` | Generation timestamp. | Technical/Audit | Low |
| `notion_page_id` | Dossier page id, but current sync writes into company page via `companies.notion_page_id`. | Technical | Low |

Best individual candidates: `table_fields`, `notion_page_id`, maybe `version`.

## `bot_users` — Telegram bot allowlist, 1 row

Used by `bot/access.py`.

| Field | Use | Type | Removal |
|---|---|---|---|
| `chat_id` | Primary key and Telegram identity. | Technical | High if bot stays |
| `username` | Operator username. | User | Low |
| `role` | `admin`/`viewer` authorization. | Technical | Medium |
| `active` | Allowlist enable/disable flag. | Technical | Medium |
| `added_at` | Added timestamp. | Audit | Low |

## `bot_presets` — run presets, 0 rows

Used by `bot/presets.py`; code seeds defaults on first use.

| Field | Use | Type | Removal |
|---|---|---|---|
| `id` | UUID primary key. | Technical | Medium |
| `name` | Unique preset name. | User | High if presets stay |
| `config` | RunConfig JSON. | Technical/User | High if presets stay |
| `owner` | Preset owner. Empty. | Audit | Low |
| `is_default` | Default preset flag. | Technical | Medium |
| `created_at` | Creation audit. | Audit | Low |

## `bot_dialog_state` — Telegram `/run` wizard state, 0 rows

Used by `bot/dialog.py`.

| Field | Use | Type | Removal |
|---|---|---|---|
| `chat_id` | Primary key per Telegram chat. | Technical | High if wizard stays |
| `step` | Current wizard step. | Technical | High if wizard stays |
| `draft` | Draft RunConfig JSON. | Technical | High if wizard stays |
| `updated_at` | State update timestamp. | Technical/Audit | Low |

## Views

### `pipeline_stats`

Definition: groups `companies` by `status`.

| Field | Source | Use |
|---|---|---|
| `status` | `companies.status` | Pipeline count grouping. |
| `count` | `count(*)` | Count per status. |

### `recent_leads`

Definition: selects Hot/Warm companies from last 30 days or with no `last_signal_date`, ordered by score.

| Field | Source | Use |
|---|---|---|
| `domain` | `companies.domain` | Lead identity. |
| `name` | `companies.name` | Display. |
| `score` | `companies.score` | Ranking. |
| `score_bucket` | `companies.score_bucket` | Hot/Warm filter. |
| `icp_segment` | `companies.icp_segment` | Segment display/filter. |
| `latest_signal` | `companies.latest_signal` | Display reason. |
| `last_signal_date` | `companies.last_signal_date` | Recency filter/display. |
| `ai_direction` | `companies.ai_direction` | Score explanation. |
| `notion_page_id` | `companies.notion_page_id` | Link/update target. |

Supabase security advisor flags both views as `SECURITY DEFINER` views.

## Local-only / Missing Live Tables

### `github_org_cache`

Exists in `sql/002_github_org_cache.sql` and `scripts/org_cache.py`, but is not present in live DB.

| Field | Intended use | Type | Removal |
|---|---|---|---|
| `org_login` | GitHub org login primary key. | Technical | Medium |
| `data` | Raw GitHub org API payload. | Technical/Audit | Medium |
| `cached_at` | TTL timestamp. | Technical | Low |

Decision: either apply/create it if GitHub org caching is needed, or delete `scripts/org_cache.py` integration/tests if not.

## Practical Drop Candidates

### Low-risk field candidates

- `companies.funding_amount`
- `companies.funding_date`
- `companies.team_size`
- `companies.website_snippet`
- `companies.score_version`
- `companies.notion_synced_at`
- `dossiers.table_fields`
- `dossiers.notion_page_id`
- `analysis_notes.model`
- `run_logs.finished_at` if no completion tracking is planned
- `run_logs.notes` if free-form notes are not useful
- `bot_presets.owner`

### Product-decision candidates

- Full contact contour: `contacts`, `contact_companies`, `companies.dm_enriched_at`, Notion contacts mapping, contact enrichment scripts.
- Full dossier contour: `source_links`, `analysis_notes`, `dossiers`, dossier prompts/scripts.
- Scoring/recent-leads contour: `companies.score`, `score_bucket`, `ai_direction`, `last_signal_date`, plus `recent_leads`.
- CRM reverse-sync contour: `companies.outreach_status`, `companies.outreach_note`, `contacts.contact_result`.

### Do not delete without redesign

- `companies.domain`, `name`, `website`, `status`, `icp_segment`, `last_verified`, `notion_page_id`, `updated_at`.
- `signals.normalized_domain`, `source`, `signal_type`, `evidence_url`, `signal_date`.
- `run_logs.task_name`, `started_at`.
- Any primary key, unique key, or composite key fields.

## Security Follow-up

Supabase advisor recommends enabling RLS on:

```sql
ALTER TABLE public.contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.source_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.analysis_notes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dossiers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bot_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bot_presets ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bot_dialog_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.contact_companies ENABLE ROW LEVEL SECURITY;
```

Do not apply this blindly: enabling RLS without policies can block legitimate bot/service access. Decide access policies first.
