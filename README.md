# kvetio-agent

Рабочий Python-проект Kvetio. Скрипты, которые вызывают агенты Claude, чтобы собирать и квалифицировать компании-кандидаты в покупатели данных.

Полная архитектура и бизнес-контекст — в репозитории [kvetio](https://github.com/Katoli-IV-ka/kvetio) (`docs/context/`).

## Принцип работы

- **Промпты в `agents/prompts/*.md`** определяют, что делает каждый агент (research, collection, verify, scoring, monitor, source_expansion).
- **Python-скрипты в `scripts/`** — детерминированный слой, который агенты вызывают через `Bash`. Это **источник истины** для рабочего кода. Никакой параллельной упаковки в Python-пакет нет.
- **Supabase** — единое runtime-хранилище (`companies`, `signals`, `run_logs`). Схема — в `sql/`.
- **Notion** — рабочий интерфейс для ручного аутрича. Синхронизация — отдельный шаг pipeline.

## Быстрый старт

```bash
# 1. Окружение
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Конфигурация
cp .env.example .env
# заполнить: SUPABASE_URL, SUPABASE_KEY, NOTION_TOKEN, NOTION_COMPANIES_DB_ID,
#            ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# 3. Применить миграции Supabase (выполнить SQL из sql/ в порядке номеров)

# 4. Sanity check
pytest
```

## Раскладка

```
kvetio-agent/
├── pyproject.toml             # конфиг ruff/pytest
├── requirements.txt           # runtime + dev зависимости
├── .env.example               # шаблон секретов
├── agents/
│   ├── context/icp_summary.md # короткий справочник ICP для агентов
│   └── prompts/               # один промпт = одна агентская задача
│       ├── research_task.md
│       ├── collection_task.md
│       ├── discovery_task.md      # этап 1: источники + резолв сайта → discovered
│       ├── relevance_task.md      # этап 2: анализ сайта + верификация → relevant
│       ├── discover_verify_task.md  # УСТАРЕЛ (заменён на discovery + relevance)
│       ├── verify_task.md
│       ├── scoring_task.md       # этап 2.5: триаж-гейт, скор + qualified/triaged_out (Notion-синк → этап 5)
│       ├── enrichment_task.md    # этап 3: сбор ручек-источников (sources_gathered)
│       ├── analysis_task.md      # этап 4: оркестратор анализа → analyzed
│       ├── analysis_section_task.md  # этап 4: секционный под-агент (company/product/...)
│       ├── analysis_audit_task.md    # этап 4: под-агент аудита (синтез 5 нот)
│       ├── conclusions_task.md   # этап 5: сборка досье + Notion → dossier_ready
│       ├── monitor_task.md
│       └── source_expansion_task.md
├── config/
│   ├── icp.yaml               # сегменты ICP (Stage 0)
│   ├── scoring.yaml           # веса score (Stage 2)
│   ├── sources.yaml           # registry источников и их настроек
│   └── notion_mapping.yaml    # декларативный маппинг полей БД → Notion
├── data/
│   └── known_ats_slugs.csv    # ручной seed-list slug → company
├── scripts/                   # ★ канонические скрипты — то, что вызывают агенты
│   ├── models.py              # доменные типы (RawSignal, Company, Evidence, …)
│   ├── normalize.py           # normalize_domain, fuzzy company match
│   ├── http_client.py         # rate-limited HTTP с retries
│   ├── greenhouse.py          # источник: Greenhouse Job Board
│   ├── github.py              # источник: GitHub Code Search по org train.py
│   ├── org_cache.py           # Supabase TTL-кэш GitHub org metadata
│   ├── lever.py               # источник: Lever
│   ├── huggingface.py         # источник: HuggingFace orgs/models
│   ├── yc_browser.py          # источник: Y Combinator company browser
│   ├── supabase_store.py      # CRUD над Supabase + дедуп + покрытие
│   ├── score.py               # детерминированный scoring engine
│   ├── notify.py              # уведомления в Telegram
│   ├── enrichment.py          # этап 3: резолверы ссылок-источников → source_links
│   ├── dossier_store.py       # CRUD: source_links, analysis_notes, dossiers (этапы 3-5)
│   ├── notion_sync.py         # синк Supabase ↔ Notion (config-driven)
│   └── telegram_routines.py   # операционные Telegram-дайджесты и очереди
├── sql/                       # миграции Postgres/Supabase
│   ├── 001_init.sql
│   ├── 002_github_org_cache.sql
│   ├── 003_source_page_url.sql
│   ├── 004_signals_source_page_url.sql
│   └── 008_source_links.sql, 009_analysis_notes.sql, 010_dossiers.sql  # данные досье
└── tests/
    ├── conftest.py
    ├── fixtures/
    ├── test_normalize.py
    ├── test_scoring.py
    ├── test_greenhouse.py
    ├── test_github.py
    ├── test_huggingface.py
    ├── test_yc_browser.py
    └── test_dedup.py
```

## Как агент использует скрипты

Каждый промпт в `agents/prompts/` описывает задачу и явно перечисляет команды:

```bash
# Пример из collection_task.md
python scripts/yc_browser.py --segment medical-imaging --limit 100
python scripts/supabase_store.py --coverage
python scripts/notify.py --run-summary '{"task":"collection_task", ...}'
```

Скрипты пишут в stdout JSON-совместимый вывод и читают stdin/аргументы. Никаких импортов между скриптами в обход явных API — каждый скрипт самодостаточен.

## Telegram routines

`scripts/telegram_routines.py` собирает операционные сообщения из Supabase и отправляет их через существующий Telegram Bot API слой.

```bash
# Проверить текст и payload без отправки в Telegram
python scripts/telegram_routines.py daily_digest --dry-run
python scripts/telegram_routines.py hot_leads --limit 5 --dry-run
python scripts/telegram_routines.py stale_review --days 30 --limit 10 --dry-run

# Отправить в Telegram-чат из TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID
python scripts/telegram_routines.py daily_digest
python scripts/telegram_routines.py hot_leads --limit 5
python scripts/telegram_routines.py stale_review --days 30 --limit 10
```

Доступные routines:
- `daily_digest` — total/by-status статистика и покрытие по ICP-сегментам.
- `hot_leads` — enriched + Hot компании, отсортированные по score.
- `stale_review` — компании без проверки или с устаревшим `last_verified`.

## Telegram Management Bot

`bot/` — Telegram-бот для управления pipeline-агентом. Поддерживает ручной запуск pipeline через inline-кнопки, уведомления о результатах, историю ранов и пресеты.

### Компоненты

| Файл | Ответственность |
|---|---|
| `bot/gateway.py` | FastAPI: webhook, команды, allowlist, `/runs`, `/healthz` |
| `bot/dialog.py` | Мастер `/run` на inline-кнопках, состояние в `bot_dialog_state` |
| `bot/runs.py` | `RunConfig`, CRUD `pipeline_runs`, status-машина, concurrency lock |
| `bot/worker.py` | Поллер очереди, триггер агента, heartbeat, сбор Summary |
| `bot/access.py` | Allowlist + роли (`admin`/`viewer`) из `bot_users` |
| `bot/presets.py` | Именованные пресеты `RunConfig`, `/quickrun`, default |
| `bot/set_webhook.py` | Идемпотентный `setWebhook` при деплое |
| `sql/012_bot.sql` | Миграция: `pipeline_runs`, `bot_users`, `bot_presets`, `bot_dialog_state` |

### Команды

| Команда | Роль | Назначение |
|---|---|---|
| `/run` | admin | Мастер запуска (inline-кнопки: сегменты → лимит → стадии → флаги → подтверждение) |
| `/quickrun [preset]` | admin | Быстрый запуск по пресету |
| `/status` | all | Текущий активный ран |
| `/cancel` | admin | Отменить очередной/активный ран |
| `/last [n]` | all | История последних n ранов |
| `/presets` | all | Список пресетов; `save`/`delete` для admin |
| `/digest`, `/hot`, `/stale` | all | Дайджест, Hot-лиды, очередь проверки |
| `/whoami`, `/help`, `/ping` | all | Инфо, справка, health-check |

### Переменные окружения (Railway)

```
TELEGRAM_BOT_TOKEN          — токен бота от @BotFather
TELEGRAM_WEBHOOK_SECRET     — секрет для X-Telegram-Bot-Api-Secret-Token
INTERNAL_API_TOKEN          — Bearer-токен для POST /runs (bot ↔ worker)
BOT_WEBHOOK_URL             — https://<app>.up.railway.app/telegram/webhook
SUPABASE_URL / SUPABASE_KEY
ANTHROPIC_API_KEY
```

### Деплой на Railway

```bash
# После деплоя — выставить webhook (идемпотентно)
python -m bot.set_webhook

# Применить миграцию БД
# Выполнить sql/012_bot.sql в Supabase SQL Editor
```

`railway.toml` описывает два сервиса: `web` (FastAPI) и `worker` (поллер очереди).

## Текущий статус

- ✅ Greenhouse, GitHub, HuggingFace, YC Browser — рабочие источники.
- ✅ Supabase — единый runtime store, дедупликация (exact + fuzzy) реализована.
- ✅ Scoring — детерминированная функция от Company → ScoreBreakdown.
- ✅ Telegram-уведомления.
- ✅ Telegram routines для ежедневных дайджестов и review-очередей.
- ✅ Notion sync — детерминированный `scripts/notion_sync.py` + конфиг
  `config/notion_mapping.yaml`. БД — источник истины; Notion — курируемая витрина
  (forward), reverse-синк whitelist ручных полей. Поля настраиваются правкой YAML
  + `--ensure-schema`.

## Принципы

1. **Скрипт = pure CLI.** Вход через args/stdin, выход через stdout JSON. Никаких скрытых side-effect-ов кроме явно заявленных (запись в Supabase, отправка в Telegram).
2. **Scoring = pure function.** Тестируется табличными тестами на фикстурах.
3. **Supabase = source of truth** для runtime-данных. SQLite/файлы не используются.
4. **Идемпотентность.** Повторный запуск с тем же входом не порождает дубликатов.
5. **Evidence обязателен.** Без `evidence_url` и `signal_date` сигнал невалиден.
