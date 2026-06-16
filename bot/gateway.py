"""FastAPI gateway: Telegram webhook.

Environment variables:
    SUPABASE_URL, SUPABASE_KEY
    TELEGRAM_BOT_TOKEN
    TELEGRAM_WEBHOOK_SECRET     — X-Telegram-Bot-Api-Secret-Token header value
    ROUTINE_FIRE_URL, ROUTINE_TOKEN — Claude Code Routine credentials
    KVETIO_LOG_LEVEL            — default INFO

Run locally:
    uvicorn bot.gateway:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env")

from bot.config import DEFAULT_LIMIT_PER_SEGMENT, RunConfig  # noqa: E402
from bot.dialog import apply_encoded_callback, build_step_message  # noqa: E402
from bot.preset_args import parse_preset_save_args  # noqa: E402
from bot.presets import PresetsStore  # noqa: E402
from bot.routine import config_to_text, fire  # noqa: E402

logger = logging.getLogger(__name__)

app = FastAPI(title="kvetio-bot-gateway", version="2.0.0")


def _make_supabase():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def _deps():
    client = _make_supabase()
    presets = PresetsStore(client)
    presets.ensure_seed_presets()
    return (
        presets,
        client,
    )


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ── Telegram Webhook ──────────────────────────────────────────────────────────

@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = "",
):
    _verify_webhook_secret(x_telegram_bot_api_secret_token)
    update = await request.json()
    logger.debug("Webhook update: %s", update)

    try:
        await _handle_update(update)
    except Exception as exc:  # noqa: BLE001
        logger.error("Update handling error: %s", exc, exc_info=True)

    return JSONResponse({"ok": True})


async def _handle_update(update: dict[str, Any]) -> None:
    presets, client = _deps()
    tg = TelegramSender()

    if "message" in update:
        await _handle_message(update["message"], presets, client, tg)
    elif "callback_query" in update:
        await _handle_callback(update["callback_query"], tg)


async def _handle_message(
    msg: dict[str, Any],
    presets: PresetsStore,
    client: Any,
    tg: "TelegramSender",
) -> None:
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()

    if not chat_id or not text.startswith("/"):
        return

    command = text.split()[0].lower().rstrip("@")
    args = text.split()[1:]

    if command == "/ping":
        await tg.send(chat_id, "🏓 pong")
        return

    if command == "/start":
        await tg.send(chat_id, _start_text())

    elif command == "/help":
        await tg.send(chat_id, _help_text())

    elif command == "/whoami":
        await tg.send(chat_id, f"Ваш chat_id: <code>{chat_id}</code>")

    elif command == "/status":
        row = _fetch_active_run(client)
        if row:
            task = row.get("task_name", "?")
            started = (row.get("started_at") or "")[:16]
            await tg.send(chat_id, f"🔵 Активный ран: <b>{task}</b> с {started}")
        else:
            await tg.send(chat_id, "✅ Активных ранов нет")

    elif command == "/last":
        n = int(args[0]) if args and args[0].isdigit() else 5
        n = min(n, 20)
        rows = _fetch_recent_runs(client, n)
        if not rows:
            await tg.send(chat_id, "Истории ранов нет")
        else:
            lines = ["<b>Последние раны:</b>"]
            for r in rows:
                task = r.get("task_name", "?")
                started = (r.get("started_at") or "")[:16]
                finished = r.get("finished_at")
                status_icon = "✅" if finished else "🔵"
                lines.append(f"{status_icon} <b>{task}</b> {started}")
            await tg.send(chat_id, "\n".join(lines))

    elif command == "/presets":
        await _handle_presets_command(chat_id, args, presets, tg)

    elif command == "/quickrun":
        preset_name = args[0] if args else None
        preset = presets.get(preset_name) if preset_name else presets.get_default()
        if not preset:
            await tg.send(chat_id, f"Пресет не найден: {preset_name or 'default'}")
            return
        cfg_dict = preset["config"]
        cfg_dict["triggered_by"] = f"chat:{chat_id}"
        cfg_dict["trigger_type"] = "manual"
        cfg = RunConfig.from_dict(cfg_dict)
        result = fire(config_to_text(cfg))
        if result.get("dev_mode"):
            await tg.send(chat_id, f"🟡 [dev] Рутина запущена (пресет: {preset['name']})")
        elif "error" in result:
            await tg.send(chat_id, f"❌ Ошибка запуска: {result['error']}")
        else:
            session_id = result.get("claude_code_session_id", "?")
            await tg.send(
                chat_id,
                f"🟢 Рутина запущена (пресет: {preset['name']})\n"
                f"Session: <code>{session_id}</code>",
            )

    elif command == "/run":
        draft: dict[str, Any] = {
            "segments": [],
            "limit_per_segment": DEFAULT_LIMIT_PER_SEGMENT,
            "stages": "full",
            "dry_run": False,
            "notion_sync": True,
        }
        text_out, keyboard = build_step_message("segments", draft)
        await tg.send_with_keyboard(chat_id, text_out, keyboard)

    elif command in ("/digest", "/hot", "/stale"):
        await _handle_routine_command(command, chat_id, args, tg)

    elif command == "/settings":
        await tg.send(
            chat_id,
            "⚙️ Настройки через /presets. Используйте /run для пошагового запуска "
            "или /quickrun [preset] для быстрого запуска.",
        )


async def _handle_callback(
    cq: dict[str, Any],
    tg: "TelegramSender",
) -> None:
    chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
    message_id = cq.get("message", {}).get("message_id")
    data = cq.get("data", "")
    cq_id = cq.get("id", "")

    await tg.answer_callback(cq_id)

    try:
        next_step, new_draft = apply_encoded_callback(data)
    except ValueError:
        await tg.edit_message(chat_id, message_id, "Сессия устарела. Используйте /run заново.")
        return

    if next_step == "done":
        cfg = RunConfig(
            segments=new_draft.get("segments", []),
            limit_per_segment=new_draft.get(
                "limit_per_segment",
                DEFAULT_LIMIT_PER_SEGMENT,
            ),
            stages=new_draft.get("stages", "full"),
            dry_run=new_draft.get("dry_run", False),
            notion_sync=new_draft.get("notion_sync", True),
        )
        try:
            cfg.validate()
        except ValueError as exc:
            await tg.edit_message(chat_id, message_id, f"❌ Ошибка конфига: {exc}")
            return
        result = fire(config_to_text(cfg))
        if result.get("dev_mode"):
            await tg.edit_message(chat_id, message_id, "🟡 <b>[dev] Рутина запущена</b>")
        elif "error" in result:
            await tg.edit_message(chat_id, message_id, f"❌ Ошибка запуска: {result['error']}")
        else:
            session_id = result.get("claude_code_session_id", "?")
            await tg.edit_message(
                chat_id, message_id,
                f"🟢 <b>Рутина запущена</b>\nSession: <code>{session_id}</code>",
            )

    elif next_step == "cancelled":
        await tg.edit_message(chat_id, message_id, "❌ Запуск отменён")

    else:
        text_out, keyboard = build_step_message(next_step, new_draft)
        await tg.edit_message_with_keyboard(chat_id, message_id, text_out, keyboard)


async def _handle_presets_command(
    chat_id: str, args: list[str], presets: PresetsStore, tg: "TelegramSender"
) -> None:
    if not args:
        items = presets.list_all()
        if not items:
            await tg.send(chat_id, "Пресетов нет. Они будут созданы автоматически.")
            return
        lines = ["<b>Пресеты:</b>"]
        for p in items:
            dflt = " ⭐ (default)" if p.get("is_default") else ""
            lines.append(f"· <b>{p['name']}</b>{dflt}")
        await tg.send(chat_id, "\n".join(lines))
        return

    sub = args[0].lower()

    if sub == "use" and len(args) >= 2:
        p = presets.get(args[1])
        if not p:
            await tg.send(chat_id, f"Пресет не найден: {args[1]}")
        else:
            await tg.send(chat_id, f"Используйте /quickrun {args[1]} для запуска")

    elif sub == "save":
        try:
            name, config, is_default = parse_preset_save_args(args)
        except ValueError as exc:
            await tg.send(chat_id, f"❌ {exc}")
            return
        presets.save(name, config, owner=f"chat:{chat_id}", is_default=is_default)
        suffix = " и назначен default" if is_default else ""
        await tg.send(chat_id, f"✅ Пресет {name} сохранён{suffix}")

    elif sub == "default" and len(args) >= 2:
        if presets.set_default(args[1]):
            await tg.send(chat_id, f"✅ Пресет {args[1]} назначен default")
        else:
            await tg.send(chat_id, f"Пресет не найден: {args[1]}")

    elif sub == "delete" and len(args) >= 2:
        if presets.delete(args[1]):
            await tg.send(chat_id, f"✅ Пресет {args[1]} удалён")
        else:
            await tg.send(chat_id, f"Пресет не найден: {args[1]}")

    else:
        await tg.send(
            chat_id,
            "Использование:\n"
            "/presets\n"
            "/presets use <name>\n"
            "/presets save <name> segments=<seg1,seg2> limit=<n> "
            "stages=<full|stage1,stage2> [dry_run=true|false] "
            "[notion_sync=true|false] [default=true|false]\n"
            "/presets default <name>\n"
            "/presets delete <name>",
        )


async def _handle_routine_command(
    command: str, chat_id: str, args: list[str], tg: "TelegramSender"
) -> None:
    try:
        from supabase_store import SupabaseStore
        from telegram_routines import run_routine

        routine_map = {"/digest": "daily_digest", "/hot": "hot_leads", "/stale": "stale_review"}
        routine_name = routine_map[command]
        store = SupabaseStore()

        limit = int(args[0]) if args and args[0].isdigit() else 5
        result = run_routine(routine_name, store=store, dry_run=False, limit=limit)
        await tg.send(chat_id, result.message)
    except Exception as exc:  # noqa: BLE001
        logger.error("Routine %s failed: %s", command, exc)
        await tg.send(chat_id, f"❌ Ошибка рутины: {exc}")


def _fetch_active_run(client: Any) -> dict[str, Any] | None:
    """Return the most recent run_log with no finished_at (in progress)."""
    result = (
        client.table("run_logs")
        .select("task_name,started_at,finished_at")
        .is_("finished_at", "null")
        .order("started_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def _fetch_recent_runs(client: Any, limit: int = 5) -> list[dict[str, Any]]:
    """Return recent run_log entries ordered by start time."""
    result = (
        client.table("run_logs")
        .select("task_name,started_at,finished_at")
        .order("started_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def _start_text() -> str:
    return "\n".join(
        [
            "🤖 <b>Kvetio Agent Bot</b>",
            "",
            "Этот бот запускает Kvetio Agent Pipeline: агент ищет компании по ICP-сегментам, проверяет релевантность, скорит лиды, обогащает данные и готовит результат для Supabase/Notion.",
            "",
            "Бот сам не выполняет pipeline. Он собирает параметры и отправляет запуск в Claude Code Routine через /fire. После завершения рутина сама присылает сводку в Telegram.",
            "",
            "/run — подробный мастер запуска",
            "/quickrun [preset] — быстрый запуск по пресету",
            "/presets — сохранение и настройка пресетов",
            "/help — все команды",
        ]
    )


def _help_text() -> str:
    return "\n".join(
        [
            "🤖 <b>Kvetio Agent Bot: команды</b>",
            "",
            "/start — что делает бот и как работает запуск",
            "/help — эта справка",
            "/ping — проверка доступности бота",
            "/whoami — показать chat_id текущего чата",
            "",
            "<b>Запуск агента</b>",
            "/run — подробный мастер запуска с выбором параметров",
            "/quickrun — быстрый запуск default-пресета",
            "/quickrun &lt;preset&gt; — быстрый запуск выбранного пресета",
            "",
            "<b>Пресеты</b>",
            "/presets — список пресетов",
            "/presets use &lt;name&gt; — подсказка для запуска пресета",
            "/presets save &lt;name&gt; segments=&lt;seg1,seg2&gt; limit=&lt;n&gt; stages=&lt;full|stage1,stage2&gt; [dry_run=true|false] [notion_sync=true|false] [default=true|false] — сохранить пресет",
            "/presets default &lt;name&gt; — назначить default-пресет",
            "/presets delete &lt;name&gt; — удалить пресет",
            "",
            "<b>Статус и отчеты</b>",
            "/status — текущий активный ран",
            "/last [n] — последние n запусков, максимум 20",
            "/digest [limit] — дайджест",
            "/hot [limit] — горячие лиды",
            "/stale [limit] — очередь на проверку",
            "",
            "/settings — где менять параметры запуска",
        ]
    )


# ── Telegram sender helper ────────────────────────────────────────────────────

class TelegramSender:
    def __init__(self) -> None:
        self._token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self._base = f"https://api.telegram.org/bot{self._token}"

    async def send(self, chat_id: str, text: str) -> dict:
        return await self._post(
            "/sendMessage",
            {"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
        )

    async def send_with_keyboard(
        self, chat_id: str, text: str, keyboard: list[list[dict]]
    ) -> dict:
        return await self._post(
            "/sendMessage",
            {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": keyboard},
            },
        )

    async def edit_message(self, chat_id: str, message_id: int, text: str) -> dict:
        return await self._post(
            "/editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
            },
        )

    async def edit_message_with_keyboard(
        self, chat_id: str, message_id: int, text: str, keyboard: list[list[dict]]
    ) -> dict:
        return await self._post(
            "/editMessageText",
            {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": "HTML",
                "reply_markup": {"inline_keyboard": keyboard},
            },
        )

    async def answer_callback(self, callback_query_id: str) -> None:
        await self._post("/answerCallbackQuery", {"callback_query_id": callback_query_id})

    async def _post(self, method: str, payload: dict) -> dict:
        if not self._token:
            logger.warning("TELEGRAM_BOT_TOKEN not set — skipping %s", method)
            return {}
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.post(f"{self._base}{method}", json=payload)
                return resp.json()
            except Exception as exc:  # noqa: BLE001
                logger.error("Telegram API %s failed: %s", method, exc)
                return {}


# ── Token verification ────────────────────────────────────────────────────────

def _verify_webhook_secret(token: str) -> None:
    expected = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    if expected and token != expected:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid webhook secret",
        )


if __name__ == "__main__":
    import uvicorn

    level = os.environ.get("KVETIO_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
