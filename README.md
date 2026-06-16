# kvetio-agent

Pipeline лидогенерации Kvetio: агент Claude собирает и квалифицирует компании —
кандидаты в покупатели данных. Запускается как **Claude Code Routine** в облаке
Anthropic (по подписке, без Anthropic API), детерминированную работу выполняют
Python-скрипты, данные живут в Supabase, витрина — Notion, управление и
уведомления — Telegram.

> Статус документа: целевая архитектура на **Claude Code Routines**. Часть кода в
> репозитории ещё относится к старой схеме (worker + очередь + `claude -p` по API).
> Что и как мигрировать — см. [docs/RUNBOOK.md](docs/RUNBOOK.md).

---

## Как это работает

```
                         ┌──────────────────────────────────────────┐
   Telegram (ты)         │     Claude Code Routine (облако Anthropic) │
        │                │     bootstrap = pipeline_task.md             │
        │                │     main prompt = pipeline_main_task.md      │
        │ /run, /quickrun │     репо = kvetio-agent (клонируется)      │
        ▼                │     env = секреты + network + setup script │
  bot/gateway.py  ──POST /fire──►  агент по шагам зовёт scripts/*.py   │
  (Railway, web)         │              │                              │
        ▲                │              ▼                              │
        │                │   Supabase (companies, signals, run_logs)  │
        │                │   Notion (витрина) · источники (GH/HF/YC)  │
        │                │              │                              │
        └──── Telegram ◄──── scripts/notify.py (последний шаг рутины) │
                         └──────────────────────────────────────────┘
        ▲
        │ Schedule-триггер (ежедневно) запускает ту же рутину сам
```

Три факта, которые определяют всю схему:

1. **Рутина крутится в облаке Anthropic** и расходует подписку (Pro/Max/Team), а не
   API-ключ. Ноутбук может быть выключен.
2. **`/fire` — fire-and-forget.** POST на endpoint рутины возвращает только
   `session_id`; callback о завершении не приходит. Поэтому уведомление о
   результате шлёт **сама рутина последним шагом** (`scripts/notify.py`), а не
   внешний процесс.
3. **Бот ничего не исполняет.** `bot/gateway.py` только принимает команды,
   собирает параметры запуска и дёргает `/fire`. Очереди и поллера (`worker`) в
   этой модели нет.

### Два триггера на одну рутину

- **Schedule** — ежедневный автозапуск (настраивается в claude.ai/code, мин. интервал 1 час).
- **API (`/fire`)** — ручной запуск: Telegram-бот POST-ит на endpoint, опционально
  передавая в поле `text` параметры (сегменты, лимит) поверх сохранённого промпта.

---

## Раскладка репозитория

```
kvetio-agent/
├── agents/
│   ├── context/icp_summary.md     # короткий справочник ICP для агента
│   └── prompts/                   # один промпт = одна задача агента
│       ├── pipeline_task.md       # ★ стабильный bootstrap-промпт рутины
│       ├── pipeline_main_task.md  # основной repo-managed prompt полного pipeline
│       ├── discovery_task.md      # этап 1: источники + резолв сайта → discovered
│       ├── relevance_task.md      # этап 2: анализ сайта + верификация → relevant
│       ├── scoring_task.md        # этап 2.5: триаж-гейт → qualified/triaged_out
│       ├── enrichment_task.md     # этап 3: сбор ссылок-источников → sources_gathered
│       ├── dm_enrich_task.md      # этап 3: обогащение контактов (decision makers)
│       ├── analysis_task.md       # этап 4: оркестратор анализа → analyzed
│       ├── analysis_section_task.md / analysis_audit_task.md  # под-агенты этапа 4
│       ├── conclusions_task.md    # этап 5: сборка досье + Notion → dossier_ready
│       ├── monitor_task.md        # мониторинг изменений
│       ├── research_task.md / collection_task.md / verify_task.md / source_expansion_task.md
│       └── discover_verify_task.md  # УСТАРЕЛ (заменён discovery + relevance)
├── config/
│   ├── icp.yaml                   # сегменты ICP (Stage 0)
│   ├── scoring.yaml               # веса score (Stage 2)
│   ├── sources.yaml               # registry источников
│   └── notion_mapping.yaml        # маппинг полей БД → Notion
├── data/known_ats_slugs.csv       # ручной seed-list slug → company
├── scripts/                       # ★ канонические CLI-скрипты — то, что зовёт агент
│   ├── models.py · normalize.py · http_client.py   # ядро
│   ├── greenhouse.py · lever.py · github.py · huggingface.py · yc_browser.py  # источники
│   ├── supabase_store.py          # CRUD над Supabase + дедуп + покрытие + run_logs
│   ├── score.py                   # детерминированный scoring engine
│   ├── enrichment.py · dossier_store.py            # этапы 3–5
│   ├── contact_enricher.py · contacts_store.py · dm_*.py  # контакты / decision makers
│   ├── notion_sync.py             # синк Supabase ↔ Notion (config-driven, не MCP)
│   ├── notify.py                  # уведомления в Telegram (финальный шаг рутины)
│   └── telegram_routines.py       # дайджесты/очереди (daily_digest, hot_leads, stale_review)
├── bot/                           # Telegram-бот-триггер (хостится на Railway)
│   ├── gateway.py                 # FastAPI: webhook, команды, POST /fire
│   ├── dialog.py                  # stateless-мастер /run на callback_data
│   ├── presets.py · preset_args.py # пресеты параметров запуска
│   └── set_webhook.py             # идемпотентный setWebhook при деплое
├── sql/                           # миграции Supabase (применять по номерам)
├── tests/                         # pytest: источники, скоринг, дедуп, синк, бот
├── railway.toml                   # сервис web (бот-триггер)
└── requirements.txt
```

Источник истины: код — это `scripts/`; данные — Supabase; промпты — `agents/prompts/`.

---

## Настройка рутины (claude.ai/code)

1. Открыть [claude.ai/code/routines](https://claude.ai/code/routines) → **New routine**.
2. **Промпт** — содержимое `agents/prompts/pipeline_task.md`. Это стабильный
   bootstrap-промпт: при каждом запуске он читает основной prompt из
   `agents/prompts/pipeline_main_task.md` в свежем checkout репозитория и следует ему.
   Поэтому дальнейшие изменения логики pipeline делаются в Git, а не в UI рутины.
3. **Репозиторий** — `kvetio-agent` (клонируется при каждом запуске; ветка по умолчанию).
4. **Environment** (см. таблицу секретов ниже):
   - **Network access** — уровень с выходом к Supabase, Notion, Telegram и источникам
     (Greenhouse, GitHub, HuggingFace, YC).
   - **Environment variables** — все секреты из таблицы.
   - **Setup script** — `pip install -r requirements.txt` (результат кэшируется).
5. **Триггеры**: добавить **Schedule** (ежедневно) и **API**. После сохранения у
   API-триггера сгенерировать токен — он показывается один раз, сохранить в секреты бота.
6. **Коннекторы** — отключить все, что рутине не нужно.

Ручной разовый прогон — кнопка **Run now** на странице рутины.

### Запуск рутины через `/fire`

```bash
curl -X POST https://api.anthropic.com/v1/claude_code/routines/<ROUTINE_ID>/fire \
  -H "Authorization: Bearer <ROUTINE_TOKEN>" \
  -H "anthropic-beta: experimental-cc-routine-2026-04-01" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"text": "segments=medical-imaging,robotics-ai; limit=5"}'
```

Поле `text` — строка параметров запуска поверх сохранённого bootstrap-промпта.
Основной prompt принимает `segments`, `limit`/`limit_per_segment`, `stages`,
`dry_run`, `notion_sync`. Default `limit` — 5 компаний на сегмент. Именно этот
POST делает Telegram-бот по команде `/run`/`/quickrun`.

---

## Telegram-бот-триггер (Railway)

Бот только принимает команды и дёргает `/fire`. Деплоится отдельным сервисом на Railway.

```bash
# Локальная отладка команд:
uvicorn bot.gateway:app --host 0.0.0.0 --port 8000
curl localhost:8000/healthz

# После деплоя — выставить Telegram webhook (идемпотентно):
python -m bot.set_webhook
```

Команды:

| Команда | Назначение |
|---|---|
| `/start` | Объясняет назначение бота и схему запуска routine |
| `/run` | Stateless-мастер запуска на кнопках, собирает параметры → POST `/fire` |
| `/quickrun [preset]` | Быстрый запуск default или named-пресета из `bot_presets` → POST `/fire` |
| `/presets` | Список, сохранение, default-настройка и удаление пресетов |
| `/status`, `/last [n]` | Состояние/история из `run_logs` (пишутся скриптами внутри рутины) |
| `/digest`, `/hot`, `/stale` | Дайджест, Hot-лиды, очередь проверки (чтение из Supabase) |
| `/whoami`, `/help`, `/ping` | Инфо, справка, health-check |

---

## Секреты

В новой схеме секреты живут в **двух местах**:

| Переменная | В Environment рутины | В Railway (бот) | Зачем |
|---|:--:|:--:|---|
| `SUPABASE_URL`, `SUPABASE_KEY` | ✅ | ✅ | хранилище (рутина пишет; бот читает для дайджестов) |
| `NOTION_TOKEN`, `NOTION_COMPANIES_DB_ID`, `NOTION_CONTACTS_DB_ID` | ✅ | — | синк-витрина |
| `GITHUB_TOKEN`, `HF_TOKEN` | ✅ | — | источники сигналов |
| `TELEGRAM_BOT_TOKEN` | ✅ | ✅ | рутина шлёт уведомления; бот отвечает на команды |
| `TELEGRAM_CHAT_ID` | ✅ | — | куда рутина шлёт сводку |
| `ROUTINE_FIRE_URL`, `ROUTINE_TOKEN` | — | ✅ | бот дёргает `/fire` рутины |
| `TELEGRAM_WEBHOOK_SECRET`, `BOT_WEBHOOK_URL` | — | ✅ | приём webhook от Telegram |

`ANTHROPIC_API_KEY` и `INTERNAL_API_TOKEN` в новой схеме **не нужны** (API-запуска и
внутренней очереди больше нет).

---

## Локальная разработка и тесты

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # заполнить для локального прогона скриптов/бота
pytest                      # источники, скоринг, дедуп, синк, бот
ruff check .
```

Отдельные скрипты можно гонять напрямую — это полезно для отладки этапов:

```bash
python scripts/supabase_store.py --coverage
python scripts/yc_browser.py --segment medical-imaging --limit 100
python scripts/notion_sync.py --entity companies --all
python scripts/telegram_routines.py daily_digest --dry-run
```

---

## Принципы

1. **Скрипт = pure CLI.** Вход через args/stdin, выход через stdout JSON. Side-effect'ы
   только явные (запись в Supabase, отправка в Telegram).
2. **Scoring = pure function.** Тестируется табличными тестами на фикстурах.
3. **Supabase = source of truth** для runtime-данных.
4. **Идемпотентность.** Повторный запуск с тем же входом не плодит дубликаты.
5. **Evidence обязателен.** Без `evidence_url` и `signal_date` сигнал невалиден.
6. **Уведомляет сама рутина.** Финальный шаг промпта — `notify.py`; внешнего callback нет.
