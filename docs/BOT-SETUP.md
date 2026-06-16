# Настройка Telegram-бота-триггера

Бот в новой схеме делает только одно: принимает твои команды в Telegram,
собирает параметры и дёргает `/fire` рутины. Он не запускает агента и не шлёт уведомления о
результате — это делает сама рутина. Поэтому настраиваем по порядку:
**рутина → Telegram-бот → Supabase → секреты → деплой → webhook → проверка**.

---

## Шаг 0 — Предусловие: рутина уже создана

Бот зовёт `/fire`, поэтому сначала должна существовать рутина с API-триггером.
На [claude.ai/code/routines](https://claude.ai/code/routines): открыть рутину →
**Edit** → **Select a trigger** → **Add another trigger** → **API** → сохранить →
**Generate token**.

Запиши два значения (токен показывается один раз):

- `ROUTINE_FIRE_URL` — вида `https://api.anthropic.com/v1/claude_code/routines/<ROUTINE_ID>/fire`
- `ROUTINE_TOKEN` — `sk-ant-oat01-...`

Если рутины ещё нет — сначала создай её по разделу «Настройка рутины» в README.

---

## Шаг 1 — Создать бота в Telegram

1. Написать [@BotFather](https://t.me/BotFather) → `/newbot`.
2. Задать имя и username (должен заканчиваться на `bot`).
3. Скопировать выданный **TELEGRAM_BOT_TOKEN** (вида `123456789:AAF...`).
4. Узнать свой `chat_id`: написать своему боту любое сообщение, затем открыть
   `https://api.telegram.org/bot<TOKEN>/getUpdates` и найти `message.chat.id`.

---

## Шаг 2 — Придумать секреты webhook

Сгенерировать две случайные строки (например `openssl rand -hex 32`):

- `TELEGRAM_WEBHOOK_SECRET` — Telegram будет слать его в заголовке, бот проверяет.
- (`INTERNAL_API_TOKEN` в новой схеме не нужен — внутреннего `/runs` API больше нет.)

`BOT_WEBHOOK_URL` появится после деплоя (Шаг 5) — вида
`https://<app>.up.railway.app/telegram/webhook`.

---

## Шаг 3 — Проверить внешнее ограничение доступа

Бот больше не хранит пользователей и роли в Supabase. Если доступ нужно
ограничить, делай это вне базы бота: настройками Telegram, приватным размещением,
секретным webhook, proxy или другим внешним механизмом.

---

## Шаг 4 — Собрать переменные окружения бота

Боту на Railway нужны только эти переменные (полная карта секретов — в README):

| Переменная | Откуда | Зачем |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Шаг 1 | отвечать на команды |
| `TELEGRAM_WEBHOOK_SECRET` | Шаг 2 | проверка подлинности webhook |
| `BOT_WEBHOOK_URL` | Шаг 5 | адрес webhook для `set_webhook` |
| `ROUTINE_FIRE_URL` | Шаг 0 | endpoint рутины |
| `ROUTINE_TOKEN` | Шаг 0 | bearer-токен для `/fire` |
| `SUPABASE_URL`, `SUPABASE_KEY` | проект Supabase | пресеты + чтение для `/status`,`/digest` |
| `KVETIO_LOG_LEVEL` | опц., default `INFO` | логирование |

Локально те же значения кладутся в `.env` (для отладки).

> Эти переменные — для бота. Секреты для самой работы pipeline (`NOTION_*`,
> `GITHUB_TOKEN`, `HF_TOKEN`, `TELEGRAM_CHAT_ID`) задаются не здесь, а в Environment
> рутины на claude.ai/code.

---

## Шаг 5 — Деплой на Railway

1. Создать проект Railway из репозитория `kvetio-agent`.
2. Сервис `web` (из `railway.toml`):
   `uvicorn bot.gateway:app --host 0.0.0.0 --port $PORT`, healthcheck `/healthz`.
   (Сервис `worker` в новой схеме не нужен — если он ещё в `railway.toml`, удали.)
3. Прописать переменные из Шага 4 в сервис `web`.
4. Дождаться деплоя, скопировать публичный URL → задать
   `BOT_WEBHOOK_URL = https://<app>.up.railway.app/telegram/webhook`.
5. Проверить здоровье: `curl https://<app>.up.railway.app/healthz` → `{"status":"ok"}`.

---

## Шаг 6 — Выставить webhook

Идемпотентно регистрируем webhook в Telegram (берёт `BOT_WEBHOOK_URL` и секрет из env):

```bash
python -m bot.set_webhook
```

Запускать можно из деплой-хука Railway или разово локально с прод-значениями env.

---

## Шаг 7 — Проверка

В чате с ботом:

1. `/ping` → `🏓 pong` (бот жив).
2. `/start` → кратко объясняет назначение бота.
3. `/whoami` → показывает твой `chat_id`.
4. `/presets` → показывает сохранённые пресеты или seed-пресеты.
5. `/quickrun` → бот POST-ит на `/fire`, в ответ присылает `session_id`/ссылку на сеанс.
6. `/run` → открывает stateless-мастер запуска на кнопках.
7. Открыть сеанс на claude.ai/code — рутина выполняется; по завершении в Telegram
   приходит сводка от `scripts/notify.py` (это шлёт рутина, не бот).
8. `/status`, `/last`, `/digest`, `/hot`, `/stale` → отвечают данными из Supabase.

---

## Если что-то не работает

- **`/quickrun` пишет ошибку `/fire`** → проверь `ROUTINE_FIRE_URL`/`ROUTINE_TOKEN`,
  что токен не отозван и бета-заголовок актуален.
- **Telegram не доставляет апдейты** → неверный `BOT_WEBHOOK_URL` или рассинхрон
  `TELEGRAM_WEBHOOK_SECRET`; перезапусти `python -m bot.set_webhook` и глянь
  `https://api.telegram.org/bot<TOKEN>/getWebhookInfo`.
- **Сводка не приходит после рутины** → проблема не в боте: проверь, что в Environment
  рутины заданы `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`, и что финальный шаг
  `pipeline_task.md` зовёт `notify.py`.

> Примечание: команды `/run`, `/quickrun`, `/status`, `/last` и клиент `/fire`
> появляются после Фаз 2–3 плана чистки (`docs/CLEANUP-PLAN.md`). До этого в коде ещё
> старая очередь — инструкция описывает целевого бота.
