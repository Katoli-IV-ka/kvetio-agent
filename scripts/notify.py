"""Telegram-уведомления через Bot API.

Требует переменных окружения (из .env):
    TELEGRAM_BOT_TOKEN=123456:ABC...
    TELEGRAM_CHAT_ID=123456789

CLI:
    python scripts/notify.py --message "Новый Hot-лид: acme.ai (скор 72)"
    python scripts/notify.py --run-summary '{"found": 12, "enriched": 8, "errors": 0}'
    python scripts/notify.py --hot-lead '{"name": "Acme", "domain": "acme.ai", "score": 72}'
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent / ".env")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def send(text: str, *, parse_mode: str = "HTML") -> bool:
    """Отправляет сообщение в Telegram. Возвращает True при успехе."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.error("TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID должны быть в .env")
        return False

    url = TELEGRAM_API.format(token=token)
    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Telegram: ошибка отправки — %s", exc)
        return False


def notify_hot_lead(name: str, domain: str, score: int, segment: str = "") -> bool:
    seg_tag = f" <i>({segment})</i>" if segment else ""
    text = (
        f"🔥 <b>Новый Hot-лид</b>{seg_tag}\n"
        f"<b>{name}</b> — {domain}\n"
        f"Скор: <b>{score}</b>\n"
        f"🔗 https://{domain}"
    )
    return send(text)


def notify_run_summary(
    task_name: str,
    *,
    found: int,
    enriched: int,
    errors: int,
) -> bool:
    status = "✅" if errors == 0 else "⚠️"
    text = (
        f"{status} <b>{task_name}</b> завершён\n"
        f"Найдено: {found} | Обогащено: {enriched} | Ошибок: {errors}"
    )
    return send(text)


def notify_error(task_name: str, error: str) -> bool:
    text = f"❌ <b>{task_name}</b> упал с ошибкой:\n<code>{error[:400]}</code>"
    return send(text)


def notify_pipeline_summary(
    run_id: str,
    *,
    trigger_type: str = "manual",
    triggered_by: str = "",
    segments: list[str] | None = None,
    found: int = 0,
    qualified: int = 0,
    errors: int = 0,
    error_details: list[dict] | None = None,
    hot_leads: list[dict] | None = None,
    duration_sec: int = 0,
    chat_ids: list[str] | None = None,
) -> int:
    """Send pipeline summary to one or more chats. Returns count of successful sends.

    If chat_ids is None, falls back to TELEGRAM_CHAT_ID env var.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN не задан")
        return 0

    fallback_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    targets = chat_ids if chat_ids else ([fallback_chat] if fallback_chat else [])
    if not targets:
        logger.warning("notify_pipeline_summary: нет получателей")
        return 0

    run_id_short = run_id[:8] if len(run_id) > 8 else run_id
    status_icon = "✅" if errors == 0 else "⚠️"
    dur = f" · {duration_sec // 60}m {duration_sec % 60}s" if duration_sec else ""
    seg_str = ", ".join(segments or []) or "—"

    lines = [
        f"{status_icon} <b>Pipeline завершён</b> · ран {run_id_short}{dur}",
        f"Триггер: {trigger_type}" + (f" ({triggered_by})" if triggered_by else ""),
        f"Сегменты: {seg_str}",
        "",
        f"Найдено: {found} · qualified: {qualified} · ошибок: {errors}",
    ]

    if hot_leads:
        lines.append("")
        lines.append("🔥 <b>Топ Hot:</b>")
        for i, lead in enumerate(hot_leads[:5], 1):
            domain = lead.get("domain", "")
            score = lead.get("score", 0)
            seg = lead.get("icp_segment", "")
            lines.append(f"{i}. {domain} — {score}" + (f" ({seg})" if seg else ""))

    if error_details:
        lines.append("")
        lines.append(f"⚠️ <b>Ошибки ({errors}):</b>")
        for e in (error_details or [])[:3]:
            stage = e.get("stage", "?")
            seg = e.get("segment", "?")
            err = (e.get("error") or "")[:60]
            lines.append(f"  {stage}/{seg} — {err}")

    lines.append("")
    lines.append(f"🔗 run_id: <code>{run_id}</code> · /last для истории")
    text = "\n".join(lines)

    url = TELEGRAM_API.format(token=token)
    sent = 0
    for chat_id in targets:
        try:
            resp = httpx.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                timeout=10,
            )
            resp.raise_for_status()
            sent += 1
        except Exception as exc:  # noqa: BLE001
            logger.error("Telegram sendMessage to %s failed: %s", chat_id, exc)
    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Telegram-уведомления Kvetio")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--message", help="Произвольный текст")
    group.add_argument("--hot-lead", metavar="JSON",
                       help='JSON: {"name":"...","domain":"...","score":72}')
    group.add_argument("--run-summary", metavar="JSON",
                       help='JSON: {"task":"...","found":N,"enriched":N,"errors":N}')
    group.add_argument("--error", metavar="JSON",
                       help='JSON: {"task":"...","error":"..."}')
    args = parser.parse_args()

    ok = False
    if args.message:
        ok = send(args.message)
    elif args.hot_lead:
        d = json.loads(args.hot_lead)
        ok = notify_hot_lead(
            d["name"], d["domain"], d["score"], d.get("segment", "")
        )
    elif args.run_summary:
        d = json.loads(args.run_summary)
        ok = notify_run_summary(
            d.get("task", "Task"),
            found=d.get("found", 0),
            enriched=d.get("enriched", 0),
            errors=d.get("errors", 0),
        )
    elif args.error:
        d = json.loads(args.error)
        ok = notify_error(d.get("task", "Task"), d.get("error", ""))

    sys.exit(0 if ok else 1)
