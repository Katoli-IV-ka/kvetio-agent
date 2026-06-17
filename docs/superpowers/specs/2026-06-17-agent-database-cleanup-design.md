# Agent Database Cleanup — Design Spec
**Date:** 2026-06-17  
**Status:** Approved

## Problem

The current agent database mixes agent runtime data, old scoring logic, Telegram bot UI storage,
Notion/CRM fields, and several partially migrated data models. This makes the agent harder to
reason about: prompts read fields that are missing or duplicated elsewhere, status values mix old
and new workflow states, and some tables exist only as artifacts of older architecture.

The cleanup must simplify the system without breaking the agent. The database should store data
that the agent actually uses for discovery, relevance, analysis, contacts, and Notion projection.
User-only CRM state and obsolete bot/scoring artifacts should be removed.

## Goals

- Remove the full score system from code, prompts, and database.
- Use a small status model as the primary marker for whether a company fits the agent.
- Make `signals` the source of truth for discovery evidence, provenance, and latest signal context.
- Remove Telegram bot presets and keep `/run` as the single configurable launch flow.
- Keep one `contacts` table, linked correctly to `companies`.
- Support Notion contact sync while preserving the contact-company relation in Notion.
- Remove user-only CRM fields that are not part of the current agent system.
- Leave no unused tables, scripts, prompts, or docs that describe deleted behavior.

## Non-Goals

- Do not build a CRM or outreach pipeline in this cleanup.
- Do not store explanations for why a company is relevant or not relevant.
- Do not keep backward compatibility for Telegram `/presets` or `/quickrun`.
- Do not introduce a new score-like replacement.
- Do not add `source_page_url` as a new field.
- Do not introduce `contact_role`; contact role/meaning is stored in `contacts.title`.

---

## Companies

`companies` remains the core company table. It stores company identity, current workflow status,
basic profile data, Notion page identity, and timestamps.

### Removed Fields

Remove these fields from `companies`:

| Field | Reason |
|---|---|
| `score` | Old scoring system is removed. |
| `score_bucket` | Old scoring system is removed. |
| `score_version` | Old scoring system is removed. |
| `ai_direction` | Score explanation; no longer needed. |
| `sources` | Discovery provenance moves to `signals`. |
| `latest_signal` | Latest signal is derived from `signals`. |
| `reject_reason` | No stored explanation for `not_relevant` decisions. |
| `outreach_status` | User/CRM state, not agent data. |
| `outreach_note` | User/CRM note, not agent data. |

### Status Model

`companies.status` is the primary operational marker.

Canonical statuses:

| Status | Meaning |
|---|---|
| `discovered` | Candidate company found but not yet classified. |
| `relevant` | Primary analysis says the company fits enough to continue. |
| `not_relevant` | Primary analysis says the company does not fit. |
| `manual_review` | Agent could not confidently classify the company. |
| `sources_gathered` | Supporting sources were gathered for deeper analysis. |
| `analyzed` | Structured analysis notes were produced. |
| `dossier_ready` | Final dossier is ready or synced. |

Legacy status migration:

| Current Value | Target Value |
|---|---|
| `qualified` | `relevant` |
| `pending_enrich` | `relevant` |
| `enriched` | `relevant` |
| `triaged_out` | `not_relevant` |

The system intentionally does not store an explanation for why a company is relevant or not
relevant. This stage is a lightweight primary filter before deeper analysis.

---

## Signals

`signals` is the source of truth for discovery evidence, source provenance, and latest signal
context.

The cleanup does not add `source_page_url`. The existing signal fields carry the required meaning:

| Field | Meaning |
|---|---|
| `source` | Source system or collector name, such as `huggingface`, `github`, `websearch`. |
| `signal_type` | Role and kind of signal. |
| `evidence_url` | Canonical URL for the source evidence. |
| `signal_date` | Date of the signal or discovery. |
| `confidence` | Confidence in the signal. |
| `raw_data` | Optional raw source payload if the field exists in the active schema. |
| `parser_version` | Optional parser version if the field exists in the active schema. |

### `signal_type` Convention

`signal_type` must encode the role of the signal:

| Prefix | Meaning |
|---|---|
| `primary_*` | Signal that first brought the company into the database. |
| `verification_*` | Supporting signal found during initial validation. |
| `monitor_*` | New signal for an already known company. |

Examples:

```text
primary_hf_org
primary_github_org
primary_yc_company
primary_job_posting
primary_websearch
verification_hf_org
verification_foundation_model
verification_job_posting
verification_news
verification_website
monitor_funding
monitor_model_release
monitor_job_posting
monitor_news
```

Notion and Telegram should derive "latest signal" displays from `signals`, not from
`companies.latest_signal`.

---

## Telegram Bot

Telegram bot storage should not live in the agent database.

Remove:

| Object | Reason |
|---|---|
| `bot_presets` | UI convenience table; not agent data. |
| `/presets` | Depends on `bot_presets`. |
| `/quickrun` | Preset shortcut is removed with no compatibility guarantee. |
| `bot/presets.py` | Preset store implementation. |
| `bot/preset_args.py` | Parser for `/presets save`. |

Keep:

| Object | Reason |
|---|---|
| `/run` | Main configurable launch entrypoint. |
| `bot/dialog.py` callback flow | Stateless wizard; stores draft config in Telegram `callback_data`. |
| `RunConfig` | Launch config object used by `/run` and `routine.fire`. |

Target launch model:

```text
/run is the only configurable launch entrypoint.
The /run wizard is stateless.
Wizard state is encoded in Telegram callback_data.
No Telegram launch presets are stored in Supabase.
```

---

## Contacts

There should be one contacts table. The agent needs all ways to contact a specific company, not a
global people graph.

### Target Relation

Canonical relation:

```text
contacts.company_id -> companies.id
```

`companies.id` is the technical primary key and should be used for database relations.

`companies.domain` remains a unique business identifier and a useful agent input, but it is not the
canonical foreign key for contacts.

### Transitional `company_domain`

`contacts.company_domain` remains for now as a legacy compatibility field.

Rules:

- Do not use `contacts.company_domain` as the canonical relation.
- Do not build Notion relation through `contacts.company_domain`.
- Keep it as a denormalized compatibility value while old scripts and prompts still pass domains.
- New contact writes should resolve the company by domain, write `contacts.company_id`, and also
  fill `contacts.company_domain` from `companies.domain` during the transition.

After all contact code, prompts, and sync logic use `company_id`, `company_domain` can be reviewed
again for deletion.

### Removed Table

Remove `contact_companies`.

Reason: the target model is one contact record in the context of one company. If the same person is
connected to another company, that does not matter for the current agent workflow.

### Contact Meaning

One row in `contacts` is one way to reach or understand a contact path for a company. It can be:

- a person at the company;
- a company-level contact channel;
- a related person who can help reach the company;
- an unclear contact that still may be useful.

Target `contact_type` values:

| Value | Meaning |
|---|---|
| `Person` | Employee or representative of the company. |
| `Company` | Company-level channel such as `info@`, phone, website contact form, company social page. |
| `Related Person` | Advisor, investor, partner, board member, ex-founder, or similar related person. |
| `Other` | Unknown or unclear contact type. |

No `contact_role` field is added. `contacts.title` stores the role or meaning of the contact.

Examples for `title`:

```text
CTO
Founder
Head of ML
General company email
Company LinkedIn page
Contact form
Advisor
Investor
Partner
Press contact
Support email
```

### Removed Contact Fields

Remove these fields from `contacts`:

| Field | Reason |
|---|---|
| `outreach_status` | CRM/outreach state is out of scope. |
| `outreach_note` | Manual CRM note is out of scope. |
| `contact_result` | Manual outreach result is out of scope. |

Keep `contacts.notion_page_id` because it is required for Notion sync identity.

---

## Notion Sync

Notion remains a user-facing editing surface for contacts and a projection surface for companies.

### Company Sync

Companies are created and updated from Supabase to Notion. `companies.notion_page_id` links each
database row to its Notion page.

CRM-style company reverse fields are removed:

```text
companies.outreach_status
companies.outreach_note
```

### Contact Forward Sync

Forward sync from Supabase to Notion:

```text
contacts.company_id
  -> companies.id
  -> companies.notion_page_id
  -> Notion Contacts relation "Компания"
```

For each Supabase contact:

1. Read `contacts.company_id`.
2. Find the linked company row by `companies.id`.
3. Read `companies.notion_page_id`.
4. Write that page id into the Notion relation property on the contact page.
5. Create or update the Notion contact page and store `contacts.notion_page_id`.

### Contact Reverse Sync

Reverse sync from Notion to Supabase must support creating and editing contacts from Notion.

For an existing Notion contact page:

1. Match by `contacts.notion_page_id`.
2. Read editable contact properties from Notion.
3. Read the Notion relation property `Компания`.
4. Resolve the selected company page id to `companies.id`.
5. Update `contacts.company_id` and allowed contact fields.

For a new Notion contact page:

1. Require exactly one selected company in the Notion relation.
2. Resolve the selected company page id to `companies.id`.
3. Insert a new `contacts` row.
4. Store the Notion page id in `contacts.notion_page_id`.
5. Fill `contacts.company_domain` from the linked company during the transition.

If the Notion relation is missing or contains multiple companies, the sync should skip the row and
log a clear error. The current data model is one contact in the context of one company.

### Editable Contact Fields

Contacts may be edited from Notion for these fields:

```text
full_name
contact_type
title
email
phone
linkedin_url
instagram_url
facebook_url
source_url
info
company relation
```

Notion sync should not reintroduce `contact_result`, `outreach_status`, or `outreach_note`.

### Conflict Policy

Initial conflict policy:

- Agent-created contacts are inserted into Supabase first, then projected to Notion.
- User-created Notion contacts are imported only when they have exactly one company relation.
- Once a contact has `notion_page_id`, Notion edits to the allowed contact fields are accepted by
  reverse sync.
- Supabase remains responsible for technical identity fields: `id`, `company_id`, `notion_page_id`,
  timestamps, source metadata, and raw payloads.

If richer conflict resolution becomes necessary, it should be designed separately with sync
metadata. This cleanup does not add a full conflict-resolution system.

---

## Source Links, Analysis Notes, And Dossiers

This cleanup does not migrate every `company_domain` usage in the deep analysis tables.

The following tables may continue to use `company_domain` until their own cleanup pass:

```text
source_links
analysis_notes
dossiers
```

Reason: this cleanup focuses on agent structure, `companies`, `signals`, bot presets, contacts, and
Notion contact sync. Deep analysis tables are currently empty in the live database and can be
normalized later if they become active.

---

## Migration Strategy

Implementation should happen in phases to avoid breaking runtime code.

### Phase 1 — Documentation And Prompt Alignment

- Update ecosystem docs with the new status model.
- Document `signals.signal_type` prefixes.
- Update prompts to stop reading `source_page_url`, `companies.sources`, `latest_signal`,
  `reject_reason`, and score fields.
- Update prompts to use `signals` for discovery evidence and latest signal context.

### Phase 2 — Code Compatibility

- Add `contacts.company_id`.
- Resolve contact writes from domain to company id.
- Keep writing `contacts.company_domain` as a denormalized compatibility value.
- Update contact reads to use `company_id` where possible.
- Keep domain-based CLI input for agent ergonomics.

### Phase 3 — Notion Sync Rewrite

- Build contact relation from `contacts.company_id`, not `contact_companies`.
- Import new contacts from Notion when exactly one company relation is selected.
- Update existing contacts from Notion through `contacts.notion_page_id`.
- Remove Notion mappings for CRM/reverse-only fields.

### Phase 4 — Bot Cleanup

- Remove `bot_presets`.
- Remove `/presets`.
- Remove `/quickrun`.
- Keep `/run` callback wizard.
- Update bot help/start/settings text.

### Phase 5 — Schema Cleanup

Drop removed tables and fields after the code no longer references them:

```text
bot_presets
contact_companies
companies.score
companies.score_bucket
companies.score_version
companies.ai_direction
companies.sources
companies.latest_signal
companies.reject_reason
companies.outreach_status
companies.outreach_note
contacts.outreach_status
contacts.outreach_note
contacts.contact_result
```

### Phase 6 — Tests And Verification

- Update migration contract tests.
- Update Notion sync tests for contact relation via `company_id`.
- Update contacts store tests for `company_id` resolution.
- Update bot tests to remove preset expectations.
- Update prompt tests to remove score/source_page_url/old field expectations.
- Run live Supabase verification queries after migration.

---

## Risks

| Risk | Mitigation |
|---|---|
| Dropping fields before code is updated breaks prompts/scripts. | Update code and prompts first; drop schema last. |
| Notion-created contacts without company relation cannot be imported. | Require exactly one company relation and log skipped rows. |
| Removing `latest_signal` affects Telegram/Notion summaries. | Derive latest signal display from `signals`. |
| Removing score affects old hot-lead workflows. | Replace score selectors with status and signal-based views. |
| `company_domain` remains and can confuse future code. | Mark it as legacy compatibility and do not use it for canonical relation. |
| Bidirectional Notion sync can create conflicts. | Keep simple field rules now; design richer sync metadata only if needed. |

## Acceptance Criteria

- No active code path reads or writes removed score fields.
- No active code path reads `companies.sources`, `companies.latest_signal`, or `reject_reason`.
- Telegram bot starts without `bot_presets` and `/run` still launches the routine.
- Contacts have `company_id` linked to `companies.id`.
- Notion Contacts relation is built from `company_id`.
- New Notion contacts with exactly one company relation can be imported into Supabase.
- `contact_companies` is no longer referenced by active code.
- `signals.signal_type` convention is documented and used by prompts.
- Removed CRM fields do not appear in Notion mapping.
