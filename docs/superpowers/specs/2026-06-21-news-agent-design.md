# NewsAgent — News-Driven Discovery & Monitoring — Design

**Date:** 2026-06-21
**Status:** Draft for review
**Related:**
- `ARCHITECTURE.md` (агенты, статусный flow, схема БД)
- `docs/AGENT-ECOSYSTEM.md`
- `agents/prompts/monitor_task.md` (сужается этим дизайном)
- `agents/prompts/analysis_section_task.md` (секция `news`, `financials`)

---

## 1. Контекст и проблема

Текущий пайплайн находит компании через source-адаптеры (HuggingFace, YC,
GitHub, Greenhouse) на стадии Discovery. Новости задействованы слабо:

- `MonitorAgent` опционален, вне основного потока, и смешивает новостные сигналы
  (funding-новости, изменения продукта) с техническими (новые модели HF,
  вакансии) — отсюда риск дублирования.
- Секция `news` в досье наполняется тем, что случайно соберут SourceExpansion /
  Analysis, без систематического новостного мониторинга и без дедупа по
  инфоповоду.
- Нет канала, который **реагирует** на свежую новость: ни для обнаружения новой
  релевантной компании, ни для обновления досье уже известной.

**Цель:** выделенный `NewsAgent`, который систематически мониторит публичные
новостные источники, находит сигналы покупательского намерения (компания скоро
будет заинтересована в покупке датасетов/разметки), и:

1. заводит новую релевантную компанию в пайплайн (как альтернативный Discovery);
2. добавляет сигналы и обновляет досье компаниям, уже находящимся в базе.

Ограничение: **только бесплатные/публичные источники.**

---

## 2. Решение (обзор)

`NewsAgent` — отдельный **планируемый** агент (`agents/prompts/news_task.md`),
запускаемый по расписанию отдельным Routine. Он **не оркестрирует пайплайн** —
он выступает альтернативной точкой входа Discovery и поставщиком новостных
сигналов, переиспользуя существующие стадии.

Два потока:

| Поток | Вход | Действие | Выход |
|---|---|---|---|
| **News discovery** | отраслевые новости по ICP-сегментам | новая компания + сильный сигнал + грубый ICP-гейт | `companies.status='discovered'` + первичный `research_record` → точечный запуск пайплайна (`news_lead`) |
| **News monitoring** | новости по компаниям, уже в базе | релевантный инфоповод | `research_record` (`monitor`); сильный сигнал → флаг `needs_refresh` → инкрементальное обновление досье |

Ключевые принципы, унаследованные из архитектуры:

- **Наблюдение ≠ интерпретация.** NewsAgent пишет `research_records`; вся
  интерпретация остаётся в `analysis_records` (AnalysisAgent).
- **Один оркестратор.** PipelineAgent остаётся единственным дирижёром стадий.
- **RelevanceAgent — настоящий ICP-гейт.** Грубый фильтр NewsAgent может
  ошибаться: штатный RelevanceAgent перепроверит и при необходимости поставит
  `not_relevant`. Поэтому автозапуск по одному сильному сигналу безопасен.
- **Статус только повышается.** Обновление досье известной компании делается
  через флаг `needs_refresh`, а НЕ через откат статуса.

---

## 3. Границы ответственности

| Агент | Владеет | НЕ трогает |
|---|---|---|
| **NewsAgent** (новый) | медиа / пресс / RSS / новостные агрегаторы (GDELT, Google News, HN, RSS); funding-новости; новостной discovery; новостные сигналы известным компаниям | техническая интерпретация; оркестрация стадий |
| **MonitorAgent** (сужается) | технические сигналы: новые модели HF, GitHub-активность, вакансии, изменения сайта | новости и funding-новости (передаются NewsAgent) |
| **DiscoveryAgent** | source-адаптеры (HF/YC/GitHub/Greenhouse) | новости |
| **RelevanceAgent** | финальная квалификация ICP | — |

Это устраняет дублирование funding-новостей между Monitor и News.

---

## 4. Таксономия сигналов

NewsAgent классифицирует каждый дедуплицированный инфоповод в один класс.

### Сильные (→ автозапуск пайплайна для компании при прохождении ICP-гейта)

| `event_type` | Инфоповод |
|---|---|
| `funding_round` | закрыла раунд (Seed–Series C) в ICP-сегменте |
| `model_launch` | анонс обучения новой модели / запуск AI-продукта, требующего размеченных данных |
| `stealth_exit` | выход из stealth / новая компания в целевом сегменте |
| `data_need` | публичное заявление о нехватке данных / сборе собственного датасета |
| `hiring_surge` | всплеск найма ML / data / annotation ролей |

### Мягкие (→ только `research_record`, без полного прогона)

| `event_type` | Инфоповод |
|---|---|
| `partnership` | партнёрство, расширение на новый рынок/домен |
| `product_update` | релиз продукта/фичи без явной привязки к данным |
| `pr_mention` | награды, отраслевые упоминания, общий PR |
| `leadership_change` | смена руководства (приход CTO / Head of ML / CDO — ещё и контактный сигнал) |
| `negative` | layoffs, пивот, регуляторные проблемы |

### Порог автозапуска

Автозапуск пайплайна = **сильный сигнал + грубый ICP-гейт**:

1. инфоповод резолвится в реальную компанию с доменом;
2. компания попадает хотя бы в один ICP-сегмент;
3. компания не в стоп-листе (`icp_summary.md`: датасет-провайдеры/конкуренты,
   API-обёртки, бигтех, консалтинг).

Один сигнал, проходящий все три условия, запускает прогон. Финальную
квалификацию делает RelevanceAgent.

---

## 5. Источники (только бесплатное/публичное)

| Источник | Назначение | Доступ |
|---|---|---|
| **GDELT DOC 2.0 API** | мировой граф новостей, кластеризация инфоповодов, запрос по ключевым словам и по домену | бесплатно, без ключа |
| **Google News RSS** | запросы по ключевым словам сегмента (discovery) и по имени/домену (мониторинг) | бесплатно, без ключа |
| **Hacker News (Algolia API)** | Show HN / анонсы моделей и AI-продуктов | бесплатно |
| **Курируемый RSS-набор** | TechCrunch, VentureBeat, EU-Startups и отраслевые порталы по сегментам | бесплатно |
| **Пресс/блог-страницы компании** | свежие посты для уже известных компаний | бесплатно (WebFetch) |
| **SEC EDGAR Form D** | подтверждение funding-сигнала (US private) | бесплатно |

### Логика прохода

1. **Сегментный скан (discovery):** запросы = `keywords_strong` из `icp.yaml`
   × сигнальные термы (`raises`, `Series A/B`, `launches`, `out of stealth`,
   `building dataset`, `hiring ML`). LLM классифицирует инфоповод в
   сильный/мягкий.
2. **Per-company скан (monitoring):** запросы по имени/домену каждой известной
   компании (батчами, с ротацией).
3. **Relevance-гейт (грубый):** только ICP-сегменты; стоп-лист из `icp_summary`.

---

## 6. Entity resolution и дедуп

**Entity resolution:** из новости извлекается название компании → резолвится
домен (официальный сайт). Действуем только при резолвящемся домене — иначе
нечего дедуплицировать и вести. Инфоповод без домена → максимум «слабый лид» в
заметку, без создания компании.

**Дедуп по инфоповоду, а не по статье:**

- кластеры GDELT, где доступны;
- нормализация `(domain + event_type + дата-окно)` → `dedupe_key`;
- канонический URL в `research_records.url`, остальные источники того же события
  в `payload.alt_urls`;
- заголовок = суть события + ссылка (требование к секции `news`).

`dedupe_key = sha1(domain + '|' + event_type + '|' + date_bucket)` —
гарантирует идемпотентность повторных прогонов и схлопывание одного события из
многих изданий в одну строку.

---

## 7. Модель данных

Новой таблицы не вводим. Наблюдения пишутся в `research_records`; таксономия — в
`payload`.

### Запись наблюдения

```jsonc
{
  "company_id": "<uuid>",
  "record_type": "news",
  "record_role": "primary",      // discovery-путь: 'primary'; monitoring-путь: 'monitor'
  "source": "gdelt|google_news|hn|rss",
  "agent": "news",
  "url": "<канонический URL>",
  "title": "<суть инфоповода>",
  "confidence": 0.50,
  "observed_at": "2026-06-21",
  "payload": {
    "signal_class": "strong|soft",
    "event_type": "funding_round|model_launch|stealth_exit|data_need|hiring_surge|partnership|product_update|pr_mention|leadership_change|negative",
    "event_date": "2026-06-19",
    "headline": "<заголовок = суть>",
    "alt_urls": ["<другие издания того же события>"]
  },
  "dedupe_key": "<sha1(domain|event_type|date_bucket)>"
}
```

Таксономию кодируем в `payload`, чтобы не гонять миграции словаря `record_types`
на каждый тип события. Если позже понадобится фильтрация по типу в Notion —
частые ключи повышаются до отдельного `record_type` миграцией (как описано в
`ARCHITECTURE.md`).

### Новая колонка для refresh

```sql
ALTER TABLE companies
  ADD COLUMN needs_refresh TIMESTAMPTZ;

CREATE INDEX idx_companies_needs_refresh
  ON companies (needs_refresh)
  WHERE needs_refresh IS NOT NULL;
```

`needs_refresh` — НЕ статус. Статус продолжает только повышаться. Флаг лишь
помечает, что у `dossier_ready`-компании появился сильный новостной сигнал и
досье надо инкрементально пересобрать.

---

## 8. Механика обновления

### Новая компания (discovery-путь)

1. NewsAgent резолвит домен, проверяет ICP-гейт.
2. `upsert companies (domain, name, website, icp_segment, status='discovered')`.
3. Пишет первичный `research_record` (`record_role='primary'`, source=новостной).
4. Дёргает Routine `/fire` с режимом `news_lead` для этого домена (см. §9).
5. Дальше — штатный пайплайн: RelevanceAgent квалифицирует, и т.д.

### Известная компания (monitoring-путь)

- **Мягкий сигнал** → пишем `research_record` (`record_role='monitor'`), статус
  и флаг не трогаем. Подхватится на следующем плановом анализе.
- **Сильный сигнал** → пишем `research_record` + ставим `needs_refresh = NOW()`.

### Refresh-ветка (инкрементальное обновление досье)

Отдельный проход (стадии analysis + conclusions, расширенная выборка):

```sql
-- AnalysisAgent (refresh): помимо обычной выборки sources_gathered
SELECT id, domain FROM companies
WHERE status = 'dossier_ready' AND needs_refresh IS NOT NULL;
```

1. AnalysisAgent пере-собирает только секции `news` и `financials` для этих
   компаний (инкрементально, не весь анализ).
2. ConclusionAgent обновляет соответствующие поля досье и `summary_md`.
3. Гасит флаг: `UPDATE companies SET needs_refresh = NULL WHERE domain = …`.

Так досье обновляется по свежей новости без нарушения правила «статус только
вверх».

---

## 9. Режим `news_lead`

Тонкий режим запуска для точечной адресации одной компании.

| Параметр | Значение |
|---|---|
| `mode` | `news_lead` |
| Стадии | `relevance → source_expansion → enrichment → analysis → conclusions` |
| Выборка | по конкретному `domain` (а не по сегменту) |
| Обязательные поля | `domain` |

Это `enrich_existing`, суженный до одной компании: discovery корректно
пропущена (NewsAgent уже сыграл её роль), RelevanceAgent остаётся гейтом.

Не-горячие `discovered`-компании, заведённые из новостей, подбирает обычный
плановый прогон `enrich_existing` — для них точечный `/fire` не нужен.

Реализация: добавить `ScenarioSpec` в `bot/scenarios.py` и значение режима в
`bot/config.py`; стадии берутся из иммутабельного порядка `VALID_STAGES`.

---

## 10. Расписание и уведомления

- **Расписание.** NewsAgent — отдельный scheduled Routine (по аналогии с
  `notion-sync-cron`), по умолчанию раз в день, с ротацией сегментов для
  соблюдения лимитов GDELT/RSS. Частота — параметр запуска.
- **Уведомления.** На сильный сигнал / горячий лид `notify.py` шлёт в Telegram
  карточку: `🔥 <компания> — <event_type> — суть — ссылка`. Переиспользуем
  существующий канал.

---

## 11. Изменения файлов

### Новые

| Файл | Назначение |
|---|---|
| `agents/prompts/news_task.md` | Промпт NewsAgent: роль, источники, таксономия, гейт, триггер, запись |
| `scripts/news.py` | Детерминированные резолверы (GDELT, Google News RSS, HN Algolia, RSS), нормализация, entity-resolution, запись `research_records`. По образцу `enrichment.py` |
| `config/news_sources.yaml` | Курируемый RSS-набор, сигнальные термы, per-segment запросы (правится человеком, как `icp.yaml`) |

### Правки

| Файл | Изменение |
|---|---|
| `config/sources.yaml` | включить `gdelt`; добавить `google_news`, `hn`, `news_rss` |
| `sql/` (миграция) | `companies.needs_refresh TIMESTAMPTZ` + частичный индекс |
| `agents/prompts/monitor_task.md` | сузить: убрать новости и funding-новости |
| `agents/prompts/analysis_task.md`, `analysis_section_task.md` | refresh-выборка по `needs_refresh`; инкрементальная пере-сборка `news`+`financials` |
| `agents/prompts/conclusions_task.md` | refresh-ветка: обновить поля досье и `summary_md`, погасить `needs_refresh` |
| `bot/scenarios.py`, `bot/config.py` | режим `news_lead` |
| `scripts/supabase_store.py` | хелперы set/clear `needs_refresh`; refresh-выборки |
| `ARCHITECTURE.md`, `docs/AGENT-ECOSYSTEM.md` | задокументировать NewsAgent и сужение MonitorAgent |

---

## 12. Проверка и eval

- **Юнит-тесты `news.py`:** моки ответов GDELT/RSS/HN; стабильность
  `dedupe_key`; entity-resolution (имя→домен); маппинг классификации сигналов.
- **`--dry-run`** как у прочих агентов (не пишет в Supabase, не дёргает `/fire`).
- **Мини-eval:** фикстуры реальных инфоповодов → ожидаемые
  `(company, event_type, signal_class)`. Метрики: precision/recall ICP-гейта и
  дедупа. Главный риск — ложный автозапуск пайплайна (false positive), поэтому
  целимся в высокий precision сильных сигналов.
- **Тест идемпотентности:** повторный прогон не плодит дублей `research_records`.
- **Safety:** в `dry_run` автозапуск `news_lead` запрещён.

---

## 13. Поэтапный выкат

Снижает риск автозапуска пайплайна на плохих лидах.

1. **Observe-only.** Только пишет сигналы существующим компаниям; без discovery
   и без авто-fire. Оцениваем качество сигналов и дедуп.
2. **Discovery без авто-fire.** Заводит `discovered`-компании из новостей;
   прогоняем вручную, проверяем, кого находит.
3. **Refresh-ветка.** Включаем `needs_refresh` + инкрементальное обновление
   досье.
4. **Авто-fire `news_lead`.** Для сильных гейтнутых лидов + сужение MonitorAgent
   + ежедневное расписание.

---

## 14. Открытые вопросы (на потом, вне MVP)

- Промотировать ли частые `event_type` из `payload` в отдельные `record_types`
  ради фильтрации в Notion.
- Нужен ли отдельный приоритет/скоринг горячести лида (сейчас бинарно:
  сильный/мягкий).
- Дополнительные отраслевые медиа под конкретные сегменты (medtech-порталы для
  medical-imaging и т.п.) — расширяется через `config/news_sources.yaml`.

---

## 15. Verification queries

```sql
-- Колонка needs_refresh существует
SELECT column_name FROM information_schema.columns
WHERE table_name = 'companies' AND column_name = 'needs_refresh';

-- Новостные наблюдения пишутся с таксономией в payload
SELECT source, payload->>'signal_class' AS class, payload->>'event_type' AS event, count(*)
FROM research_records
WHERE agent = 'news'
GROUP BY 1,2,3
ORDER BY count(*) DESC;

-- Компании, ожидающие refresh
SELECT domain, status, needs_refresh
FROM companies
WHERE needs_refresh IS NOT NULL
ORDER BY needs_refresh DESC;

-- Проверка дедупа: один инфоповод = одна строка
SELECT dedupe_key, count(*)
FROM research_records
WHERE agent = 'news'
GROUP BY dedupe_key
HAVING count(*) > 1;   -- ожидаем 0 строк
```
