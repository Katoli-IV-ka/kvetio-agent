# Analysis & Dossier Pipeline — для компаний со статусом sources_gathered

## Роль

Выполняет stages `analysis` и `conclusions` для компаний, которые уже в статусе `sources_gathered` (например, из site_researched).

## Параметры

```
limit=5; dry_run=false; notion_sync=true
```

## Шаг 1 - Проверка Supabase

```bash
python scripts/supabase_store.py --coverage
```

## Шаг 2 - Analysis Stage

Для каждой компании со статусом `sources_gathered` (макс `limit`):

```sql
SELECT id, domain, name, icp_segment
FROM companies
WHERE status = 'sources_gathered'
ORDER BY created_at DESC
LIMIT <limit>;
```

**Для каждой компании:**

1. Собери все `research_records` по `company_id`.
2. Запусти анализ по 5 секциям (смотри `agents/prompts/analysis_task.md`):
   - `company` — информация о компании
   - `product` — описание продукта
   - `collaboration` — партнёрства и команда
   - `financials` — финансовая информация
   - `news` — новости и события

3. Для каждой секции вызови вложенный AnalysisSection с промптом `analysis_section_task.md`.

4. Запиши результаты в `analysis_records` с `record_type='analysis'`.

5. Обнови статус компании на `analyzed`.

## Шаг 3 - Conclusions Stage

Для каждой компании со статусом `analyzed`:

1. Собери все `analysis_records` по `company_id`.
2. Запусти conclusions (смотри `agents/prompts/conclusions_task.md`).
3. Собери dossier с финальными типизированными полями:
   - `icp_fit` (strong/moderate/weak/unknown)
   - `funding_stage`, `funding_amount_usd`, `funding_date`
   - `product_category`, `ai_use_case`
   - `summary_md`, `audit_md`

4. Запиши dossier в `dossiers` через:
   ```bash
   python scripts/dossier_store.py --upsert-dossier
   ```

5. Обнови статус компании на `dossier_ready`.

## Шаг 4 - Notion Sync

Если `notion_sync=true` и `dry_run=false`:

```bash
python scripts/notion_sync.py --entity companies --all
python scripts/notion_sync.py --entity dossiers
```

## Итоговая сводка

```json
{
  "task": "analyze_and_conclude",
  "limit": 5,
  "dry_run": false,
  "notion_sync": true,
  "analyzed": 0,
  "dossier_ready": 0,
  "errors": 0
}
```

Отправь уведомление:
```bash
python scripts/notify.py --run-summary '<json>'
```
