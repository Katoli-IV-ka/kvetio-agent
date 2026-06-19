# Conclusions Task - final dossier and Notion sync

## Роль

Ты выполняешь роль ConclusionAgent. Берешь companies со статусом `analyzed`,
читаешь `analysis_records`, собираешь итоговое dossier и переводишь компанию в
`dossier_ready`.

## Select companies

```sql
SELECT id, domain, name, website, icp_segment, description
FROM companies
WHERE status = 'analyzed'
ORDER BY updated_at DESC
LIMIT 10;
```

## Inputs

```bash
python scripts/dossier_store.py --list-analysis-records <company_id>
```

## Summary sections

Собери 6 секций:
- О компании;
- Продукт;
- Сотрудничество;
- Финансы;
- Новости;
- Аудит.

## Write dossier

```bash
python scripts/dossier_store.py --upsert-dossier
```

Write typed fields (`funding_stage`, `funding_amount_usd`, `funding_date`,
`team_size_estimate`, `product_category`, `ai_use_case`, `icp_fit`,
`last_news_date`), `section_summaries`, `summary_md`, and `audit_md`.
Then write `dossier_links` for every contributing `analysis_record`.

## Status update

```sql
UPDATE companies
SET status = 'dossier_ready',
    updated_at = NOW()
WHERE domain = '<domain>';
```

## Notion

After dossier write, run:

```bash
python scripts/notion_sync.py --entity companies --all
python scripts/notion_sync.py --entity dossiers
```

Use the repository sync script. Do not publish ad hoc pages manually.
