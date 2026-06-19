# Enrichment Task - сбор ссылок-источников

## Роль

Ты выполняешь роль EnrichmentAgent. Для каждой `relevant`-компании собираешь
набор ссылок для будущего анализа и пишешь их в `research_records`.

ВАЖНО: здесь ты НЕ интерпретируешь и НЕ анализируешь данные - только находишь и
сохраняешь URL с provenance. Анализ выполняется в `analysis_task`.

**Следующий этап:** `analysis_task`.

## Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---:|---|
| `segment` | all | Фильтр по сегменту |
| `limit` | 5 | Максимум компаний на сегмент |

## Шаг 1 - Список компаний

```sql
SELECT domain, name, website, icp_segment
FROM companies
WHERE status = 'relevant'
  AND ('<segment>' = 'all' OR icp_segment = '<segment>')
ORDER BY updated_at DESC
LIMIT <limit>;
```

## Шаг 2 - Детерминированные резолверы

```bash
python scripts/enrichment.py --domain <domain>
```

Скрипт пишет найденные ссылки в `research_records` с `record_role='source'`.
Прочитай JSON-вывод.

## Шаг 3 - MCP/WebSearch-ручки

Добери источники, которых нет в скрипте, и запиши каждую ссылку как
`research_records` row:

```sql
INSERT INTO research_records
  (company_id, record_type, record_role, source, url, confidence, observed_at, payload, dedupe_key)
VALUES
  ('<company_uuid>', 'source_link', 'source', '<resolver>', '<url>', 0.5, CURRENT_DATE,
   '{"kind":"<kind>"}'::jsonb, '<sha1>');
```

Собирай, если найдено:
- `hf_org`;
- `news_feed`;
- `social`;
- `wikidata`;
- product docs/blog pages.

## Шаг 4 - Перевести статус

```sql
UPDATE companies
SET status = 'sources_gathered',
    updated_at = NOW()
WHERE domain = '<domain>';
```

## Шаг 5 - Отчет

```bash
python scripts/notify.py --run-summary '{"task":"enrichment_task","processed":<N>,"links_total":<M>}'
```

## Граничные случаи

- Резолвер ничего не нашел - это нормально, продолжай.
- Компания не `relevant` - не трогать.
