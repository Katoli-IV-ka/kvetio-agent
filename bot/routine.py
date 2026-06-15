"""Claude Code Routine trigger client."""

from __future__ import annotations

import logging
import os

import httpx

from bot.config import RunConfig

logger = logging.getLogger(__name__)


def config_to_text(cfg: RunConfig) -> str:
    """Serialize RunConfig to a text string for the routine's `text` field."""
    stages = cfg.stages if cfg.stages == "full" else ",".join(cfg.stages)
    return (
        f"segments={','.join(cfg.segments)}; "
        f"limit={cfg.limit_per_segment}; "
        f"stages={stages}; "
        f"dry_run={'true' if cfg.dry_run else 'false'}; "
        f"notion_sync={'true' if cfg.notion_sync else 'false'}"
    )


def fire(text: str = "") -> dict:
    """POST to the Claude Code Routine /fire endpoint.

    Returns the response dict (contains claude_code_session_id on success).
    Returns {"dev_mode": True} when credentials are not configured.
    Returns {"error": "..."} on failure.
    """
    url = os.environ.get("ROUTINE_FIRE_URL", "")
    token = os.environ.get("ROUTINE_TOKEN", "")

    if not url or not token:
        logger.warning("ROUTINE_FIRE_URL or ROUTINE_TOKEN not set — dev mode, skipping fire")
        return {"dev_mode": True, "text": text}

    headers = {
        "Authorization": f"Bearer {token}",
        "anthropic-beta": "experimental-cc-routine-2026-04-01",
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    try:
        with httpx.Client(timeout=30) as client:
            resp = client.post(url, json={"text": text}, headers=headers)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Routine fire HTTP error %s: %s",
            exc.response.status_code,
            exc.response.text[:500],
        )
        return {"error": f"HTTP {exc.response.status_code}", "detail": exc.response.text[:200]}
    except Exception as exc:  # noqa: BLE001
        logger.error("Routine fire failed: %s", exc)
        return {"error": str(exc)}
