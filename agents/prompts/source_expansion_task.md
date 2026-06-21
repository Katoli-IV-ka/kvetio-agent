# Source Expansion Task — сбор источников о компании

## Роль

Ты выполняешь роль SourceExpansionAgent. Берёшь компании со статусом `relevant`
и собираешь курированный набор URL-источников для последующего анализа. Ты НЕ
интерпретируешь данные — только находишь долговечные ссылки и пишешь их в
`research_records` с provenance.

В полном прогоне это основная стадия сбора источников: она запускает и
детерминированные резолверы (скрипт), и добор мягких источников агентом. Поэтому
обязательно выполняй Шаг 2 (скрипт) — иначе новые резолверы не отработают.

**Следующий этап:** `dm_enrich_task` → `analysis_task`.

## Параметры

| Параметр | По умолчанию | Описание |
|---|---:|---|
| `segment` | all | Фильтр по сегменту |
| `limit` | 5 | Максимум компаний на сегмент |

## Шаг 1 — Выбрать компании

```sql
SELECT id, domain, name, website, icp_segment
FROM companies
WHERE status = 'relevant'
  AND ('<segment>' = 'all' OR icp_segment = '<segment>')
ORDER BY updated_at DESC
LIMIT <limit>;
```

## Шаг 2 — Детерминированные резолверы (обязательно)

```bash
python scripts/enrichment.py --domain <domain>
```

Прогоняет включённые резолверы (`config/sources.yaml`) и пишет источники в
`research_records` (`record_role='source'`). Прочитай JSON-вывод (`written`).
Сейчас покрыты: `github_org`, `wayback`, `arxiv`, `papers_with_code`, `wikidata`,
`company_registry`. Это закрывает значимую часть секций «О компании» и «Продукт» —
не дублируй их вручную.

## Шаг 3 — Добор мягких источников агентом

Через WebSearch / WebFetch (JS-сайты — Claude-in-Chrome; HF — MCP) найди то, чего
скрипт не покрывает. Для каждого источника фиксируй канонический URL + `payload.kind`.
Цель — закрыть все шесть секций досье; приоритет сейчас на «О компании» и «Продукт».

| Секция | Что искать | `payload.kind` |
|---|---|---|
| О компании | `/about`, `/company`, команда; Crunchbase (публичная), LinkedIn company, Wikipedia; сторонние профили (директории, обзоры рынка) | `about_page`, `crunchbase_public`, `linkedin_company`, `wikipedia`, `directory_listing` |
| Продукт | `/product(s)`, `/platform`, `/solutions`, документация, changelog/release notes, инженерный блог, Product Hunt, демо/видео, HF org (модели+датасеты), GitHub repos | `product_page`, `docs`, `changelog`, `blog`, `product_hunt`, `hf_org`, `github_repo` |
| Сотрудничество | пресс-релизы и анонсы партнёрств, страницы клиентов/кейсов, упоминания поставщиков данных | `press_release`, `partnership`, `customer_case` |
| Финансы | анонсы раундов/грантов, Crunchbase funding, профильные новости | `funding_announcement`, `crunchbase_public`, `news` |
| Новости | свежие материалы за 6–12 мес (разные инфоповоды) | `news`, `blog` |

Запись:

```sql
INSERT INTO research_records
  (company_id, record_type, record_role, source, url, confidence, observed_at, payload, dedupe_key)
VALUES
  ('<company_uuid>', 'source_link', 'source', 'websearch', '<url>', 0.5, CURRENT_DATE,
   '{"kind":"<kind>"}'::jsonb, '<sha1>');
```

Если URL прямо подтверждает релевантность (собственные модели, обучение, датасеты) —
ставь `record_role = 'verification'`.

## Правила качества

- Долговечный канонический URL вместо поисковой выдачи или редиректа.
- Один источник — одна запись; не дублируй то, что записал скрипт (сверься по URL).
- Нет источника нужного типа — фиксируй как пробел, не выдумывай ссылку.

## Шаг 4 — Перевести статус

```sql
UPDATE companies
SET status = 'sources_gathered',
    updated_at = NOW()
WHERE domain = '<domain>';
```

## Шаг 5 — Отчёт

```bash
python scripts/notify.py --run-summary '{"task":"source_expansion_task","processed":<N>,"links_total":<M>}'
```
