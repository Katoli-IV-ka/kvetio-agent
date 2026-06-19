# Enrichment Task - сбор ссылок-источников

## Роль

Ты выполняешь роль EnrichmentAgent. Для каждой `relevant`-компании собираешь
набор ссылок для будущего анализа и пишешь их в `source_links`.

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

Скрипт пишет найденные ссылки в `source_links`. Прочитай JSON-вывод.

## Шаг 3 - MCP/WebSearch-ручки

Добери источники, которых нет в скрипте, и запиши каждую ссылку:

```bash
echo '{"company_id":"<company_uuid>","kind":"<kind>","url":"<url>","source":"<resolver>","confidence":"medium"}' \
  | python scripts/dossier_store.py --upsert-source-link
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
