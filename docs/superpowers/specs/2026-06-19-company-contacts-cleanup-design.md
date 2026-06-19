> SUPERSEDED — see 2026-06-19-database-agent-cleanup-FINAL.md

# Company And Contacts Cleanup — Design Spec
**Date:** 2026-06-19  
**Status:** Superseded

Superseded by
`docs/superpowers/specs/2026-06-19-database-agent-cleanup-consolidated-design.md`.
Use the consolidated design as the active contract for companies, contacts,
signals, source links, scripts, and agent prompts.

## Goal

Simplify `companies` so it stores only current company identity, workflow state,
Notion identity, and stable timestamps. Move evidence, signal provenance,
funding facts, verification notes, and outreach/contact channels out of
`companies` into the tables that already model those concepts.

Also broaden `contacts` from "people at a company" to "all ways to reach or
observe a company", covering both people and organization-level channels.

## Companies

`companies` remains the canonical current-state company card.

### Keep

| Field | Reason |
|---|---|
| `id` | Technical primary key and FK target. |
| `domain` | Unique business key and company dedup key. |
| `name` | Human-readable company name. |
| `website` | Primary company website. |
| `linkedin_url` | Primary company LinkedIn page. Kept as a high-value company profile field. |
| `notion_page_id` | Binding to the company page in Notion. |
| `notion_synced_at` | Last successful Notion sync timestamp; needed for current and future two-way sync. |
| `status` | Current workflow state. |
| `icp_segment` | Current ICP routing and filtering field. |
| `description` | Short company description for operator context and analysis prompts. |
| `created_at` | Company creation timestamp. |
| `updated_at` | Current-state update timestamp and ordering field. |

### Remove

| Field | Replacement |
|---|---|
| `last_signal_date` | Derive from `signals` by `company_id`. |
| `created_from_signal_id` | Do not store signal pointers on `companies`; use `signals.company_id`. |
| `last_signal_id` | Derive latest signal from `signals` by date/created time. |
| `last_verified` | Derive verification freshness from `signals` or future monitor runs. |
| `site_note` | Store evidence in `signals`; store interpretation in `analysis_notes`. |
| `funding_stage` | Store raw funding evidence in `signals`; interpretation in `analysis_notes.financials`. |
| `funding_date` | Store as `signals.signal_date` for funding signals. |
| `funding_amount` | Store in `signals.payload` or `analysis_notes.financials`. |
| `website_snippet` | Store website evidence in `signals.summary`, `signals.payload`, or `raw_data`. |
| `dm_enriched_at` | Derive from existing people/channel contacts or contact-related signals. |

## Signals

`signals` remains the place for evidence and history. A signal must reference
the company through `signals.company_id`. `companies` must not store shortcut
FKs back to individual signals.

When the system needs the latest signal, first signal, verification freshness,
or funding evidence for a company, it should query `signals` by `company_id`
with the appropriate `signal_type`, `signal_date`, and `created_at` ordering.

## Analysis Notes

Funding and similar business interpretation belongs in `analysis_notes`, not
in `companies`.

Examples:

- raw funding article found -> `signals`
- extracted round amount/date/source -> `signals.payload`
- agent conclusion about funding stage or company maturity -> `analysis_notes`
- final user-facing summary -> `dossiers`

## Contacts

`contacts` should represent all company touchpoints, not only individual people.

### Contact Types

Only two contact types are needed:

| Type | Meaning |
|---|---|
| `person` | A named person associated with the company. |
| `organization` | A company-level channel, inbox, profile, or page. |

### Target Shape

Replace `first_name` and `last_name` with one general `name` field.

Target fields:

| Field | Meaning |
|---|---|
| `id` | Contact/touchpoint primary key. |
| `company_id` | FK to `companies.id`. |
| `contact_type` | `person` or `organization`. |
| `name` | Person name or organization-channel label. |
| `info` | Role, context, or short explanation. |
| `email` | Email channel, if present. |
| `phone` | Phone channel, if present. |
| `linkedin_url` | Person LinkedIn profile or organization LinkedIn page, depending on type. |
| `x_url` | X/Twitter profile. |
| `facebook_url` | Facebook profile/page. |
| `instagram_url` | Instagram profile/page. |
| `other_channels` | Secondary channels with typed JSON entries. |
| `discovered_from_signal_id` | Optional provenance pointer to the signal that discovered this touchpoint. |
| `notion_page_id` | Binding to a Notion contact/touchpoint page. |
| `notion_synced_at` | Last successful Notion sync timestamp; needed for current and future two-way sync. |
| `created_at` | Creation timestamp. |
| `updated_at` | Update timestamp. |

### Dedup

The base dedup key should be:

```text
company_id + contact_type + lower(name)
```

Channel-level dedup should also prevent duplicate exact primary channels where
possible, especially email and canonical URLs.

## Notion Projection

The Notion contacts database should treat contacts as touchpoints:

- title: `contacts.name`
- type/select: `contacts.contact_type`
- company relation: computed through `contacts.company_id -> companies.notion_page_id`
- visible channels: email, phone, LinkedIn, X, Facebook, Instagram, other channels

Both `companies` and `contacts` keep `notion_page_id` and `notion_synced_at`.
`notion_page_id` stores the page binding. `notion_synced_at` stores the last
successful sync time and supports incremental sync, troubleshooting, and future
two-way conflict handling.

## Open Implementation Notes

- Existing person-source scripts should stop splitting names into first/last and
  write `name` with `contact_type = 'person'`.
- Organization-level sources should write `contact_type = 'organization'`.
- Existing `contacts.company_id` remains the canonical company relation.
- `companies.domain` remains the dedup key for companies.
