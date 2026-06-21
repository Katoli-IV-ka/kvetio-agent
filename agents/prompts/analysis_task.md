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

### Refresh-выборка (NewsAgent, режим обновления досье)

Помимо обычной выборки, в режиме refresh добери `dossier_ready`-компании со
свежим сильным новостным сигналом (флаг `needs_refresh`):

```sql
SELECT id, domain FROM companies
WHERE status = 'dossier_ready' AND needs_refresh IS NOT NULL
ORDER BY needs_refresh ASC
LIMIT <limit>;
```

Для этих компаний пере-собирай **инкрементально только секции `news` и
`financials`** (не весь анализ) — там, где появился новый инфоповод. Статус НЕ
меняй (он уже `dossier_ready` и понижаться не может). Флаг гасит ConclusionAgent
после обновления полей досье.

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

**Refresh-режим:** для `dossier_ready`-компаний из refresh-выборки статус НЕ
обновляй — статус только повышается. Обновлённые секции подхватит ConclusionAgent
по флагу `needs_refresh`.
