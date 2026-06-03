# Discover & Verify Task — Поиск, анализ сайта и верификация

## Роль
Ты выполняешь роль DiscoverVerifyAgent. За один запуск ты:
1. Находишь компании из источников
2. Получаешь сайт каждой компании
3. Анализируешь сайт и проверяешь релевантность
4. Записываешь результат в Supabase

Компании выходят из этого агента со статусом `pending_enrich` (прошли) или
`not_relevant` (отклонены). Промежуточный статус `new` не используется.

**Следующий этап после этого агента:** `scoring_task`

---

## Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---|---|
| `segment` | обязательный | ICP-сегмент из `config/icp.yaml` |
| `limit` | 30 | Максимум компаний на источник |
| `sources` | auto | Список источников через запятую; если не указан — из `config/sources.yaml` |
| `batch_size` | 5 | Компаний за одну итерацию верификации |

---

## ФАЗА 1: Сбор

### Шаг 1 — Покрытие до запуска

```bash
python scripts/supabase_store.py --coverage
```

Выведи таблицу: сколько компаний по каждому сегменту и статусу.

---

### Шаг 2 — Выбрать источники

Открой `config/sources.yaml`. Выбери все источники где:
- `enabled: true`
- `supported_segments` содержит текущий `segment` (или поле отсутствует)

Команды запуска:

| Источник | Команда |
|---|---|
| `huggingface` | `python scripts/huggingface.py --segment <segment> --max-models 1000` |
| `yc_browser` | `python scripts/yc_browser.py --segment <segment> --limit <limit>` |
| `greenhouse` | `python scripts/greenhouse.py --segment <segment>` |

Порядок: huggingface → yc_browser → greenhouse.

Сообщи какие источники выбраны и почему, прежде чем запускать.

---

### Шаг 3 — Запустить источники

Запускай по очереди. Каждый скрипт выводит JSON в stdout.

Если источник вернул 0 компаний — зафиксируй и продолжай следующий.

---

### Шаг 4 — Объединить и дедуплицировать

**4a. Дедупликация внутри сессии** — по нормализованному домену. Если одна компания
пришла из HuggingFace и YC одновременно — оставляй одну запись,
в `sources` пиши оба: `["huggingface", "yc_browser"]`.

**4b. Дедупликация против базы:**
```sql
SELECT domain, status FROM companies
WHERE domain = '<normalized_domain>';
```
Если уже есть — пропускать.

После объединения выведи:
```
huggingface: N | yc_browser: M | greenhouse: K
Дублей в сессии: X | Уже в базе: Y
→ Для проверки: Z компаний
```

---

### Шаг 5 — Preview

Выведи первые 10 компаний из списка и дождись подтверждения:

```
Сегмент: <segment> | Источники: huggingface, yc_browser
Новых для проверки: Z

Топ-10:
1. Acme Medical AI — acme.ai (huggingface, 8 моделей)
2. RadarBot — radarbot.io (yc_browser, batch W24)
...

Запустить верификацию? [yes/no]
```

---

## ФАЗА 2: Анализ и верификация

Обрабатывай компании **батчами по `batch_size`** (по умолчанию 5). После каждого
батча кратко выводи промежуточный результат.

Для каждой компании выполняй шаги 6–9.

---

### Шаг 6 — Получить сайт

Надёжность домена зависит от источника:

| Источник | Домен в данных | Действие |
|---|---|---|
| `yc_browser` | Всегда есть | Используй напрямую |
| `huggingface` | Иногда `null` | Если `null` → WebSearch (ниже) |
| `greenhouse` | Из CSV-колонки `website` | Если пусто → WebSearch (ниже) |

**Fallback если домен отсутствует:**
```
WebSearch: "<company name>" official website
```
Бери первый явный домен компании (не LinkedIn, не Crunchbase).
Если не нашёл — пометь `domain_status: not_found` и пропускай (не записывай без домена).

---

### Шаг 7 — Быстрый анализ сайта (Quick Filter)

```
WebFetch: https://<domain>
```

Если недоступен → попробуй `https://www.<domain>`.

Задаёшь себе один вопрос:
> «Эта компания разрабатывает собственные AI/ML модели, а не просто использует чужие?»

**Пропускаем дальше если есть хотя бы один сигнал:**
- Упоминание обучения моделей, датасетов, fine-tuning
- "we train / our model / custom AI / proprietary model"
- Продукт явно в ML-домене (medical imaging, speech, autonomous systems)
- Вакансии ML/AI на карьерной странице

**Сразу отклоняем (`quick_reject`):**
| Причина | `reject_reason` |
|---|---|
| Parked domain, "domain for sale", страница-заглушка | `dead_website` |
| Явный SaaS без ML под капотом | `no_ai_dev` |
| "Powered by ChatGPT/OpenAI" как главный messaging | `api_wrapper` |
| Датасет-провайдер / аннотационный сервис | `competitor` |
| Крупная корпорация (Google, Meta, Apple, etc.) | `too_large` |

**Если за Cloudflare / капча — не блокирует:** пометь `site_note: behind_protection`
и переходи к шагу 8 без контента сайта.

---

### Шаг 8 — Глубокая верификация (только для прошедших Quick Filter)

Выполняй только для компаний, не попавших в `quick_reject`.

#### 8a. HuggingFace
Используй HuggingFace MCP (`hf_hub_query` или `hub_repo_search`):
```
Ищи организацию по имени компании или домену
```
Записывай: количество моделей, pipeline_tags, дата последней активности.

#### 8b. Вакансии
```
WebSearch: "<company name>" jobs "ML engineer" OR "data annotation" OR "training data"
```
Достаточно найти один релевантный job posting. Записывай title + URL.

#### 8c. Сбор фактуры

| Поле | Метод |
|---|---|
| `description` (2-3 предложения) | Из сайта / HF профиля |
| `linkedin_url` | WebSearch: `site:linkedin.com/company "<name>"` |
| `team_size` | LinkedIn / сайт |
| `funding_stage` | WebSearch: `"<name>" funding round OR raised` |
| `funding_date` | Там же |

Не обязательно заполнять всё — записывай что нашёл.

---

### Шаг 9 — Решение

**→ `pending_enrich`** если:
- Прошёл Quick Filter (шаг 7)
- Есть хотя бы одно конкретное доказательство из шага 8: HF-модели, релевантная
  вакансия, или описание продукта явно подтверждает собственную ML-разработку

**→ `not_relevant`** если:
- `quick_reject` (любая причина из шага 7)
- Прошёл Quick Filter, но в шаге 8 не нашлось ни одного подтверждения

**→ `manual_review`** если:
- Признаки есть, но данных мало (stealth-стартап, закрытый сайт)
- Неоднозначная ситуация, где нужен человек

---

## ФАЗА 3: Запись

### Шаг 10 — Записать компании в Supabase

**Прошедшие (`pending_enrich`):**
```sql
INSERT INTO companies (
  domain, name, website, status, icp_segment,
  sources, source_page_url, description,
  linkedin_url, team_size, funding_stage, funding_date,
  reject_reason, site_note, last_verified, updated_at
)
VALUES (
  '<domain>',
  '<name>',
  'https://<domain>',
  'pending_enrich',
  '<segment>',
  '<["huggingface","yc_browser"]>',   -- JSON-массив источников
  '<url страницы в первичном источнике>',
  '<description>',
  '<linkedin_url или NULL>',
  '<team_size или NULL>',
  '<funding_stage или NULL>',
  '<funding_date или NULL>',
  NULL,                                -- reject_reason пустой
  '<site_note или NULL>',
  CURRENT_DATE,
  NOW()
)
ON CONFLICT (domain) DO NOTHING;
```

**Отклонённые (`not_relevant`):**
```sql
INSERT INTO companies (
  domain, name, website, status, icp_segment,
  sources, source_page_url, reject_reason, last_verified, updated_at
)
VALUES (
  '<domain>', '<name>', 'https://<domain>',
  'not_relevant', '<segment>',
  '<sources>', '<source_page_url>',
  '<reject_reason>',
  CURRENT_DATE, NOW()
)
ON CONFLICT (domain) DO NOTHING;
```

**На ручной просмотр (`manual_review`):**
То же что `pending_enrich`, но `status = 'manual_review'` и `site_note` объясняет причину.

---

### Шаг 11 — Записать сигналы в `signals`

Для каждой компании со статусом `pending_enrich` запиши найденные сигналы:

```sql
INSERT INTO signals (
  source, signal_type, company_name, normalized_domain,
  evidence_url, signal_date, confidence, raw_data
)
VALUES (
  '<source>',
  '<hf_org | job_posting | yc_company>',
  '<company_name>',
  '<domain>',
  '<evidence_url>',
  '<signal_date>',
  'high',
  '<{...json...}>'
)
ON CONFLICT (evidence_url) DO NOTHING;
```

---

### Шаг 12 — run_log и уведомление

```sql
INSERT INTO run_logs (task_name, companies_found, companies_enriched, errors, notes)
VALUES (
  'discover_verify_task',
  <всего_из_источников>,
  <записано_pending_enrich>,
  '[]',
  'not_relevant: <N>, manual_review: <M>, no_domain: <K>'
);
```

```bash
python scripts/notify.py --run-summary '{
  "task": "discover_verify_task",
  "segment": "<segment>",
  "sources": ["huggingface", "yc_browser"],
  "discovered": <из_источников>,
  "dedup_skipped": <дублей>,
  "pending_enrich": <прошло>,
  "not_relevant": <отклонено>,
  "manual_review": <на_просмотр>
}'
```

Выведи покрытие после запуска:
```bash
python scripts/supabase_store.py --coverage
```

---

## Граничные случаи

**Домен не найден:** не записывать компанию. Логировать как `no_domain`.

**Supabase недоступен:** прервать с чёткой ошибкой.

**Пользователь ответил `no` на preview:** предложить изменить параметры.

**Крупный список (>50 компаний):** Quick Filter работает быстро, но глубокую верификацию
(шаг 8) можно пропустить для obvious-pass компаний (например, HF-организации с 10+
моделями в нужном домене). В таком случае сразу пишем `pending_enrich` без шага 8.

---

## Итоговая схема статусов

```
[Источники] → discovered
     ↓
[Дедупликация] → уже в базе: пропустить
     ↓
[Quick Filter]
     ├── quick_reject → not_relevant
     └── pass
          ↓
     [Глубокая верификация]
          ├── confirmed → pending_enrich → [scoring_task]
          ├── not_confirmed → not_relevant
          └── unclear → manual_review
```
