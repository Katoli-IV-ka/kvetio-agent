# Миграция на Claude Code Routines — аудит и чек-лист

Карта проекта под целевую модель: pipeline = **Claude Code Routine** в облаке
Anthropic (по подписке, без Anthropic API). Бот только дёргает `/fire`; уведомления
шлёт сама рутина. Решения, на которых построена карта:

- Бот = триггер с параметрами (stateless-мастер `/run`/пресеты собирают конфиг → передают в `text` у `/fire`).
- Лёгкая история ранов остаётся: `/status`, `/last` читают `run_logs` из Supabase. `/cancel` убираем.
- `worker` и очередь `pipeline_runs` удаляются в любом случае.

> Эта карта — план. Файлы пока не тронуты; удаляй/правь по чек-листу сам.

---

## Что меняется концептуально

| Было (API-схема) | Стало (routines) |
|---|---|
| `bot/worker.py` поллит очередь и зовёт `claude -p` по `ANTHROPIC_API_KEY` | Облако Anthropic само запускает рутину по Schedule / `/fire` |
| Бот кладёт ран в `pipeline_runs`, worker подхватывает | Бот напрямую POST-ит на `/fire` рутины |
| Worker собирает Summary и шлёт в Telegram | Рутина последним шагом зовёт `scripts/notify.py` |
| Запуск стоит денег по API | Запуск расходует подписку (дневной лимит ранов) |

---

## Карта файлов: keep / change / remove

### `bot/`

| Файл | Вердикт | Что делать |
|---|---|---|
| `gateway.py` | **CHANGE** | Заменить `runs.enqueue(...)` в `/run` и `/quickrun` на POST `/fire` (новый клиент). `/status`,`/last` — читать `run_logs`, не `pipeline_runs`. Удалить `/cancel`, внутренний `/runs` API и `/runs/{id}/cancel` (обслуживали worker). Оставить: webhook, `/digest`/`/hot`/`/stale`, `TelegramSender`, `/ping`/`/help`/`/whoami` |
| `access.py` | **REMOVE** | `bot_users` больше не нужен: доступ ограничивается внешними средствами |
| `dialog.py` | **KEEP** | stateless-мастер `/run`; состояние кодируется в callback_data |
| `presets.py` | **KEEP** | DB-backed пресеты параметров запуска |
| `preset_args.py` | **ADD** | парсинг `/presets save <name> key=value...` |
| `set_webhook.py` | **KEEP** | выставляет Telegram webhook |
| `worker.py` | **REMOVE** | поллер + `claude -p` по API — заменён облаком |
| `runs.py` | **CHANGE** | удалить `RunsStore` (CRUD/lock над `pipeline_runs`). Оставить `RunConfig` (валидация + `from_dict`) для сборки `text`. Лучше переименовать модуль или вынести `RunConfig` в `bot/config.py` |
| (новый) `bot/routine.py` | **ADD** | тонкий клиент: `fire(text: str)` → POST на `ROUTINE_FIRE_URL` с `ROUTINE_TOKEN` + бета-заголовком |

### `agents/prompts/`

| Файл | Вердикт | Что делать |
|---|---|---|
| `pipeline_task.md` | **CHANGE** | Сделать стабильным bootstrap-промптом рутины: он читает `agents/prompts/pipeline_main_task.md` из свежего checkout и передаёт туда `/fire text` |
| `pipeline_main_task.md` | **ADD** | Основной repo-managed prompt pipeline: парсит `segments`/`limit`/`stages`/`dry_run`/`notion_sync`, запускает этапы и финальный `notify.py` |
| `discover_verify_task.md` | **REMOVE** | помечен устаревшим (заменён `discovery` + `relevance`) |
| остальные | **KEEP** | этапы pipeline, под-агенты, monitor |

### `sql/`

| Таблица / файл | Вердикт | Что делать |
|---|---|---|
| `run_logs` (`001_init.sql`) | **KEEP** | история этапов; пишется `supabase_store.py` внутри рутины |
| `bot_users` (`012_bot.sql`) | **REMOVE** | удалить новой миграцией: allowlist больше нет |
| `bot_presets` (`012_bot.sql`) | **KEEP** | пресеты параметров |
| `bot_dialog_state` (`012_bot.sql`) | **REMOVE** | удалить новой миграцией: `/run` stateless |
| `pipeline_runs` (`012_bot.sql`) | **REMOVE** | очередь worker'а; больше не пишется. Вынести `DROP TABLE pipeline_runs` в новую миграцию `013_drop_pipeline_runs.sql` (не править применённый 012) |

### `tests/`

| Файл | Вердикт | Что делать |
|---|---|---|
| `test_bot_runs.py` | **REMOVE** | тестировал `RunsStore`/`pipeline_runs` |
| `test_bot_summary.py` | **REMOVE** | тестировал сбор Summary в worker |
| `test_bot_access.py` | **REMOVE** | allowlist удалён |
| `test_pipeline_prompts.py` | **CHANGE** | сверить bootstrap `pipeline_task.md` и основной `pipeline_main_task.md` |
| остальные | **KEEP** | источники, скоринг, дедуп, синк, контакты |

### Прочее

| Объект | Вердикт | Что делать |
|---|---|---|
| `railway.toml` | **CHANGE** | удалить сервис `worker`; оставить `web` (бот-триггер) |
| `.env.example` | **CHANGE** | убрать `ANTHROPIC_API_KEY`, `INTERNAL_API_TOKEN`; добавить `ROUTINE_FIRE_URL`, `ROUTINE_TOKEN` |
| `scripts/notify.py` | **KEEP** | теперь это и есть «бот шлёт уведомление» — последний шаг рутины |
| `scripts/*` (источники, store, score, notion_sync, dm_*) | **KEEP** | детерминированный слой, не зависит от способа запуска |

---

## Чек-лист миграции (по порядку)

1. **Рутина в облаке.** Создать routine на claude.ai/code: prompt = содержимое
   `agents/prompts/pipeline_task.md`, репо = `kvetio-agent`, Environment с секретами +
   `pip install -r requirements.txt`, триггеры Schedule + API. Сохранить
   `ROUTINE_FIRE_URL` и `ROUTINE_TOKEN`.
2. **Промпт.** Дальнейшие изменения логики вносить в `agents/prompts/pipeline_main_task.md`,
   затем прогнать `Run now` и убедиться, что приходит Telegram-сводка от `notify.py`.
3. **Бот.** Добавить `bot/routine.py` (`fire()`), переключить `/run`/`/quickrun` на него,
   `/status`/`/last` → `run_logs`, удалить `/cancel` и внутренний `/runs` API.
4. **Чистка кода.** Удалить `worker.py`, `RunsStore`, `test_bot_runs.py`, `test_bot_summary.py`.
5. **БД.** Применить `013_drop_pipeline_runs.sql`.
6. **Деплой.** `railway.toml` без `worker`; в Railway оставить только секреты бота
   (`TELEGRAM_*`, `SUPABASE_*`, `ROUTINE_*`, `BOT_WEBHOOK_URL`). `python -m bot.set_webhook`.
7. **Проверка end-to-end.** `/quickrun` → приходит `/fire`-ответ с session_id → рутина
   отрабатывает в облаке → в Telegram падает сводка. Schedule-триггер проверить через `Run now`.

---

## Чем подтверждается, что работает

- `pytest` зелёный (после удаления тестов worker'а).
- `Run now` у рутины → в claude.ai/code виден сеанс, в Telegram пришла сводка.
- `/quickrun` из Telegram → HTTP 200 от `/fire` с `claude_code_session_id`.
- `python scripts/supabase_store.py --coverage` отдаёт цифры (Supabase доступен из облака рутины).
