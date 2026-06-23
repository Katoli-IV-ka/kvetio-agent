"""Long-polling runner for local development.

Удаляет webhook (если установлен), затем опрашивает Telegram через getUpdates.
Переиспользует _handle_update из gateway.py — логика обработки не дублируется.

Run:
    python -m bot.polling

Environment variables:
    TELEGRAM_BOT_TOKEN
    KVETIO_LOG_LEVEL   — default INFO
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

logger = logging.getLogger(__name__)

_BASE = f"https://api.telegram.org/bot{os.environ.get('TELEGRAM_BOT_TOKEN', '')}"
_POLL_TIMEOUT = 30  # long-poll timeout in seconds


async def _delete_webhook() -> None:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{_BASE}/deleteWebhook", json={"drop_pending_updates": False})
        data = resp.json()
        if data.get("ok"):
            logger.info("Webhook deleted")
        else:
            logger.warning("deleteWebhook: %s", data)


async def _get_updates(offset: int) -> list[dict]:
    async with httpx.AsyncClient(timeout=_POLL_TIMEOUT + 5) as client:
        try:
            resp = await client.post(
                f"{_BASE}/getUpdates",
                json={
                    "offset": offset,
                    "timeout": _POLL_TIMEOUT,
                    "allowed_updates": ["message", "callback_query"],
                },
            )
            data = resp.json()
            if not data.get("ok"):
                logger.error("getUpdates error: %s", data)
                return []
            return data.get("result", [])
        except httpx.ReadTimeout:
            return []
        except Exception as exc:  # noqa: BLE001
            logger.error("getUpdates failed: %s", exc)
            await asyncio.sleep(3)
            return []


async def run_polling() -> None:
    try:
        from bot.gateway import _handle_update  # when run as `python -m bot.polling`
    except ModuleNotFoundError:
        from gateway import _handle_update  # when run directly from bot/

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)

    await _delete_webhook()
    logger.info("Polling started — Ctrl+C to stop")

    offset = 0
    while True:
        updates = await _get_updates(offset)
        for update in updates:
            update_id = update.get("update_id", 0)
            offset = update_id + 1
            try:
                await _handle_update(update)
            except Exception as exc:  # noqa: BLE001
                logger.error("Update %s handling error: %s", update_id, exc, exc_info=True)


def main() -> None:
    level = os.environ.get("KVETIO_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    loop = asyncio.new_event_loop()

    def _shutdown(*_):
        logger.info("Shutting down polling...")
        loop.stop()

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    try:
        loop.run_until_complete(run_polling())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
