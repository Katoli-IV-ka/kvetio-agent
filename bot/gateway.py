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

import asyncio
import logging
import os
import sys
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
load_dotenv(ROOT / ".env")

from bot.config import DEFAULT_LIMIT_PER_SEGMENT, ENRICH_DEFAULT_STAGES, RunConfig  # noqa: E402
from bot.dialog import apply_encoded_callback, build_enrich_step_message, build_step_message  # noqa: E402
from bot.intent_agent import ParsedIntent, parse_intent  # noqa: E402
from bot.routine import config_to_text, fire  # noqa: E402
from bot.scenarios import SCENARIOS  # noqa: E402
from bot.session import BotSession, SessionStore  # noqa: E402

logger = logging.getLogger(__name__)

app = FastAPI(title="kvetio-bot-gateway", version="2.0.0")
session_store = SessionStore()


def _make_supabase():
    from supabase import create_client
    return create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])


def _deps():
    client = _make_supabase()
    return client


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.post("/internal/notion-sync")
async def internal_notion_sync(request: Request, background_tasks: BackgroundTasks):
    _verify_sync_secret(request.headers.get("Authorization", ""))
    background_tasks.add_task(_run_notion_sync_and_notify, notify_chat_id=None)
    return {"status": "queued"}


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
    client = _deps()
    tg = TelegramSender()

    if "message" in update:
        await _handle_message(update["message"], client, tg)
    elif "callback_query" in update:
        await _handle_callback(update["callback_query"], tg)


async def _handle_message(
    msg: dict[str, Any],
    client: Any,
    tg: "TelegramSender",
) -> None:
    chat_id = str(msg.get("chat", {}).get("id", ""))
    text = (msg.get("text") or "").strip()

    if not chat_id or not text:
        return

    if not text.startswith("/"):
        session = await session_store.get(chat_id)
        if session and session.state == "clarifying":
            await _handle_ask_followup(chat_id, text, session, tg)
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

    elif command == "/refill":
        draft = {
            "run_mode": "enrich_existing",
            "segments": [],
            "limit_per_segment": 30,
            "stages": list(ENRICH_DEFAULT_STAGES),
            "dry_run": False,
            "notion_sync": True,
        }
        text_out, keyboard = build_enrich_step_message("segments", draft)
        await tg.send_with_keyboard(chat_id, text_out, keyboard)

    elif command == "/ask":
        prompt = " ".join(args)
        await _handle_ask_command(chat_id, prompt, tg)

    elif command in ("/digest", "/hot", "/stale"):
        await _handle_routine_command(command, chat_id, args, tg)

    elif command == "/notion_sync":
        await _handle_notion_sync_command(chat_id, tg)

    elif command == "/settings":
        await tg.send(
            chat_id,
            "⚙️ Параметры запуска выбираются через /run.",
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

    if data.startswith("a1:"):
        await _handle_ask_callback(chat_id, message_id, data, tg)
        return

    try:
        next_step, new_draft = apply_encoded_callback(data)
    except ValueError:
        await tg.edit_message(chat_id, message_id, "Сессия устарела. Используйте /run заново.")
        return

    if next_step == "done":
        cfg = RunConfig(
            run_mode=new_draft.get("run_mode", "icp_segment"),
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


async def _handle_ask_command(chat_id: str, prompt: str, tg: "TelegramSender") -> None:
    messages = []
    if prompt:
        messages.append({"role": "user", "parts": [{"text": prompt}]})

    session = BotSession(
        chat_id=chat_id,
        messages=messages,
        parsed_intent=None,
        state="clarifying",
        clarification_count=0,
        created_at=datetime.now(UTC),
    )
    await session_store.set(session)

    if not prompt:
        await tg.send(chat_id, "Что хочешь исследовать?")
        return

    parsed = await parse_intent(messages)
    await _advance_ask_dialog(chat_id, session, parsed, tg)


async def _handle_ask_followup(
    chat_id: str,
    text: str,
    session: BotSession,
    tg: "TelegramSender",
) -> None:
    session.messages.append({"role": "user", "parts": [{"text": text}]})
    parsed = await parse_intent(session.messages)
    await _advance_ask_dialog(chat_id, session, parsed, tg)


async def _advance_ask_dialog(
    chat_id: str,
    session: BotSession,
    parsed: ParsedIntent,
    tg: "TelegramSender",
) -> None:
    session.parsed_intent = parsed
    if parsed.missing_fields and session.clarification_count < 3:
        session.clarification_count += 1
        session.state = "clarifying"
        await session_store.set(session)
        await tg.send(chat_id, parsed.clarification_question or "Уточни параметры запуска.")
        return

    session.state = "confirming"
    await session_store.set(session)
    text, keyboard = _ask_confirmation(parsed)
    await tg.send_with_keyboard(chat_id, text, keyboard)


async def _handle_ask_callback(
    chat_id: str,
    message_id: int,
    data: str,
    tg: "TelegramSender",
) -> None:
    session = await session_store.get(chat_id)
    if not session:
        await tg.edit_message(chat_id, message_id, "Сессия устарела. Используйте /ask заново.")
        return

    action = data.split(":", 1)[1]
    if action == "cancel":
        await session_store.delete(chat_id)
        await tg.edit_message(chat_id, message_id, "❌ Запуск отменён")
        return

    if action == "edit":
        session.state = "clarifying"
        await session_store.set(session)
        await tg.edit_message(chat_id, message_id, "Что хочешь изменить?")
        return

    if action != "confirm" or not session.parsed_intent:
        await tg.edit_message(chat_id, message_id, "Сессия устарела. Используйте /ask заново.")
        return

    try:
        cfg = _run_config_from_intent(session.parsed_intent)
        cfg.validate()
    except ValueError as exc:
        await tg.edit_message(chat_id, message_id, f"❌ Ошибка конфига: {escape(str(exc))}")
        return

    result = fire(config_to_text(cfg))
    await session_store.delete(chat_id)
    if result.get("dev_mode"):
        await tg.edit_message(chat_id, message_id, "🟡 <b>[dev] Рутина запущена</b>")
    elif "error" in result:
        await tg.edit_message(chat_id, message_id, f"❌ Ошибка запуска: {escape(result['error'])}")
    else:
        routine_session_id = result.get("claude_code_session_id", "?")
        await tg.edit_message(
            chat_id,
            message_id,
            f"🟢 <b>Рутина запущена</b>\nSession: <code>{escape(str(routine_session_id))}</code>",
        )


def _ask_confirmation(parsed: ParsedIntent) -> tuple[str, list[list[dict]]]:
    scenario = SCENARIOS[parsed.mode]
    lines = [
        "🔍 <b>Понял запрос</b>",
        "",
        f"Сценарий: <b>{escape(scenario.name)}</b>",
    ]
    params = parsed.params
    if parsed.mode == "icp_segment":
        lines.append(f"Сегменты: <b>{escape(', '.join(params.get('segments') or []))}</b>")
        lines.append(f"Лимит: <b>{escape(str(params.get('limit_per_segment', 5)))}</b>")
        lines.append(f"Стадии: <b>{escape(_stages_label(params.get('stages', 'full')))}</b>")
    elif parsed.mode == "single_company":
        lines.append(f"Компания: <b>{escape(str(params.get('company_name', '')))}</b>")
        if params.get("company_url"):
            lines.append(f"URL: <b>{escape(str(params['company_url']))}</b>")
        lines.append(f"Стадии: <b>{escape(_stages_label(params.get('stages', 'full')))}</b>")
    elif parsed.mode == "startup_research":
        if params.get("company_name"):
            lines.append(f"Компания: <b>{escape(str(params['company_name']))}</b>")
        if params.get("company_url"):
            lines.append(f"URL: <b>{escape(str(params['company_url']))}</b>")
        lines.append(f"Описание: <b>{escape(str(params.get('description', '')))}</b>")
        if params.get("focus_areas"):
            lines.append(f"Фокус: <b>{escape(', '.join(params['focus_areas']))}</b>")
    elif parsed.mode == "enrich_existing":
        segs = params.get("segments") or []
        lines.append(f"Сегменты: <b>{escape(', '.join(segs) or 'все сегменты')}</b>")
        lines.append(f"Лимит: <b>{escape(str(params.get('limit_per_segment', 30)))}</b> на сегмент")
        lines.append(f"Стадии: <b>{escape(_stages_label(params.get('stages', [])))}</b>")
        notion = params.get("notion_sync", True)
        lines.append(f"Notion sync: <b>{'да' if notion else 'нет'}</b>")

    keyboard = [
        [
            {"text": "🚀 Запустить", "callback_data": "a1:confirm"},
            {"text": "✏️ Уточнить", "callback_data": "a1:edit"},
        ],
        [{"text": "❌ Отмена", "callback_data": "a1:cancel"}],
    ]
    return "\n".join(lines), keyboard


def _run_config_from_intent(parsed: ParsedIntent) -> RunConfig:
    params = parsed.params
    if parsed.mode == "icp_segment":
        return RunConfig(
            run_mode="icp_segment",
            segments=list(params.get("segments") or []),
            limit_per_segment=int(params.get("limit_per_segment", DEFAULT_LIMIT_PER_SEGMENT)),
            stages=params.get("stages", "full"),
            dry_run=bool(params.get("dry_run", False)),
            notion_sync=bool(params.get("notion_sync", True)),
        )
    if parsed.mode == "single_company":
        return RunConfig(
            run_mode="single_company",
            segments=[],
            limit_per_segment=DEFAULT_LIMIT_PER_SEGMENT,
            stages=params.get("stages", "full"),
            notion_sync=bool(params.get("notion_sync", True)),
            company_name=str(params.get("company_name", "")),
            company_url=str(params.get("company_url", "")),
        )
    if parsed.mode == "startup_research":
        return RunConfig(
            run_mode="startup_research",
            segments=[],
            limit_per_segment=DEFAULT_LIMIT_PER_SEGMENT,
            stages=params.get("stages", "full"),
            notion_sync=bool(params.get("notion_sync", True)),
            company_name=str(params.get("company_name", "")),
            company_url=str(params.get("company_url", "")),
            startup_description=str(params.get("description", "")),
            focus_areas=list(params.get("focus_areas") or []),
        )
    if parsed.mode == "enrich_existing":
        return RunConfig(
            run_mode="enrich_existing",
            segments=list(params.get("segments") or []),
            limit_per_segment=int(params.get("limit_per_segment", 30)),
            stages=list(params.get("stages") or ENRICH_DEFAULT_STAGES),
            dry_run=bool(params.get("dry_run", False)),
            notion_sync=bool(params.get("notion_sync", True)),
        )
    raise ValueError(f"unknown run mode: {parsed.mode}")


def _stages_label(stages: str | list[str]) -> str:
    if stages == "full":
        return "полный pipeline"
    if isinstance(stages, list):
        return ", ".join(stages)
    return str(stages)


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


async def _handle_notion_sync_command(chat_id: str, tg: "TelegramSender") -> None:
    await _run_notion_sync_and_notify(notify_chat_id=chat_id, tg=tg)


def _run_notion_sync_blocking() -> dict:
    """Runs in thread pool; sync uses Notion API and Supabase directly."""
    from notion_sync import NotionSync, _make_db, _make_notion

    sync = NotionSync(notion=_make_notion(), db=_make_db())
    companies = sync.sync_forward("companies")
    contacts = sync.sync_forward("contacts")
    return {"companies": companies, "contacts": contacts}


async def _run_notion_sync_and_notify(
    notify_chat_id: str | None = None,
    tg: "TelegramSender | None" = None,
) -> None:
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(None, _run_notion_sync_blocking)

    if notify_chat_id is None:
        return

    sender = tg or TelegramSender()
    companies_count = _notion_sync_changed_count(result["companies"])
    contacts_count = _notion_sync_changed_count(result["contacts"])
    await sender.send(
        notify_chat_id,
        f"✅ Синхронизировано: {companies_count} компаний, {contacts_count} контактов",
    )


def _notion_sync_changed_count(result: dict[str, Any]) -> int:
    return int(result.get("created", 0) or 0) + int(result.get("updated", 0) or 0)


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
            "Этот бот запускает Kvetio Agent Pipeline: агент ищет компании по ICP-сегментам, проверяет релевантность, обогащает данные и готовит результат для Supabase/Notion.",
            "",
            "Бот сам не выполняет pipeline. Он собирает параметры и отправляет запуск в Claude Code Routine через /fire. После завершения рутина сама присылает сводку в Telegram.",
            "",
            "/run — мастер запуска с выбором параметров",
            "/ask <запрос> — запуск через свободный текст",
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
            "/run — мастер запуска с выбором сегментов, лимита, stages и флагов",
            "/refill — дозаполнение существующих компаний с неполными данными",
            "/ask <запрос> — разобрать свободный текст и запустить подходящий сценарий",
            "",
            "<b>Статус и отчеты</b>",
            "/status — текущий активный ран",
            "/last [n] — последние n запусков, максимум 20",
            "/digest [limit] — дайджест",
            "/hot [limit] — горячие лиды",
            "/stale [limit] — очередь на проверку",
            "/notion_sync — синхронизация Supabase → Notion",
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
                data = resp.json()
                if not data.get("ok"):
                    logger.error("Telegram API %s error %s: %s", method, resp.status_code, data)
                return data
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


def _verify_sync_secret(authorization: str) -> None:
    expected = os.environ.get("SYNC_SECRET", "")
    if not expected or authorization != f"Bearer {expected}":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="invalid sync secret",
        )


if __name__ == "__main__":
    import uvicorn

    level = os.environ.get("KVETIO_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
