# Analysis Task - structured company analysis

## Роль

Ты выполняешь роль AnalysisAgent. Берешь companies со статусом
`sources_gathered`, читаешь `research_records`, сайт и публичные
источники, затем пишешь structured `analysis_records`.

**Следующий этап:** `conclusions_task`.

## Шаг 1 - Select companies

```sql
SELECT domain, name, website, icp_segment
FROM companies
WHERE status = 'sources_gathered'
ORDER BY updated_at DESC
LIMIT <limit>;
```

## Шаг 2 - Sections

Для каждой компании запусти секционные prompts:
- `agents/prompts/analysis_section_task.md`;
- `agents/prompts/analysis_audit_task.md`.

Разделы:
- company;
- product;
- collaboration;
- financials;
- news.

Каждый section должен отделять заявленные claims from verified facts and keep URLs.

## Шаг 3 - Write notes

Use:

```bash
python scripts/dossier_store.py --upsert-analysis-record
```

## Шаг 4 - Status update

```sql
UPDATE companies
SET status = 'analyzed',
    updated_at = NOW()
WHERE domain = '<domain>';
```
