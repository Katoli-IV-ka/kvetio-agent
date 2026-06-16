"""Named RunConfig presets — CRUD and default resolution.

Usage:
    from bot.presets import PresetsStore
    store = PresetsStore(supabase_client)
    preset = store.get("nightly-full")
"""

from __future__ import annotations

import logging
from typing import Any

from bot.config import DEFAULT_LIMIT_PER_SEGMENT

logger = logging.getLogger(__name__)

# Seed presets created on first use if no presets exist
DEFAULT_SEED_PRESETS = [
    {
        "name": "nightly-full",
        "config": {
            "segments": [
                "medical-imaging", "autonomous-vehicles", "speech-and-audio",
                "generative-ai", "agriculture-ai", "robotics-ai", "video-photo-ai",
            ],
            "limit_per_segment": DEFAULT_LIMIT_PER_SEGMENT,
            "stages": "full",
            "dry_run": False,
            "notion_sync": True,
        },
        "is_default": True,
    },
    {
        "name": "quick-2seg",
        "config": {
            "segments": ["medical-imaging", "generative-ai"],
            "limit_per_segment": 10,
            "stages": "full",
            "dry_run": False,
            "notion_sync": False,
        },
        "is_default": False,
    },
    {
        "name": "dry-smoke",
        "config": {
            "segments": ["medical-imaging"],
            "limit_per_segment": 5,
            "stages": ["discovery", "relevance"],
            "dry_run": True,
            "notion_sync": False,
        },
        "is_default": False,
    },
]


class PresetsStore:
    def __init__(self, client: Any) -> None:
        self._db = client

    def get(self, name: str) -> dict[str, Any] | None:
        result = (
            self._db.table("bot_presets")
            .select("*")
            .eq("name", name)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def get_default(self) -> dict[str, Any] | None:
        result = (
            self._db.table("bot_presets")
            .select("*")
            .eq("is_default", True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def list_all(self) -> list[dict[str, Any]]:
        result = self._db.table("bot_presets").select("*").order("name").execute()
        return result.data or []

    def save(
        self,
        name: str,
        config: dict[str, Any],
        owner: str = "",
        is_default: bool = False,
    ) -> None:
        if is_default:
            self._db.table("bot_presets").update({"is_default": False}).neq(
                "name", name
            ).execute()
        self._db.table("bot_presets").upsert(
            {
                "name": name,
                "config": config,
                "owner": owner,
                "is_default": is_default,
            },
            on_conflict="name",
        ).execute()
        logger.info("Saved preset %r (default=%s)", name, is_default)

    def delete(self, name: str) -> bool:
        result = self._db.table("bot_presets").delete().eq("name", name).execute()
        return bool(result.data)

    def set_default(self, name: str) -> bool:
        self._db.table("bot_presets").update({"is_default": False}).neq(
            "name", name
        ).execute()
        result = (
            self._db.table("bot_presets")
            .update({"is_default": True})
            .eq("name", name)
            .execute()
        )
        return bool(result.data)

    def ensure_seed_presets(self) -> None:
        """Create default seed presets if none exist yet."""
        existing = self.list_all()
        if existing:
            return
        for preset in DEFAULT_SEED_PRESETS:
            try:
                self._db.table("bot_presets").insert(preset).execute()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Could not seed preset %r: %s", preset["name"], exc)
        logger.info("Seeded %d presets", len(DEFAULT_SEED_PRESETS))
