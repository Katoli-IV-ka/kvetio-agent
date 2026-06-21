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

### Refresh-ветка (NewsAgent, обновление досье по свежей новости)

Дополнительно добери уже готовые досье, помеченные на обновление:

```sql
SELECT id, domain, name, icp_segment, needs_refresh
FROM companies
WHERE status = 'dossier_ready' AND needs_refresh IS NOT NULL
ORDER BY needs_refresh ASC
LIMIT 10;
```

Для них AnalysisAgent уже пере-собрал секции `news` и `financials`. Обнови
соответствующие поля досье (`last_news_date`, `funding_*`, `extra_facts`),
секции `news`/`financials` в `section_summaries` и `summary_md` — инкрементально,
не трогая остальные секции. Статус остаётся `dossier_ready` (только вверх).

После обновления **погаси флаг**:

```bash
python scripts/supabase_store.py  # через store.clear_needs_refresh(<domain>)
```

```sql
UPDATE companies SET needs_refresh = NULL WHERE domain = '<domain>';
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
