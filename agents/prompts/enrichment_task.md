# Enrichment Task — сбор ссылок-источников (детерминированные резолверы)

## Роль

Ты выполняешь роль EnrichmentAgent. Для каждой компании со статусом `relevant`
собираешь набор ссылок-источников для будущего анализа и пишешь их в
`research_records`.

ВАЖНО: здесь ты НЕ интерпретируешь и НЕ анализируешь данные — только находишь и
сохраняешь URL с provenance. Интерпретация — на стадии `analysis_task`.

**Следующий этап:** `analysis_task` (после `source_expansion_task` и `dm_enrich_task`).

## Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---:|---|
| `segment` | all | Фильтр по сегменту |
| `limit` | 5 | Максимум компаний на сегмент |

## Шаг 1 — Список компаний

```sql
SELECT id, domain, name, website, icp_segment
FROM companies
WHERE status = 'relevant'
  AND ('<segment>' = 'all' OR icp_segment = '<segment>')
ORDER BY updated_at DESC
LIMIT <limit>;
```

## Шаг 2 — Детерминированные резолверы (скрипт)

```bash
python scripts/enrichment.py --domain <domain>
```

Скрипт прогоняет все включённые в `config/sources.yaml` резолверы и пишет найденное
в `research_records` (`record_role='source'`, `record_type='source_link'`,
`payload.kind` = тип источника). Прочитай JSON-вывод (`written`) и пойми, что уже
собрано, чтобы не дублировать руками.

Что покрывают резолверы сейчас:

| `payload.kind` | Источник | Для секции досье |
|---|---|---|
| `github_org` | GitHub-организация (из ранее собранных сигналов) | Продукт, Сотрудничество |
| `wayback` | ближайший снапшот сайта (динамика позиционирования, детект пивота) | Компания, Продукт |
| `arxiv` | недавние публикации по имени компании (до 5) | Продукт (R&D, технологии) |
| `papers_with_code` | research с реализациями по имени компании | Продукт |
| `wikidata` | дата основания, штаб-квартира, руководство, размер | Компания |
| `company_registry` | OpenCorporates: юрлицо, юрисдикция, дата регистрации | Компания |

Замечания по достоверности (передаются дальше в анализ):
- `arxiv` и `papers_with_code` матчат по имени → возможны ложные совпадения.
  Резолвер кладёт `title`/`authors` в payload — на анализе сверяй, что статья
  реально про эту компанию, иначе помечай как неподтверждённое.
- `wikidata`/`company_registry` берут топ-1 результат поиска → в payload есть
  `label`/`legal_name` для проверки соответствия сущности компании.

## Шаг 3 — Web-ручки (добор того, чего нет в скрипте)

Через WebSearch / WebFetch (для JS-сайтов — Claude-in-Chrome; HF — MCP) добери
источники и запиши КАЖДУЮ ссылку как `research_records` row. Не интерпретируй —
только фиксируй URL + `payload.kind`.

Приоритет для секций «О компании» и «Продукт» (текущий фокус):

- **Компания:** официальный сайт `/about`, `/company`, страница команды; Crunchbase
  (публичная страница), LinkedIn company (публичная), Wikipedia. `kind`:
  `about_page`, `crunchbase_public`, `linkedin_company`, `wikipedia`.
- **Продукт:** `/product(s)`, `/platform`, `/solutions`, документация (`docs.`,
  `/docs`), changelog / release notes, инженерный блог, Product Hunt, демо/видео,
  HuggingFace org (модели и датасеты), GitHub repos (по основному продукту).
  `kind`: `product_page`, `docs`, `changelog`, `blog`, `product_hunt`, `hf_org`,
  `github_repo`.

Запись вручную:

```sql
INSERT INTO research_records
  (company_id, record_type, record_role, source, url, confidence, observed_at, payload, dedupe_key)
VALUES
  ('<company_uuid>', 'source_link', 'source', '<resolver|websearch>', '<url>', 0.5,
   CURRENT_DATE, '{"kind":"<kind>"}'::jsonb, '<sha1>');
```

Правила:
- Предпочитай долговечный канонический URL (страница продукта, doc, repo), а не
  поисковую выдачу.
- Не дублируй то, что уже записал скрипт в Шаге 2 (сверься по URL/kind).
- Не нашёл источник конкретного типа — это нормально, фиксируй как пробел (ничего
  не пиши), не выдумывай ссылку.

## Шаг 4 — Перевести статус

```sql
UPDATE companies
SET status = 'sources_gathered',
    updated_at = NOW()
WHERE domain = '<domain>';
```

## Шаг 5 — Отчёт

```bash
python scripts/notify.py --run-summary '{"task":"enrichment_task","processed":<N>,"links_total":<M>}'
```

## Граничные случаи

- Резолвер ничего не нашёл — нормально, продолжай.
- Компания не `relevant` — не трогать.
- OpenCorporates/Wikidata вернули неподходящую сущность — не записывай ссылку как
  факт; если уже записана скриптом, на анализе она будет помечена как непроверенная.
