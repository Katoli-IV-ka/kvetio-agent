# Source Expansion Task - supporting links and signals

## Роль

Ты выполняешь роль SourceExpansionAgent. Берешь `relevant` companies and gathers
supporting URLs, source links, and verification signals for analysis.

**Следующий этап:** `analysis_task`.

## Шаг 1 - Select companies

```sql
SELECT domain, name, website, icp_segment
FROM companies
WHERE status = 'relevant'
  AND ('<segment>' = 'all' OR icp_segment = '<segment>')
ORDER BY updated_at DESC
LIMIT <limit>;
```

## Шаг 2 - Gather sources

Use website, search, GitHub, HuggingFace, news, docs, and company profiles.
For every supporting fact, prefer a durable URL and write:
- `source_links` for analysis inputs;
- `signals` with `signals.url` and `signals.signal_type` prefixed with
  `verification_` when the URL proves relevance.

## Шаг 3 - Status update

```sql
UPDATE companies
SET status = 'sources_gathered',
    updated_at = NOW()
WHERE domain = '<domain>';
```

## Шаг 4 - Report

```bash
python scripts/notify.py --run-summary '{"task":"source_expansion_task","processed":<N>,"links_total":<M>}'
```
