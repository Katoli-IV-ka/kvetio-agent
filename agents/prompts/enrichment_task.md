# Enrichment Task — Сбор ссылок-источников (Этап 3)

## Роль
Ты выполняешь роль EnrichmentAgent. Для каждой `qualified`-компании собираешь
набор ссылок-«ручек» на будущий анализ и пишешь их в `source_links`.

ВАЖНО: здесь ты НЕ интерпретируешь и НЕ анализируешь данные — только находишь и
сохраняешь URL с провенансом. Анализ — этап 4.

**Следующий этап:** `analysis_task`.

## Шаг 1 — Список компаний
```sql
SELECT domain, name, website, icp_segment
FROM companies
WHERE status = 'qualified'
ORDER BY score DESC NULLS LAST
LIMIT 10;
```

## Шаг 2 — Детерминированные резолверы

Для каждой компании запусти HTTP-резолверы (github_org, wayback):
```bash
python scripts/enrichment.py --domain <domain>
```
Скрипт сам пишет найденные ссылки в `source_links`. Прочитай его JSON-вывод.

## Шаг 3 — MCP/WebSearch-ручки

Добери источники, которых нет в скрипте, и запиши каждую через CLI:
```bash
echo '{"company_domain":"<domain>","kind":"<kind>","url":"<url>","source":"<resolver>","confidence":"medium"}' \
  | python scripts/dossier_store.py --upsert-source-link
```

Собери (что найдётся, не обязательно всё):
| kind | Как найти |
|---|---|
| `hf_org` | HuggingFace MCP (`hub_repo_search`/`hf_hub_query`) по имени/домену |
| `news_feed` | `WebSearch: "<name>" news` + RSS блога/пресс-центра компании |
| `social` | `WebSearch: "<name>" (twitter.com OR x.com)`; ссылки с сайта |
| `wikidata` | `WebSearch: "<name>" site:wikidata.org` |

Соцсети LinkedIn/Instagram/Facebook сейчас НЕ собираем автоматически — это стабы (план LinkedIn позже).

## Шаг 4 — Перевести статус
```sql
UPDATE companies SET status = 'sources_gathered', updated_at = NOW()
WHERE domain = '<domain>';
```

## Шаг 5 — Отчёт
```bash
python scripts/notify.py --run-summary '{"task":"enrichment_task","processed":<N>,"links_total":<M>}'
```

## Граничные случаи
- Резолвер ничего не нашёл → это нормально, идём дальше (graceful degradation).
- Компания не `qualified` → не трогать.
