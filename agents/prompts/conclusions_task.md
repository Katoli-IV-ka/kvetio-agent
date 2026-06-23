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

Write typed fields to `dossiers`:

**Существующие поля:**
- `funding_stage`, `funding_amount_usd`, `funding_date`
- `product_category`, `ai_use_case`
- `icp_fit`, `last_news_date`
- `section_summaries`, `summary_md`, `audit_md`

Размер компании не записывай в `dossiers`: используй `companies.company_size`,
которое заполняет firmographics enrichment.

**Новые sales-brief поля (обязательно заполнить для dossier_ready):**
- `pain_summary` — 2-4 предложения: какая конкретная боль с данными есть у этой компании исходя из их продукта. Не сухой список типов данных — нарратив специфики и проблемы. Пример: "Компания строит систему сегментации медицинских снимков. Узкое место — размеченные DICOM-датасеты: публичных почти нет, внутренняя разметка дорогая и медленная, а качество критично для регуляторного одобрения."
- `pitch_angle` — 1-2 предложения: наш конкретный угол ценностного предложения для этой компании. Пример: "Мы можем поставить pre-labelled DICOM датасеты от аккредитованных радиологов, что сокращает time-to-model на 3-6 месяцев."
- `why_interesting` — 1-3 предложения: внутренняя заметка, почему лид сильный. Пример: "Свежий раунд Series A, активный найм ML-инженеров, CEO публично жаловался на annotation bottleneck на конференции."
- `outreach_hook` — одно конкретное свежее событие ЛПР для первого сообщения в LinkedIn. Пример: "Выступил на MICCAI 2025 с докладом «Annotation Quality in Medical AI»." Если события нет — оставить null.

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
python scripts/notion_sync.py --entity companies --forward
python scripts/notion_sync.py --entity contacts --forward
```

`enrich_company_rows` автоматически подтянет dossier и синтезирует `Funding Info`.
Новые колонки (ICP Segment, Country, Founded, Company Size, Funding Info) обновятся
в таблице Companies в Notion.

Use the repository sync script. Do not publish ad hoc pages manually.
