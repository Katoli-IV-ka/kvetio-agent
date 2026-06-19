> SUPERSEDED — see 2026-06-19-database-agent-cleanup-FINAL.md

# Database And Agent Cleanup Consolidation - Design Spec
**Date:** 2026-06-19  
**Status:** Draft for review  
**Supersedes:**
- `docs/superpowers/specs/2026-06-19-company-contacts-cleanup-design.md`
- `docs/superpowers/specs/2026-06-19-signals-source-links-consolidation-design.md`

## Goal

Unify the company cleanup, contacts cleanup, and source-links consolidation into
one database contract that scripts and agents can use safely.

The new contract has four primary domain tables:

1. `companies` stores only current company identity, workflow state, Notion
   identity, and stable timestamps.
2. `contacts` stores all company touchpoints, including named people and
   organization-level channels.
3. `research_entries` stores raw company observations found during research,
   discovery, verification, monitoring, enrichment, or similar collection work.
4. `analysis_entries` stores interpreted conclusions derived from
   `research_entries`.

This design also updates the agent/script contract so crypto and research
agents work with the new database shape instead of writing legacy fields.
After implementation, project documentation must be updated so operators and
future agents read the new database contract instead of the removed schema.

## Problems Being Solved

The current schema and prompts mix current state with evidence history:

- `companies` stores derived evidence shortcuts such as latest signal,
  verification date, funding fields, website snippets, and DM enrichment status.
- `source_links` overlaps with the raw research layer, so analysis has to read
  two evidence tables.
- `contacts` models only people through `first_name` and `last_name`, while
  agents also need to store organization-level channels such as company inboxes,
  social pages, GitHub orgs, and public profiles.
- Several prompts still tell agents to write old fields such as `source_links`,
  `funding_stage` on `companies`, and split contact names.

The cleanup should make the database easier for agents to reason about: current
company card in `companies`, touchpoints in `contacts`, raw research records in
`research_entries`, interpretation in `analysis_entries`, and final output in
`dossiers`.

## Naming Decision

Use these primary table names:

| Table | Role |
|---|---|
| `companies` | Canonical current company profile. |
| `contacts` | People and organization-level contact points. |
| `research_entries` | Raw found information about a company before interpretation. |
| `analysis_entries` | Interpreted conclusions and structured notes based on research entries. |

Do not use `logs` for domain knowledge tables. `logs` is reserved for technical
runtime history such as agent execution, errors, and diagnostics.

## Non-Goals

- Do not redesign the full scoring model.
- Do not define the final research entry type vocabulary beyond the storage
  contract.
- Do not preserve backward-compatible reads from `source_links`.
- Do not keep `source_links` as a compatibility view.
- Do not backfill `source_links`, because it is expected to be empty before
  removal.
- Do not build the migration in this design document; implementation planning
  will happen separately after review.

## Target Data Flow

```text
companies
  -> research_entries
      -> analysis provenance links
          -> analysis_entries
              -> dossiers

companies
  -> contacts
```

Meaning:

- agents discover or verify facts by writing `research_entries`;
- analysis creates interpretation in `analysis_entries`;
- a support provenance table records which research entries support,
  contradict, or provide context for each analysis entry;
- `dossiers` stores the final generated company dossier;
- `contacts` stores people and organization-level touchpoints for outreach or
  observation.

## Companies

`companies` remains the canonical current-state company card.

### Keep

| Field | Reason |
|---|---|
| `id` | Technical primary key and FK target. |
| `domain` | Unique business key and company dedup key. |
| `name` | Human-readable company name. |
| `website` | Primary company website. |
| `linkedin_url` | Primary company LinkedIn page. |
| `notion_page_id` | Binding to the company page in Notion. |
| `notion_synced_at` | Last successful Notion sync timestamp. |
| `status` | Current workflow state. |
| `icp_segment` | Current ICP routing and filtering field. |
| `description` | Short company description for operator context and prompts. |
| `created_at` | Company creation timestamp. |
| `updated_at` | Current-state update timestamp and ordering field. |

### Remove

| Field | Replacement |
|---|---|
| `last_signal_date` | Derive from `research_entries` by `company_id`. |
| `created_from_signal_id` | Do not store raw-entry pointers on `companies`; use `research_entries.company_id`. |
| `last_signal_id` | Derive latest raw entry from `research_entries` ordering. |
| `last_verified` | Derive verification freshness from verification or monitor research entries. |
| `site_note` | Store raw evidence in `research_entries`; store interpretation in `analysis_entries`. |
| `funding_stage` | Raw funding evidence in `research_entries`; interpreted maturity in `analysis_entries`. |
| `funding_date` | Entry event date for funding research entries. |
| `funding_amount` | `research_entries.payload` for extracted raw amount; `analysis_entries` for interpretation. |
| `team_size` | Store raw team-size evidence in `research_entries.payload`; interpreted value in `analysis_entries`. |
| `website_snippet` | `research_entries.summary`, `research_entries.payload`, or raw snapshot data. |
| `dm_enriched_at` | Derive from existing contacts or contact-related research entries. |

Agents must not write removed fields after the cleanup. If a prompt needs a
summary of funding, verification, latest signal, or team size, it should query
`research_entries` and `analysis_entries`.

## Research Entries

`research_entries` is the raw research and observation table. Any URL, event,
source, page, news item, profile, repository, token page, or other finding that
may be used by analysis must be stored as a research entry.

Former `source_links` concepts map to `research_entries` as follows:

| Former `source_links` field | Target location |
|---|---|
| `company_id` | `research_entries.company_id` |
| `kind` | `research_entries.entry_type` or `research_entries.payload.kind` |
| `url` | `research_entries.url` |
| `source` | `research_entries.source` |
| `confidence` | `research_entries.confidence` |
| `found_via` | `research_entries.agent` or `research_entries.payload.found_via` |
| `source_signal_id` | Removed; the row itself is the research entry |
| `raw` | raw snapshot data on `research_entries` |
| `fetched_at` | `research_entries.created_at` or `research_entries.payload.fetched_at` |

Entry type should describe the evidence kind, not the pipeline stage. The
pipeline stage belongs in `agent`, `source`, or optionally a separate role
field.

If role separation is needed during implementation, prefer:

```sql
entry_role TEXT NOT NULL DEFAULT 'evidence'
CHECK (entry_role IN ('primary', 'verification', 'monitor', 'analysis_input', 'evidence'))
```

If implementation scope needs to stay smaller, defer the column and temporarily
store the role in `research_entries.payload.role`.

### Research Entry Deduplication

For URL-backed research entries, dedupe by:

```text
company_id + entry_type + url
```

For research entries without a URL, use a stable source-specific fallback such
as:

```text
company_id + entry_type + source + external_id
```

Resolver and adapter code should prefer durable URLs whenever available.

## Analysis Entries

Business interpretation belongs in `analysis_entries`, not in `companies`.

Examples:

- raw funding article found -> `research_entries`;
- extracted round amount/date/source -> `research_entries.payload`;
- agent conclusion about funding stage or company maturity ->
  `analysis_entries`;
- final user-facing summary -> `dossiers`;
- latest verification state -> derived from verification research entries and
  optionally summarized in `analysis_entries`.

Analysis provenance remains the link between interpretation and raw research.
Analysis should link each entry to the research entry IDs it used with the
roles:

- `supports`;
- `contradicts`;
- `context`.

## Contacts

`contacts` represents all company touchpoints, not only individual people.

### Contact Types

| Type | Meaning |
|---|---|
| `person` | A named person associated with the company. |
| `organization` | A company-level channel, inbox, profile, or page. |

### Target Shape

Replace `first_name` and `last_name` with one general `name` field.

| Field | Meaning |
|---|---|
| `id` | Contact/touchpoint primary key. |
| `company_id` | FK to `companies.id`. |
| `contact_type` | `person` or `organization`. |
| `name` | Person name or organization-channel label. |
| `info` | Role, context, or short explanation. |
| `email` | Email channel, if present. |
| `phone` | Phone channel, if present. |
| `linkedin_url` | Person LinkedIn profile or organization LinkedIn page. |
| `x_url` | X/Twitter profile. |
| `facebook_url` | Facebook profile/page. |
| `instagram_url` | Instagram profile/page. |
| `other_channels` | Secondary channels with typed JSON entries. |
| `discovered_from_research_entry_id` | Optional provenance pointer to the research entry that discovered this touchpoint. |
| `notion_page_id` | Binding to a Notion contact/touchpoint page. |
| `notion_synced_at` | Last successful Notion sync timestamp. |
| `created_at` | Creation timestamp. |
| `updated_at` | Update timestamp. |

### Deduplication

The base dedup key should be:

```text
company_id + contact_type + lower(name)
```

Channel-level dedup should also prevent duplicate exact primary channels where
possible, especially email and canonical URLs.

### Contact Payload Contract

New writes should use this shape:

```json
{
  "company_id": "00000000-0000-0000-0000-000000000001",
  "contact_type": "person",
  "name": "Alice Chen",
  "info": "Head of ML; likely owns dataset/vendor decisions.",
  "email": "alice@acme.ai",
  "phone": "+1-555-0100",
  "linkedin_url": "https://www.linkedin.com/in/alicechen",
  "x_url": "https://x.com/alicechen",
  "facebook_url": null,
  "instagram_url": null,
  "other_channels": [
    {"type": "github", "url": "https://github.com/alicechen"},
    {"type": "personal_website", "url": "https://alicechen.dev"}
  ],
  "discovered_from_research_entry_id": "11111111-1111-1111-1111-111111111111"
}
```

Organization-level examples:

```json
{
  "company_id": "00000000-0000-0000-0000-000000000001",
  "contact_type": "organization",
  "name": "Company GitHub organization",
  "info": "Engineering activity and public repositories.",
  "other_channels": [
    {"type": "github", "url": "https://github.com/acme-ai"}
  ],
  "discovered_from_research_entry_id": "11111111-1111-1111-1111-111111111111"
}
```

Do not put `email`, `phone`, `linkedin_url`, `x_url`, `facebook_url`, or
`instagram_url` into `other_channels`. These are primary channels.

## Script Contract

### `scripts/supabase_store.py`

- Stop writing removed `companies` fields.
- `upsert_company()` writes only current company card fields.
- Replace `upsert_signal()` with the canonical `research_entries` write helper.
- Add or keep read helpers for derived state:
  - latest research entry for company;
  - verification freshness from research entries;
  - analysis input research entries for a company;
  - funding evidence research entries.

### `scripts/dossier_store.py`

- Remove `upsert_source_link()`.
- Remove `get_source_links()`.
- Remove source-link CLI commands.
- Replace analysis-note helpers with canonical `analysis_entries` helpers.
- Keep `upsert_dossier()` and `get_dossier()`.
- If analysis needs convenience reads, add a helper that returns research entry
  rows for a `company_id` instead of source-link rows.

### `scripts/enrichment.py`

- Stop importing and calling `upsert_source_link()`.
- Resolvers should return research-entry-shaped payloads.
- Enrichment writes through the canonical `research_entries` write helper.
- Resolver-specific fields such as original `kind`, `found_via`, external IDs,
  and fetched timestamps should live in `research_entries.payload`.

### `scripts/contacts_store.py`

- Accept `name` and `contact_type`.
- Keep short-term compatibility with old inbound payloads only if needed for a
  staged migration, by converting `first_name` + `last_name` to `name`.
- Write `on_conflict="company_id,contact_type,name"` after the schema changes.
- `mark_enriched()` should be removed or replaced by a contact-related research
  entry if the pipeline needs to record that enrichment ran.
- `list_contacts()` should order by `name`.

### DM And Contact Source Scripts

Scripts such as GitHub, HuggingFace contacts, Apollo, Wellfound, team page, and
contact page extractors should output the new contact payload:

- `contact_type = 'person'` for named people;
- `contact_type = 'organization'` for shared inboxes, company pages, org
  profiles, or generic contact forms;
- `name` instead of `first_name` and `last_name`;
- provenance through the related `research_entries` row when known.

### `scripts/notion_sync.py`

- Contact title should use `contacts.name`.
- Contact type should be projected to a Notion select.
- Company relation still comes from `contacts.company_id ->
  companies.notion_page_id`.
- Reverse contact sync should write `name` and `contact_type`, not split names.
- Dossier sync must use `dossiers.company_id`, not any legacy company-domain
  field.

## Agent Prompt Contract

All pipeline prompts must treat the new database shape as canonical.

### Discovery

- Create or update `companies` only with current card fields.
- Write primary evidence as `research_entries`.
- Do not write `created_from_signal_id`, `last_signal_id`,
  `last_signal_date`, or other shortcut fields on `companies`.

### Relevance And Verification

- Update only `companies.status` for workflow state.
- Write verification evidence as `research_entries`.
- Do not write `last_verified` on `companies`; derive it from research entries.

### Source Expansion And Enrichment

- Write supporting URLs as `research_entries`, not `source_links`.
- Keep resolver-specific metadata in `research_entries.payload`.
- Set `companies.status = 'sources_gathered'` only after required evidence has
  been stored as research entries.

### Analysis

- Read `research_entries` as the evidence input.
- Write interpretations to `analysis_entries`.
- Link analysis entries to source research entries through the provenance link
  table.
- Do not read `source_links`.
- Do not read removed company fields such as `funding_stage`, `team_size`, or
  `website_snippet`; use `research_entries` and `analysis_entries` instead.

### Conclusions

- Build final dossier from `companies`, `contacts`, `research_entries`,
  `analysis_entries`, and analysis provenance.
- Write final output to `dossiers`.
- Notion sync reads the current `companies`, `contacts`, and `dossiers` shapes.

### DM Enrichment

- Write touchpoints to `contacts`.
- Use `person` for named people and `organization` for company-level channels.
- Do not set `companies.dm_enriched_at`.
- If the run itself needs auditability, write a contact/enrichment research
  entry.

### Crypto Agents

Crypto-focused agents should follow the same contract:

- crypto source URLs, token pages, exchange listings, GitHub repos, docs,
  funding announcements, or ecosystem references are `research_entries`;
- company/project-level channels such as Discord, Telegram, X, docs, GitHub org,
  and contact forms are `contacts` with `contact_type = 'organization'` unless a
  named person is discovered;
- interpreted maturity, traction, funding, or collaboration fit belongs in
  `analysis_entries`;
- final narrative belongs in `dossiers`;
- removed `companies` fields and `source_links` must not be used.

## Project Documentation Updates

Implementation is not complete until the project documentation reflects the new
database and agent contract.

The project must have table-contract documentation that explains every active
table in a way agents and future developers can reuse before adding new schema.
For each table, document:

- table purpose and ownership;
- whether it is a core domain table, knowledge entry table, support/provenance
  table, output table, or technical/runtime table;
- what data belongs there;
- what data must not be stored there;
- field-by-field meaning;
- write logic and allowed writers;
- read logic and common query patterns;
- deduplication rules;
- lifecycle and cleanup/archive behavior;
- examples of correct and incorrect writes.

When adding new functionality, agents and developers must first check this
table-contract documentation and prefer reusing or extending existing tables.
Creating a new table or broad new column requires an explicit design decision
that explains why `companies`, `contacts`, `research_entries`, or
`analysis_entries` cannot represent the data cleanly. The goal is to prevent
one-off tables, duplicate fields, and low-quality schema clutter.

Update at minimum:

- `docs/AGENT-ECOSYSTEM.md` so the agent map points to `research_entries` and
  `analysis_entries` as the active knowledge tables and describes `contacts` as
  touchpoints;
- `docs/DB-FIELD-AUDIT-2026-06-18.md` or a newer replacement audit so removed
  fields are not presented as active schema;
- `README.md` if it mentions pipeline storage, statuses, contacts, Notion sync,
  source links, or dossier generation;
- `agents/prompts/*.md` where prompt-level behavior is documented in prose;
- `config/notion_mapping.yaml` comments if they describe old contact fields or
  source-link behavior.

Documentation should name the active contract file:

```text
docs/superpowers/specs/2026-06-19-database-agent-cleanup-consolidated-design.md
```

Old docs may keep historical context, but they must clearly say when they are
superseded and must not read like active runtime guidance.

## Notion Projection

### Companies

Notion companies database should project only current card fields:

- title: `companies.name`;
- ICP segment;
- website;
- LinkedIn;
- optional status if operators need it visible.

Derived evidence fields should not be projected from `companies`.

### Contacts

Notion contacts database should treat rows as touchpoints:

- title: `contacts.name`;
- type/select: `contacts.contact_type`;
- company relation: computed through `contacts.company_id ->
  companies.notion_page_id`;
- visible primary channels: email, phone, LinkedIn, X, Facebook, Instagram;
- secondary channels: rendered from `other_channels`.

Both `companies` and `contacts` keep `notion_page_id` and `notion_synced_at`.

## Migration Strategy

The migration should be ordered to avoid agents writing into a partially updated
schema.

1. Confirm `source_links` is empty in the target database.
2. Update script helpers and prompts to stop writing legacy fields.
3. Update tests to describe the new contracts.
4. Change schema:
   - remove legacy `companies` columns;
   - remove `source_links`;
   - change `contacts.first_name`/`last_name` to `contacts.name`;
   - add `contacts.contact_type`;
   - update contact indexes and constraints.
5. Update Notion mapping and sync code for contact `name` and `contact_type`.
6. Update project documentation to describe the new active contract.
7. Run a small discovery/source-expansion/enrichment/analysis pass.
8. Verify research entries, analysis entries, contacts, dossiers, and Notion
   sync all use the new shape.

## Rollout Verification

Before dropping `source_links`:

```sql
SELECT count(*) FROM source_links;
```

Expected: `0`.

After schema migration:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name = 'source_links';
```

Expected: no rows.

Verify company cleanup:

```sql
SELECT column_name
FROM information_schema.columns
WHERE table_name = 'companies'
  AND column_name IN (
    'last_signal_date',
    'created_from_signal_id',
    'last_signal_id',
    'last_verified',
    'site_note',
    'funding_stage',
    'funding_date',
    'funding_amount',
    'team_size',
    'website_snippet',
    'dm_enriched_at'
  );
```

Expected: no rows.

Verify research entries are written:

```sql
SELECT id, company_id, entry_type, source, url, agent, created_at
FROM research_entries
WHERE company_id = '<company_id>'
ORDER BY created_at DESC
LIMIT 20;
```

Verify analysis provenance:

```sql
-- Use the implementation's analysis provenance table.
-- It must link analysis_entries rows back to research_entries rows.
```

Verify contacts:

```sql
SELECT id, company_id, contact_type, name, email, linkedin_url, other_channels
FROM contacts
WHERE company_id = '<company_id>'
ORDER BY contact_type, name;
```

## Testing

Update focused tests around the new contracts:

- schema tests assert `source_links` is absent;
- schema tests assert removed `companies` columns are absent;
- schema tests assert `contacts.name` and `contacts.contact_type` exist;
- research entry model tests verify insert/dedupe behavior;
- enrichment tests assert resolvers write research entries;
- dossier store tests remove source-link CRUD coverage;
- contacts store tests assert new payload and dedupe behavior;
- Notion sync tests assert contact title uses `name` and type is synced;
- prompt tests assert agents no longer mention `source_links` or removed company
  fields as write targets;
- documentation review asserts active project docs do not present removed fields
  as the current schema;
- analysis provenance tests assert analysis entries link back to research
  entries.

## Open Decisions

| Decision | Recommendation |
|---|---|
| Add a `research_entries.entry_role` column now or defer to `payload.role` | Defer unless implementation needs fast querying by role. |
| Keep temporary compatibility for old contact payloads | Keep only inside `contacts_store.py` for one migration cycle, then remove. |
| Represent DM enrichment completion as a research entry | Yes, if the pipeline needs auditability; otherwise derive from contacts. |
| Preserve old signal/source type vocabulary | Defer vocabulary cleanup; table naming and table semantics come first. |
