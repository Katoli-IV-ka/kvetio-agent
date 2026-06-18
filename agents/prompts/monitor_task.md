# Monitor Task - signal refresh loop

## Роль

MonitorAgent is a signal refresh loop, not a separate status machine.

## Select stale companies

```sql
SELECT id, domain, name, icp_segment, last_verified, status
FROM companies
WHERE status IN ('relevant', 'sources_gathered', 'analyzed', 'dossier_ready', 'manual_review')
  AND (last_verified IS NULL OR last_verified < CURRENT_DATE - INTERVAL '7 days')
ORDER BY last_verified ASC NULLS FIRST
LIMIT 30;
```

## Signal checks

For each company, check:
- HuggingFace models or datasets;
- ML/data jobs;
- funding or product news;
- public product/docs changes.

For every new signal:
- insert a row into `signals`;
- use `signal_type` prefixed with `monitor_`;
- update `companies.last_verified = CURRENT_DATE`.

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
