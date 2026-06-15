"""FastAPI gateway: Telegram webhook + internal /runs API.

Environment variables:
    SUPABASE_URL, SUPABASE_KEY
    TELEGRAM_BOT_TOKEN
    TELEGRAM_WEBHOOK_SECRET     — X-Telegram-Bot-Api-Secret-Token header value
    INTERNAL_API_TOKEN          — Bearer token for POST /runs
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
from fastapi import FastAPI, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env")

from bot.access import AccessStore
from bot.dialog import DialogStore, apply_callback, build_step_message
from bot.presets import PresetsStore
from bot.runs import RunConfig, RunsStore

logger = logging.getLogger(__name__)

app = FastAPI(title="kvetio-bot-gateway", version="1.0.0")


def _make_supabase():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def _deps():
    client = _make_supabase()
    return (
        RunsStore(client),
        AccessStore(client),
        PresetsStore(client),
        DialogStore(client),
        client,
    )


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


# ── Internal Run API ──────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    segments: list[str]
    limit_per_segment: int = 30
    stages: str | list[str] = "full"
    dry_run: bool = False
    notion_sync: bool = True
    triggered_by: str = ""
    trigger_type: str = "manual"
    tg_chat_id: str | None = None


@app.post("/runs", status_code=201)
async def create_run(
    body: RunRequest,
    authorization: str = Header(default=""),
):
    _verify_internal_token(authorization)
    runs, _, _, _, _ = _deps()
    cfg = RunConfig(
        segments=body.segments,
        limit_per_segment=body.limit_per_segment,
        stages=body.stages,
        dry_run=body.dry_run,
        notion_sync=body.notion_sync,
        triggered_by=body.triggered_by,
        trigger_type=body.trigger_type,  # type: ignore[arg-type]
    )
    try:
        cfg.validate()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run_id = runs.enqueue(
        cfg,
        trigger_type=body.trigger_type,  # type: ignore[arg-type]
        triggered_by=body.triggered_by,
        tg_chat_id=body.tg_chat_id,
    )
    return {"run_id": run_id, "status": "queued"}


@app.get("/runs/{run_id}")
async def get_run(run_id: str, authorization: str = Header(default="")):
    _verify_internal_token(authorization)
    runs, _, _, _, _ = _deps()
    run = runs.get(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="run not found")
    return run


@app.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, authorization: str = Header(default="")):
    _verify_internal_token(authorization)
    runs, _, _, _, _ = _deps()
    ok = runs.cancel(run_id)
    if not ok:
        raise HTTPException(status_code=409, detail="run not cancellable")
    return {"run_id": run_id, "status": "cancelled"}


# ── Telegram Webhook ──────────────────────────────────────────────────────────

@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=""),
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
    runs, access, presets, dialog, client = _deps()
    tg = TelegramSender()

    if "message" in update:
        await _handle_message(update["message"], runs, access, presets, dialog, tg)
    elif "callback_query" in update:
        await _handle_callback(update["callback_query"], runs, access, presets, dialog, tg)


async def _handle_message(
    msg: dict[str, Any],
    runs: RunsStore,
    access: AccessStore,
    presets: PresetsStore,
    dialog: DialogStore,
    tg: "TelegramSender",
) -> None:
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()
    username = msg.get("from", {}).get("username", "")

    if not chat_id or not text.startswith("/"):
        return

    command = text.split()[0].lower().rstrip("@")
    args = text.split()[1:]

    # Health / info commands — no auth needed for /ping
    if command == "/ping":
        await tg.send(chat_id, "🏓 pong")
        return

    if not access.is_allowed(chat_id):
        logger.info("Ignored message from unknown chat_id %s", chat_id)
        return

    role = access.get_role(chat_id)
    is_admin = (role == "admin")

    if command == "/help":
        await tg.send(chat_id, _help_text(is_admin))

    elif command == "/whoami":
        await tg.send(chat_id, f"Ваш chat_id: <code>{chat_id}</code>\nРоль: <b>{role}</b>")

    elif command == "/status":
        run = runs.get_active()
        if run:
            run_id_short = str(run["id"])[:8]
            status_text = run.get("status", "?")
            await tg.send(chat_id, f"🔵 Активный ран: <code>{run_id_short}</code> — {status_text}")
        else:
            await tg.send(chat_id, "✅ Активных ранов нет")

    elif command == "/last":
        n = int(args[0]) if args and args[0].isdigit() else 5
        n = min(n, 20)
        recent = runs.list_recent(n)
        if not recent:
            await tg.send(chat_id, "Истории ранов нет")
        else:
            lines = ["<b>Последние раны:</b>"]
            for r in recent:
                rid = str(r["id"])[:8]
                st = r.get("status", "?")
                ts = (r.get("queued_at") or "")[:16]
                lines.append(f"· <code>{rid}</code> {st} {ts}")
            await tg.send(chat_id, "\n".join(lines))

    elif command == "/cancel":
        if not is_admin:
            await tg.send(chat_id, "⛔ Только администраторы могут отменять раны")
            return
        run = runs.get_active()
        if not run:
            await tg.send(chat_id, "Нет активных ранов для отмены")
            return
        if runs.cancel(run["id"]):
            await tg.send(chat_id, f"✅ Ран <code>{str(run['id'])[:8]}</code> отменён")
        else:
            await tg.send(chat_id, "❌ Не удалось отменить ран")

    elif command == "/presets":
        await _handle_presets_command(chat_id, args, is_admin, presets, tg)

    elif command == "/quickrun":
        if not is_admin:
            await tg.send(chat_id, "⛔ Только администраторы могут запускать pipeline")
            return
        preset_name = args[0] if args else None
        preset = presets.get(preset_name) if preset_name else presets.get_default()
        if not preset:
            await tg.send(chat_id, f"Пресет не найден: {preset_name or 'default'}")
            return
        cfg_dict = preset["config"]
        cfg_dict["triggered_by"] = f"chat:{chat_id}"
        cfg_dict["trigger_type"] = "manual"
        cfg = RunConfig.from_dict(cfg_dict)
        run_id = runs.enqueue(cfg, trigger_type="manual", triggered_by=f"chat:{chat_id}", tg_chat_id=chat_id)
        await tg.send(chat_id, f"🟡 Ран <code>{run_id[:8]}</code> поставлен в очередь (пресет: {preset['name']})")

    elif command == "/run":
        if not is_admin:
            await tg.send(chat_id, "⛔ Только администраторы могут запускать pipeline")
            return
        dialog.clear(chat_id)
        draft: dict[str, Any] = {
            "segments": [],
            "limit_per_segment": 30,
            "stages": "full",
            "dry_run": False,
            "notion_sync": True,
        }
        dialog.save(chat_id, "segments", draft)
        text_out, keyboard = build_step_message("segments", draft)
        await tg.send_with_keyboard(chat_id, text_out, keyboard)

    elif command in ("/digest", "/hot", "/stale"):
        await _handle_routine_command(command, chat_id, args, tg)

    elif command == "/settings":
        await tg.send(chat_id, "⚙️ Настройки через /presets. Используйте /quickrun [preset] для быстрого запуска.")


async def _handle_callback(
    cq: dict[str, Any],
    runs: RunsStore,
    access: AccessStore,
    presets: PresetsStore,
    dialog: DialogStore,
    tg: "TelegramSender",
) -> None:
    chat_id = str(cq.get("message", {}).get("chat", {}).get("id", ""))
    message_id = cq.get("message", {}).get("message_id")
    data = cq.get("data", "")
    cq_id = cq.get("id", "")

    await tg.answer_callback(cq_id)

    if not access.is_allowed(chat_id):
        return

    state = dialog.get(chat_id)
    if not state:
        await tg.edit_message(chat_id, message_id, "Сессия истекла. Используйте /run заново.")
        return

    step = state["step"]
    draft = state.get("draft") or {}

    next_step, new_draft = apply_callback(step, draft, data)

    if next_step == "done":
        dialog.clear(chat_id)
        cfg = RunConfig(
            segments=new_draft.get("segments", []),
            limit_per_segment=new_draft.get("limit_per_segment", 30),
            stages=new_draft.get("stages", "full"),
            dry_run=new_draft.get("dry_run", False),
            notion_sync=new_draft.get("notion_sync", True),
        )
        try:
            cfg.validate()
        except ValueError as exc:
            await tg.edit_message(chat_id, message_id, f"❌ Ошибка конфига: {exc}")
            return
        run_id = runs.enqueue(cfg, trigger_type="manual", triggered_by=f"chat:{chat_id}", tg_chat_id=chat_id)
        await tg.edit_message(
            chat_id, message_id,
            f"🟡 <b>Ран принят</b> — <code>{run_id[:8]}</code>\nПоставлен в очередь выполнения."
        )
        runs.set_tg_message_id(run_id, message_id)

    elif next_step == "cancelled":
        dialog.clear(chat_id)
        await tg.edit_message(chat_id, message_id, "❌ Запуск отменён")

    else:
        dialog.save(chat_id, next_step, new_draft)
        text_out, keyboard = build_step_message(next_step, new_draft)
        await tg.edit_message_with_keyboard(chat_id, message_id, text_out, keyboard)


async def _handle_presets_command(
    chat_id: str, args: list[str], is_admin: bool, presets: PresetsStore, tg: "TelegramSender"
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

    elif sub == "delete" and len(args) >= 2 and is_admin:
        if presets.delete(args[1]):
            await tg.send(chat_id, f"✅ Пресет {args[1]} удалён")
        else:
            await tg.send(chat_id, f"Пресет не найден: {args[1]}")

    elif sub in ("save", "delete") and not is_admin:
        await tg.send(chat_id, "⛔ Только администраторы могут изменять пресеты")
    else:
        await tg.send(chat_id, "Использование: /presets | /presets use <name> | /presets delete <name>")


async def _handle_routine_command(
    command: str, chat_id: str, args: list[str], tg: "TelegramSender"
) -> None:
    try:
        from supabase_store import SupabaseStore
        from telegram_routines import run_routine
        from notify import send

        routine_map = {"/digest": "daily_digest", "/hot": "hot_leads", "/stale": "stale_review"}
        routine_name = routine_map[command]
        store = SupabaseStore()

        limit = int(args[0]) if args and args[0].isdigit() else 5
        result = run_routine(routine_name, store=store, dry_run=False, limit=limit)
        await tg.send(chat_id, result.message)
    except Exception as exc:  # noqa: BLE001
        logger.error("Routine %s failed: %s", command, exc)
        await tg.send(chat_id, f"❌ Ошибка рутины: {exc}")


def _help_text(is_admin: bool) -> str:
    lines = [
        "🤖 <b>Kvetio Agent Bot</b>\n",
        "<b>Команды для всех:</b>",
        "/status — текущий ран",
        "/last [n] — история ранов",
        "/digest — дайджест за сегодня",
        "/hot — топ Hot-лиды",
        "/stale — очередь на проверку",
        "/presets — список пресетов",
        "/whoami — ваш chat_id и роль",
        "/ping — проверка бота",
        "/help — эта справка",
    ]
    if is_admin:
        lines += [
            "",
            "<b>Только для администраторов:</b>",
            "/run — запуск pipeline (мастер на кнопках)",
            "/quickrun [preset] — быстрый запуск по пресету",
            "/cancel — отменить активный ран",
            "/presets save/delete — управление пресетами",
        ]
    return "\n".join(lines)


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


def _verify_internal_token(authorization: str) -> None:
    expected = os.environ.get("INTERNAL_API_TOKEN", "")
    if not expected:
        return  # no auth configured — dev mode
    provided = authorization.removeprefix("Bearer ").strip()
    if provided != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid or missing internal API token",
        )


if __name__ == "__main__":
    import uvicorn

    level = os.environ.get("KVETIO_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
