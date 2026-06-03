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
