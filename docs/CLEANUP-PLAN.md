# План чистки под Claude Code Routines

Исполняемый план. Каждая фаза — атомарный коммит, после которого репозиторий зелёный
(`pytest` + `ruff check .`). Порядок выбран так, чтобы ничего не ломалось между шагами:
сначала готовим замену, потом удаляем старое, в конце правим инфраструктуру.

Базовые решения (зафиксированы ранее): бот = триггер с параметрами через `text` у
`/fire`; лёгкая история через `run_logs`; `worker` и очередь `pipeline_runs` удаляются.

Перед стартом: `git switch -c chore/routines-cleanup`.

---

## Фаза 0 — Бейзлайн

- [ ] `pytest` зелёный, `ruff check .` чистый — зафиксировать исходное состояние.
- [ ] Убедиться, что рутина в облаке уже создана (есть `ROUTINE_FIRE_URL`, `ROUTINE_TOKEN`),
      иначе бот после правок не сможет реально стрелять. Для тестов это не блокер (мокаем).

Коммит не нужен.

---

## Фаза 1 — Вынести `RunConfig`, отвязать от очереди

Цель: `RunConfig` остаётся (нужен мастеру и пресетам), `RunsStore` уходит из обихода.

- [ ] Создать `bot/config.py`: перенести из `bot/runs.py` `RunConfig`, `VALID_STAGES`,
      `VALID_SEGMENTS`, `RunStatus`, `TriggerType` и методы `validate/to_dict/from_dict`.
- [ ] Обновить импорты: `bot/presets.py` и `bot/gateway.py` → `from bot.config import RunConfig`.
- [ ] Пока НЕ удалять `bot/runs.py` (его ещё держит `worker.py`).

Проверка: `pytest -k "preset or config"`, `ruff check .`.
Коммит: `refactor(bot): extract RunConfig into bot/config.py`.

---

## Фаза 2 — Клиент `/fire`

- [ ] Создать `bot/routine.py`:
      ```python
      def fire(text: str = "") -> dict:
          """POST на /fire рутины. Возвращает {claude_code_session_id, ...}."""
      ```
      Берёт `ROUTINE_FIRE_URL`, `ROUTINE_TOKEN` из env; заголовки
      `Authorization: Bearer`, `anthropic-beta: experimental-cc-routine-2026-04-01`,
      `anthropic-version: 2023-06-01`; тело `{"text": text}`. Таймаут, обработка ошибок,
      понятный возврат при отсутствии токена (dev-режим).
- [ ] Добавить хелпер `config_to_text(cfg: RunConfig) -> str` (сериализация параметров
      запуска в строку для поля `text`, напр. `segments=...; limit=...; stages=...`).
- [ ] Тест `tests/test_routine_fire.py`: мок httpx — проверить заголовки, тело, парсинг ответа.

Проверка: `pytest -k routine`, `ruff check .`.
Коммит: `feat(bot): add /fire routine trigger client`.

---

## Фаза 3 — Переписать `gateway.py`

- [ ] `/run` и `/quickrun`: вместо `runs.enqueue(...)` собрать `RunConfig` → `config_to_text`
      → `routine.fire(text)`; ответить пользователю `session_id`/ссылкой на сеанс.
- [ ] `/status`, `/last`: читать `run_logs` из Supabase (последние записи / агрегаты),
      а не `pipeline_runs`.
- [ ] Удалить `/cancel` (через `/fire` отмены нет) — убрать команду, ветку и из `/help`.
- [ ] Удалить внутренний API: эндпоинты `POST /runs`, `GET /runs/{id}`, `POST /runs/{id}/cancel`,
      модель `RunRequest`, `_verify_internal_token` (обслуживали worker).
- [ ] Убрать импорт/использование `RunsStore` и `set_tg_message_id`; почистить `_deps()`.
- [ ] Оставить без изменений: webhook, allowlist, `/digest`/`/hot`/`/stale`, `TelegramSender`,
      `/ping`/`/help`/`/whoami`, мастер на кнопках (его выход теперь идёт в `fire`).

Проверка: `pytest -k "bot and not runs and not summary"`, `ruff check .`, локально
`uvicorn bot.gateway:app` + `curl /healthz`.
Коммит: `refactor(bot): trigger routine via /fire, drop internal queue API`.

---

## Фаза 4 — Удалить worker и очередь (код)

- [ ] Удалить `bot/worker.py`.
- [ ] Удалить `bot/runs.py` (`RunsStore`; `RunConfig` уже в `bot/config.py`).
- [ ] Удалить тесты `tests/test_bot_runs.py`, `tests/test_bot_summary.py`.
- [ ] Прогнать `grep -rn "worker\|RunsStore\|pipeline_runs\|INTERNAL_API_TOKEN" bot scripts tests`
      — не должно остаться живых ссылок.

Проверка: `pytest`, `ruff check .`.
Коммит: `chore(bot): remove worker + pipeline_runs queue`.

---

## Фаза 5 — Промпт рутины

- [ ] `agents/prompts/pipeline_task.md`: убрать ожидание инъекции конфига от worker
      (комментарий `INJECTED BY WORKER`); добавить блок «если в `text` переданы
      `segments`/`limit`/`stages` — использовать их, иначе брать все активные сегменты».
- [ ] Убедиться, что финальный шаг — `scripts/notify.py --run-summary {...}` (Шаг 7 есть).
- [ ] Удалить устаревший `agents/prompts/discover_verify_task.md`.
- [ ] Обновить `tests/test_pipeline_prompts.py` под новый промпт (если проверяет инъекцию).

Проверка: `pytest -k prompt`, `ruff check .`.
Коммит: `chore(prompts): make pipeline_task self-contained for routine`.

---

## Фаза 6 — База данных

- [ ] Создать `sql/013_drop_pipeline_runs.sql`:
      ```sql
      DROP TABLE IF EXISTS pipeline_runs;
      ```
      Не править применённый `012_bot.sql`. Сохранить `bot_users`, `bot_presets`,
      `bot_dialog_state`, `run_logs`.
- [ ] Сверить `tests/test_migrations.py` — добавить 013, проверить, что `run_logs` цел.
- [ ] Применить миграцию в Supabase (SQL Editor) после мёрджа.

Проверка: `pytest -k migration`.
Коммит: `chore(sql): drop pipeline_runs (013)`.

---

## Фаза 7 — Инфраструктура и секреты

- [ ] `railway.toml`: удалить сервис `worker`, оставить только `web`.
- [ ] `.env.example`: убрать `ANTHROPIC_API_KEY`, `INTERNAL_API_TOKEN`,
      `WORKER_POLL_INTERVAL_SEC`, `WORKER_HEARTBEAT_SEC`; добавить `ROUTINE_FIRE_URL`,
      `ROUTINE_TOKEN`.
- [ ] В Railway (прод) удалить переменные worker'а; добавить `ROUTINE_*`.
- [ ] В Environment рутины (claude.ai/code) завести секреты: `SUPABASE_*`, `NOTION_*`,
      `GITHUB_TOKEN`, `HF_TOKEN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.

Проверка: `ruff check .`; ревизия README таблицы секретов.
Коммит: `chore(deploy): drop worker service, add ROUTINE_* env`.

---

## Фаза 8 — End-to-end проверка

- [ ] `pytest` зелёный целиком, `ruff check .` чистый.
- [ ] `Run now` у рутины → сеанс виден на claude.ai/code, в Telegram пришла сводка `notify.py`.
- [ ] `/quickrun` из Telegram → HTTP 200 от `/fire` с `claude_code_session_id`.
- [ ] `/status`, `/last`, `/digest`, `/hot`, `/stale` отвечают (читают Supabase).
- [ ] Schedule-триггер: дождаться авто-запуска или проверить через `Run now`.
- [ ] Обновить README, если по ходу что-то разошлось с фактом.

Финал: PR `chore/routines-cleanup` → merge.

---

## Сводка изменений файлов

| Действие | Файлы |
|---|---|
| **Добавить** | `bot/config.py`, `bot/routine.py`, `tests/test_routine_fire.py`, `sql/013_drop_pipeline_runs.sql` |
| **Изменить** | `bot/gateway.py`, `bot/presets.py`, `agents/prompts/pipeline_task.md`, `tests/test_pipeline_prompts.py`, `tests/test_migrations.py`, `railway.toml`, `.env.example` |
| **Удалить** | `bot/worker.py`, `bot/runs.py`, `agents/prompts/discover_verify_task.md`, `tests/test_bot_runs.py`, `tests/test_bot_summary.py`, таблица `pipeline_runs` |

## Откат

Вся работа в ветке `chore/routines-cleanup`. Откат — `git switch main` / revert PR.
Удаление `pipeline_runs` обратимо повторным применением определения из `012_bot.sql`,
но данные очереди не восстановятся (они и не нужны).
