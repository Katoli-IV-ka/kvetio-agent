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
│       ├── verify_task.md
│       ├── scoring_task.md
│       ├── monitor_task.md
│       └── source_expansion_task.md
├── config/
│   ├── icp.yaml               # сегменты ICP (Stage 0)
│   ├── scoring.yaml           # веса score (Stage 2)
│   └── sources.yaml           # registry источников и их настроек
├── data/
│   └── known_ats_slugs.csv    # ручной seed-list slug → company
├── scripts/                   # ★ канонические скрипты — то, что вызывают агенты
│   ├── models.py              # доменные типы (RawSignal, Company, Evidence, …)
│   ├── normalize.py           # normalize_domain, fuzzy company match
│   ├── http_client.py         # rate-limited HTTP с retries
│   ├── greenhouse.py          # источник: Greenhouse Job Board
│   ├── lever.py               # источник: Lever
│   ├── huggingface.py         # источник: HuggingFace orgs/models
│   ├── yc_browser.py          # источник: Y Combinator company browser
│   ├── supabase_store.py      # CRUD над Supabase + дедуп + покрытие
│   ├── score.py               # детерминированный scoring engine
│   └── notify.py              # уведомления в Telegram
├── sql/                       # миграции Postgres/Supabase
│   ├── 001_init.sql
│   ├── 002_github_org_cache.sql
│   ├── 003_source_page_url.sql
│   └── 004_signals_source_page_url.sql
└── tests/
    ├── conftest.py
    ├── fixtures/
    ├── test_normalize.py
    ├── test_scoring.py
    ├── test_greenhouse.py
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

## Текущий статус

- ✅ Greenhouse, HuggingFace, YC Browser — рабочие источники.
- ✅ Supabase — единый runtime store, дедупликация (exact + fuzzy) реализована.
- ✅ Scoring — детерминированная функция от Company → ScoreBreakdown.
- ✅ Telegram-уведомления.
- ⏳ GitHub — текущий план в репозитории [kvetio](https://github.com/Katoli-IV-ka/kvetio) (`docs/superpowers/plans/`).
- ⏳ Notion sync — каркас, нужна сверка полей с боевой базой.

## Принципы

1. **Скрипт = pure CLI.** Вход через args/stdin, выход через stdout JSON. Никаких скрытых side-effect-ов кроме явно заявленных (запись в Supabase, отправка в Telegram).
2. **Scoring = pure function.** Тестируется табличными тестами на фикстурах.
3. **Supabase = source of truth** для runtime-данных. SQLite/файлы не используются.
4. **Идемпотентность.** Повторный запуск с тем же входом не порождает дубликатов.
5. **Evidence обязателен.** Без `evidence_url` и `signal_date` сигнал невалиден.
