# Monitor Task - technical signal refresh loop

## Роль

MonitorAgent is a **technical** signal refresh loop, not a separate status machine.

> **Scope (narrowed by NewsAgent).** Monitor owns technical signals only: new HF
> models, GitHub activity, ML/data job postings, public product/site changes.
> News and funding-news are owned by **NewsAgent** (`agents/prompts/news_task.md`)
> — do not duplicate them here.

## Select stale companies

```sql
SELECT id, domain, name, icp_segment, status
FROM companies
WHERE status IN ('relevant', 'sources_gathered', 'analyzed', 'dossier_ready', 'manual_review')
ORDER BY updated_at ASC
LIMIT 30;
```

## Signal checks

For each company, check **technical** signals only:
- HuggingFace models or datasets;
- GitHub activity;
- ML/data job postings;
- public product/docs/site changes.

Do NOT check news or funding-news — those belong to NewsAgent.

For every new finding:
- insert a row into `research_records`;
- use `record_role = 'monitor'`;
- leave derived freshness to queries over `research_records.observed_at`.

Do not write legacy monitor-only statuses, company summary fields, score fields,
or score buckets.

## Status updates

- leave status unchanged when the signal is only informational;
- set status = 'manual_review' when the signal suggests re-evaluation;
- set status = 'not_relevant' only when there is clear evidence the company no
  longer fits.

## Notifications

```bash
python scripts/notify.py --run-summary '{"task":"monitor_task","found":<N>,"errors":0}'
```
