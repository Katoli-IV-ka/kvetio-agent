# Site Research Agent — дизайн

Дата: 2026-06-23
Статус: design (одобрен пользователем по секциям, ожидает финального ревью)

## Цель

Добавить в `kvetio-agent` новую изолированную связку агентов, моделирующую
концепт «Агент разбора сайта» + «Агент проверки релевантности»:

- разобрать сайт компании и вытащить всю полезную информацию (контакты,
  руководители, сотрудники, продукт, пресс-релизы, партнёрства, финансирование,
  дата основания, страна);
- предварительно оценить релевантность компании; нерелевантные — не разбирать.

Связка работает **параллельно** существующему пайплайну
(`discovered → relevant → ...`, таблица `research_records`) и его не трогает.
Это отдельная модель данных со своими статусами и таблицами.

## Решения (зафиксированы с пользователем)

1. Проектируем как новую систему по модели со скриншотов (Companies/Contacts/
   Research_notes, статусы New/Site_researched), но размещаем внутри
   `kvetio-agent`, переиспользуя инфраструктуру (Supabase-клиент, notify,
   Notion-синк). Существующий пайплайн не меняем.
2. **Оркестрация:** один агент-оркестратор «разбор сайта», внутри которого
   вложенный под-шаг проверки релевантности. Один проход.
3. **Нерелевантные:** при отрицательной оценке — `status='not_relevant'` +
   `category`, парсинг сайта НЕ выполняется, в `contacts`/`research_notes`
   ничего не пишется. («Сразу заканчиваем обзор».)
4. **Релевантность управляется статусом, а не категорией.** Агент сам ставит
   статус; `site_researched`/`relevant` → продолжаем, `not_relevant` → стоп.
5. **Category** — отдельный текстовый столбец, ведёт себя как Notion `select`
   (расширяемый набор вариантов через справочник `category_options`), НЕ
   Postgres-enum. Релевантность из категории механически не выводится.
6. **Хранилище:** Postgres/Supabase — источник истины; Notion — витрина
   (через существующий notion-синк). Агент пишет в БД.
7. **Скрапинг:** `scripts/site_fetch.py` — тонкая обёртка над CLI
   `vercel-labs/agent-browser` для экономии токенов (accessibility-снапшот
   вместо сырого HTML), с fallback на httpx+BeautifulSoup.
8. **Идемпотентность:** upsert по уникальным ключам (не плодим дубли, копим
   историю).

## Архитектура

### Компоненты

- `agents/prompts/site_research_task.md` — SiteResearchAgent (оркестратор).
- `agents/prompts/relevance_check_task.md` — вложенный под-шаг оценки
  релевантности (отдельный промпт, тестируется/меняется независимо).
- `scripts/site_fetch.py` — скрапинг сайта (agent-browser CLI + fallback),
  возвращает компактный JSON. Промпты по HTTP сами не ходят.
- Запись в БД — через существующий `scripts/supabase_store.py`
  (+ `scripts/contacts_store.py` уже существует; расширяем при необходимости).
- Уведомления — существующий `scripts/notify.py`.

### Поток

```
new → [site_fetch.py] → reachable=false → not_relevant (стоп, причина в run_logs)
                       → reachable=true  → [relevance_check]
                                            → relevant=false → not_relevant + category (стоп)
                                            → relevant=true  → [extract → upsert] → site_researched + category
```

SiteResearchAgent для каждой компании со `status='new'`:

1. `site_fetch.py --domain <d> --json` — один скрап сайта.
2. Под-шаг релевантности на основе добытого контента → `{relevant, category}`.
3. Нерелевантна → `status='not_relevant'`, `category`, стоп.
4. Релевантна → разложить по сущностям:
   - контакты и внешние ссылки → `contacts`;
   - продукт/пресс-релизы/партнёрства/финансирование → `research_notes`
     (`note_type`);
   - год основания → `companies.founded_year` (int), страна →
     `companies.country`;
   - `status='site_researched'`, `category`.
5. `run_logs` + `notify.py`.

### Границы модулей

Промпты не знают про HTTP (скрапинг инкапсулирован в `site_fetch.py`). Вся
запись в БД — через store-скрипты. Релевантность изолирована в отдельном
промпте.

## Схема базы данных

Всё в существующей Supabase. Категория — текст + справочник (Notion-select),
не enum. Таблицу `research_records` существующего пайплайна НЕ трогаем —
`research_notes` это отдельная таблица нового пайплайна.

**Переиспользуем существующее (зафиксировано после сверки со схемой):**
- Таблица `contacts` уже существует (schema.sql, столбцы `contact_type`,
  `name`, `info`, `email`, `linkedin_url`, `x_url`, `facebook_url`,
  `instagram_url`, `other_channels JSONB`) и имеет готовый дедуплицирующий
  `upsert_contact(store, dict)` в `scripts/contacts_store.py`. Новую таблицу
  контактов НЕ создаём — пишем через `upsert_contact`.
- `companies.country TEXT` уже есть — переиспользуем для страны офиса.
- `companies.founded_year SMALLINT` уже есть — переиспользуем для года
  основания (парсим год из текста сайта в int). Новый столбец `founded` НЕ
  добавляем.

### companies (расширение — только новое)

- `status` — добавить значения `new`, `site_researched` к существующему набору
  (расширить CHECK-констрейнт `companies_status_check`).
- `category TEXT NULL` — значение из `category_options` (FK).
- `description`, `linkedin_url`, `country`, `founded_year` — уже есть,
  переиспользуем.

### category_options (справочник, Notion-select)

| колонка | тип | назначение |
|---|---|---|
| `value` | TEXT PK | `data_provider`, `product_builder`, `llm_wrapper`, `big_tech_ai`, `non_tech_product`, `startup_own_model`, `closed_project`, … |
| `label` | TEXT | человекочитаемое имя |
| `created_at` | timestamptz | |

Новая категория → INSERT сюда перед проставлением в `companies.category`.

### contacts (СУЩЕСТВУЕТ — не создаём)

Пишем через `scripts/contacts_store.py::upsert_contact(store, dict)`. Маппинг
извлечённых данных:
- человек → `{contact_type:"person", name, info=role, email?, linkedin_url?}`;
- внешние ссылки компании → передаём в соответствующие поля контакта-компании
  (`linkedin_url`, `x_url`, `facebook_url`, `instagram_url`) или в
  `other_channels` (github/huggingface/website) через `upsert_contact`, который
  сам нормализует каналы (`normalize_other_channels`);
- email компании → `{contact_type:"email", email}` либо в other_channels.

`upsert_contact` уже дедуплицирует по `(company_id, contact_type, name)` —
повторный запуск не плодит дубли.

### research_notes (новая)

| колонка | тип | назначение |
|---|---|---|
| `id` | uuid PK | |
| `company_id` | uuid FK → companies | |
| `note_type` | TEXT | `product`, `press_release`, `cooperative`, `finance` |
| `content` | TEXT | вытащенная информация |
| `content_hash` | TEXT | sha256(content) для уникальности |
| `source_url` | TEXT NULL | |
| `created_at` | timestamptz | |

`UNIQUE(company_id, note_type, content_hash)` — upsert без дублей.

## Интеграция agent-browser (`scripts/site_fetch.py`)

CLI `vercel-labs/agent-browser` (Rust + Chrome) отдаёт компактное
accessibility-дерево вместо сырого HTML — это и даёт экономию токенов, плюс
JS-рендеринг (SPA стартапов без JS пустые).

**Интерфейс:** `python scripts/site_fetch.py --domain acme.ai [--max-pages 5] [--json]`

**Логика:**

1. `agent-browser open https://<domain>`, fallback на `https://www.<domain>`.
   Демон сохраняется между командами (persistent daemon — быстрые повторные команды).
2. Главная: `agent-browser snapshot -i -c --urls --json` — структура + текст +
   ссылки.
3. Отбор приоритетных подстраниц по ключевым словам в href/тексте (`about`,
   `team`, `careers/jobs`, `blog/news/press`, `pricing`, `contact`) — до
   `--max-pages`; по каждой `snapshot -c`.
4. Извлечение внешних ссылок (linkedin/github/huggingface/twitter/facebook,
   `mailto:` email) из снапшотов.
5. `--max-output` + собственная обрезка, чтобы вывод не раздувал контекст.
6. **Fallback:** agent-browser отсутствует/упал → httpx+BeautifulSoup (в
   зависимостях), `engine: "fallback"`.

**Выход (JSON):**

```json
{
  "domain": "acme.ai",
  "engine": "agent-browser",
  "reachable": true,
  "pages": [{"url": "...", "title": "...", "text": "..."}],
  "external_links": [{"type": "linkedin", "url": "..."}],
  "emails": ["hello@acme.ai"]
}
```

**Конфиг/безопасность:** `--allowed-domains <domain>,*.<domain>` (скрап не
уходит на сторонние сайты); `--max-output` из конфига; idle-timeout демона.
Бинарь ставится отдельно (`npm i -g agent-browser && agent-browser install`) —
заметка в README и `.env.example`; в Python-зависимости не входит.

## Обработка ошибок и крайние случаи

- **Сайт недоступен** (оба варианта мертвы): `reachable:false` →
  `status='not_relevant'`, `category` пустой, причина в `run_logs.notes`
  (`dead_site:<domain>`). Релевантность вслепую не зовём.
- **agent-browser упал И fallback пустой:** компания остаётся `new`, ошибка в
  `run_logs.errors`. Технический сбой ≠ not_relevant.
- **Релевантность неоднозначна:** `relevant=false` только при явном
  несоответствии; при споре/нехватке данных — `relevant=true` с
  категорией-кандидатом (отсев необратим, не отсеиваем зря).
- **Частичное извлечение:** релевантна, но контактов нет → пишем что есть,
  `status='site_researched'`. Отсутствие контактов ≠ ошибка.
- **Идемпотентность:** upsert по уникальным ключам; `site_researched`
  исключает из выборки `WHERE status='new'`.
- **Новая категория:** INSERT в `category_options` перед проставлением (без FK-
  падения).
- **Лимиты:** `batch_size` (по умолч. 5) компаний/запуск, `--max-pages`
  (по умолч. 5)/компания, таймаут на компанию.

## Тестирование

**Юнит `site_fetch.py`** (мок subprocess):
- парсинг JSON-снапшота → pages/external_links/emails;
- классификация ссылок по типам;
- отбор приоритетных подстраниц;
- fallback-ветка (`engine:"fallback"`);
- `reachable:false` при обоих недоступных вариантах.

**Юнит записи в БД** (мок Supabase):
- upsert контакта без дубля по `(company_id, contact_type, value)`;
- upsert заметки по `content_hash`;
- новая категория → INSERT в `category_options` перед проставлением;
- not_relevant-ветка не пишет contacts/research_notes.

**Логика статусов:**
- `new → not_relevant` при недоступном сайте (контент не пишется);
- `new → site_researched` при релевантной;
- технический сбой → статус остаётся `new`, ошибка в `run_logs`.

**Миграция:** SQL в `sql/migrations/` (таблицы + столбцы + справочник);
проверка применения на чистой схеме и отсутствия конфликта с `research_records`.

**Smoke (ручной, опц.):** реальный домен через `site_fetch.py --json` — глазами
проверить компактность вывода и извлечение ссылок.

**Верификация перед завершением:** `pytest -q`, `ruff`, применение миграции на
тестовой БД.

## После реализации

Обновить `ARCHITECTURE.md` (раздел агентов, схема БД, новые статусы) — как
требует `CLAUDE.md`.
