# Conclusions Task - final dossier and Notion sync

## Роль

Ты выполняешь роль ConclusionAgent. Берешь companies со статусом `analyzed`,
читаешь `analysis_notes`, собираешь итоговое dossier и переводишь компанию в
`dossier_ready`.

## Select companies

```sql
SELECT domain, name, website, icp_segment, description, funding_stage, team_size
FROM companies
WHERE status = 'analyzed'
ORDER BY updated_at DESC
LIMIT 10;
```

## Inputs

```bash
python scripts/dossier_store.py --list-analysis-notes <domain>
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
