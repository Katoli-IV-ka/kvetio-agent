"""Claude Code Routine trigger client."""

from __future__ import annotations

import logging
import os

import httpx

from bot.config import RunConfig

logger = logging.getLogger(__name__)


def _routine_env(name: str) -> str:
    """Read Routine env values and tolerate common copy-paste wrappers."""
    return os.environ.get(name, "").strip().strip('"').strip("'")


def config_to_text(cfg: RunConfig) -> str:
    """Serialize RunConfig to a text string for the routine's `text` field."""
    stages = cfg.stages if cfg.stages == "full" else ",".join(cfg.stages)
    if cfg.run_mode == "icp_segment":
        return (
            "mode=icp_segment; "
            f"segments={','.join(cfg.segments)}; "
            f"limit={cfg.limit_per_segment}; "
            f"stages={stages}; "
            f"dry_run={'true' if cfg.dry_run else 'false'}; "
            f"notion_sync={'true' if cfg.notion_sync else 'false'}"
        )

    if cfg.run_mode == "single_company":
        parts = ["mode=single_company", f"company={cfg.company_name}"]
        if cfg.company_url:
            parts.append(f"company_url={cfg.company_url}")
        parts.extend(
            [
                f"stages={stages}",
                f"notion_sync={'true' if cfg.notion_sync else 'false'}",
            ]
        )
        return "; ".join(parts)

    if cfg.run_mode == "startup_research":
        parts = ["mode=startup_research", f"description={cfg.startup_description}"]
        if cfg.company_name:
            parts.append(f"company={cfg.company_name}")
        if cfg.company_url:
            parts.append(f"company_url={cfg.company_url}")
        if cfg.focus_areas:
            parts.append(f"focus_areas={','.join(cfg.focus_areas)}")
        parts.append(f"notion_sync={'true' if cfg.notion_sync else 'false'}")
        return "; ".join(parts)

    if cfg.run_mode == "enrich_existing":
        stages = cfg.stages if cfg.stages == "full" else ",".join(cfg.stages)
        parts = [
            "mode=enrich_existing",
            f"segments={','.join(cfg.segments)}" if cfg.segments else "segments=",
            f"limit={cfg.limit_per_segment}",
            f"stages={stages}",
            f"dry_run={'true' if cfg.dry_run else 'false'}",
            f"notion_sync={'true' if cfg.notion_sync else 'false'}",
        ]
        return "; ".join(parts)

    raise ValueError(f"unsupported run_mode: {cfg.run_mode}")


def fire(text: str = "") -> dict:
    """POST to the Claude Code Routine /fire endpoint.

    Returns the response dict (contains claude_code_session_id on success).
    Returns {"dev_mode": True} when credentials are not configured.
    Returns {"error": "..."} on failure.
    """
    url = _routine_env("ROUTINE_FIRE_URL")
    token = _routine_env("ROUTINE_TOKEN")

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
        status = exc.response.status_code
        detail = exc.response.text[:200]
        logger.error(
            "Routine fire HTTP error %s: %s",
            status,
            exc.response.text[:500],
        )
        if status == 401:
            return {
                "error": "HTTP 401: ROUTINE_TOKEN rejected by Anthropic",
                "detail": detail,
                "hint": (
                    "Regenerate the API trigger token in claude.ai/code Routine "
                    "settings and update ROUTINE_TOKEN in the bot environment."
                ),
            }
        return {"error": f"HTTP {status}", "detail": detail}
    except Exception as exc:  # noqa: BLE001
        logger.error("Routine fire failed: %s", exc)
        return {"error": str(exc)}
