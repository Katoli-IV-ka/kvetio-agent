"""Idempotent setWebhook for Telegram Bot API.

Run once after deploy:
    python -m bot.set_webhook

Environment variables:
    TELEGRAM_BOT_TOKEN
    TELEGRAM_WEBHOOK_SECRET
    BOT_WEBHOOK_URL            — e.g. https://<app>.up.railway.app/telegram/webhook
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)


def set_webhook(url: str | None = None) -> bool:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    webhook_url = url or os.environ.get("BOT_WEBHOOK_URL", "")

    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return False
    if not webhook_url:
        logger.error("BOT_WEBHOOK_URL not set")
        return False

    api = f"https://api.telegram.org/bot{token}/setWebhook"
    payload: dict = {"url": webhook_url, "allowed_updates": ["message", "callback_query"]}
    if secret:
        payload["secret_token"] = secret

    try:
        resp = httpx.post(api, json=payload, timeout=15)
        data = resp.json()
        if data.get("ok"):
            logger.info("Webhook set: %s", webhook_url)
            return True
        logger.error("setWebhook failed: %s", data)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error("setWebhook error: %s", exc)
        return False


def get_webhook_info() -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return {}
    try:
        resp = httpx.get(f"https://api.telegram.org/bot{token}/getWebhookInfo", timeout=10)
        return resp.json().get("result", {})
    except Exception:  # noqa: BLE001
        return {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    info = get_webhook_info()
    current_url = info.get("url", "")
    desired_url = os.environ.get("BOT_WEBHOOK_URL", "")

    if current_url == desired_url and desired_url:
        logger.info("Webhook already set to %s — skipping", current_url)
        sys.exit(0)

    ok = set_webhook()
    sys.exit(0 if ok else 1)
