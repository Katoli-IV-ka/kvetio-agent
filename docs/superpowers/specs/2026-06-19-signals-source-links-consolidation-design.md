# Signals And Source Links Consolidation — Design Spec
**Date:** 2026-06-19
**Status:** Draft for review

## Goal

Make `signals` the single evidence/source layer for company analysis and remove
`source_links` completely.

`source_links` is currently empty, so this change does not need data backfill,
a compatibility view, or a transitional dual-write period.

This design intentionally does not define, add, remove, or rename concrete
values in `signal_types`. Signal type vocabulary changes are a separate decision.

## Problem

`source_links` and `signals` overlap. Both can represent a URL found for a
company, with provenance, confidence, source metadata, and raw payload.

Keeping both tables makes the analysis pipeline harder to reason about:

- enrichment writes URL evidence to `source_links`;
- discovery and verification write evidence to `signals`;
- analysis has to read both tables;
- provenance can split between `source_links.source_signal_id` and direct
  `signals` rows;
- deduplication rules differ across evidence tables.

The simpler model is: every URL or finding that may be analyzed is a signal.

## Non-Goals

- Do not change the concrete values seeded in `signal_types`.
- Do not design a new scoring model.
- Do not keep `source_links` as a view.
- Do not support backward-compatible reads from `source_links`.
- Do not backfill `source_links`, because it is empty.

## Target Data Model

`signals` becomes the only source of company evidence and analysis inputs.

Target evidence flow:

```text
companies
  -> signals
      -> analysis_note_signals
          -> analysis_notes
              -> dossiers
```

`source_links` is removed from the schema.

Former `source_links` concepts map to `signals` as follows:

| Former `source_links` field | Target location |
|---|---|
| `company_id` | `signals.company_id` |
| `kind` | `signals.signal_type` or `signals.payload.kind` |
| `url` | `signals.url` |
| `source` | `signals.source` |
| `confidence` | `signals.confidence` |
| `found_via` | `signals.agent` or `signals.payload.found_via` |
| `source_signal_id` | Removed; the row itself is the signal |
| `raw` | `signals.raw_data` |
| `fetched_at` | `signals.created_at` or `signals.payload.fetched_at` |

Rule: if a URL can be used by analysis, store it as a `signals` row.

## Signal Role

The system should not encode pipeline stage into `signal_type` values. The
meaning of a signal type should be the kind of evidence, not whether it came
from discovery, verification, monitoring, or analysis input collection.

If the implementation needs to preserve this distinction, add a separate
column to `signals`:

```sql
signal_role TEXT NOT NULL DEFAULT 'evidence'
CHECK (signal_role IN ('primary', 'verification', 'monitor', 'analysis_input', 'evidence'))
```

This keeps the model clean:

| Field | Meaning |
|---|---|
| `signal_type` | What kind of evidence this is |
| `signal_role` | Why the pipeline stored it |
| `agent` | Which agent produced it |
| `source` | Which external/internal source produced it |

If implementation scope needs to stay smaller, `signal_role` can be deferred
and the role can temporarily live in `signals.payload.role`.

## Pipeline Changes

### Enrichment

`scripts/enrichment.py` should stop calling `upsert_source_link()`.

Each resolver should return or create a signal-shaped payload and write it
through the signals storage path.

The resolver output should preserve resolver-specific fields in `payload`.
Examples include original `kind`, `found_via`, external IDs, and fetched
timestamps.

### Dossier Store

`scripts/dossier_store.py` should remove source-link CRUD:

- remove `upsert_source_link()`;
- remove `get_source_links()`;
- remove source-link CLI commands.

If analysis needs a convenience helper, add a read helper that returns analysis
input signals for a `company_id`.

### Prompts

Prompts should refer to `signals` as the single evidence input:

- `enrichment_task.md`: write gathered URLs as signals;
- `source_expansion_task.md`: supporting URLs are signals;
- `analysis_task.md`: read `signals`, not `source_links`;
- `analysis_section_task.md`: use `signals.signal_type`, `signals.source`,
  `signals.url`, `signals.summary`, `signals.payload`, and `signals.raw_data`.

### Analysis Provenance

`analysis_note_signals` remains the provenance link between interpretation and
evidence.

Analysis should link each `analysis_notes` row to the signal IDs it used, with
the existing roles:

- `supports`;
- `contradicts`;
- `context`.

## Schema Changes

Remove `source_links` from the canonical schema.

Remove:

- `CREATE TABLE source_links`;
- `idx_source_links_company`;
- `idx_source_links_kind`;
- any schema comments that list `source_links` as an active runtime table.

Keep:

- `signals`;
- `analysis_notes`;
- `analysis_note_signals`;
- `dossiers`.

If `signal_role` is included in this implementation, add it to `signals` and
cover it in schema tests. This is independent of concrete `signal_types` values.

## Migration Strategy

Because `source_links` is empty, migration is destructive and simple:

1. Confirm `source_links` row count is zero in the target database.
2. Deploy code/prompt changes that stop reading and writing `source_links`.
3. Drop `source_links`.
4. Verify enrichment writes signals.
5. Verify analysis reads signals and writes `analysis_notes`.

No data backfill is required.

No compatibility view is required.

## Deduplication

The existing signal dedupe model should remain the canonical dedupe path.

For URL-backed signals, dedupe by:

```text
company_id + signal_type + url
```

For signals without a URL, use a stable source-specific fallback such as:

```text
company_id + signal_type + source + external_id
```

Resolver code should prefer durable URLs whenever available.

## Testing

Update tests around the new source-of-truth model:

- schema tests assert `source_links` is not created;
- enrichment tests assert resolvers write signals;
- dossier store tests remove source-link CRUD coverage;
- prompt tests assert `source_links` is no longer required;
- analysis provenance tests assert `analysis_note_signals` can link notes to
  signals;
- signal model tests continue to verify signal insert/dedupe behavior.

## Rollout Verification

Minimum verification after implementation:

```sql
SELECT count(*) FROM source_links;
```

Expected before drop: `0`.

After deployment:

```sql
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public'
  AND table_name = 'source_links';
```

Expected after drop: no rows.

Run a small enrichment pass and verify new signal rows exist for the target
company:

```sql
SELECT id, company_id, signal_type, source, url, agent, created_at
FROM signals
WHERE company_id = '<company_id>'
ORDER BY created_at DESC
LIMIT 20;
```

Then run analysis and verify notes link back to signals:

```sql
SELECT ans.analysis_note_id, ans.signal_id, ans.role
FROM analysis_note_signals ans
JOIN analysis_notes an ON an.id = ans.analysis_note_id
WHERE an.company_id = '<company_id>';
```

## Open Decisions

Only one implementation decision remains:

| Decision | Recommendation |
|---|---|
| Add `signals.signal_role` now or defer it to `payload.role` | Add the column now if touching the schema anyway; otherwise defer to keep the first consolidation small. |

The decision does not affect removal of `source_links`.
