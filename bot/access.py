"""Allowlist and role management from bot_users table.

Usage:
    from bot.access import AccessStore, Role
    access = AccessStore(supabase_client)
    if not access.is_allowed(chat_id):
        return  # ignore
    if access.is_admin(chat_id):
        ...
"""

from __future__ import annotations

import logging
from typing import Any, Literal

logger = logging.getLogger(__name__)

Role = Literal["admin", "viewer"]

ADMIN_COMMANDS = frozenset(["/run", "/quickrun", "/cancel", "/presets"])


class AccessStore:
    """Allowlist and role checks backed by bot_users table."""

    def __init__(self, client: Any) -> None:
        self._db = client

    def is_allowed(self, chat_id: str) -> bool:
        user = self._get_user(chat_id)
        return bool(user and user.get("active"))

    def is_admin(self, chat_id: str) -> bool:
        user = self._get_user(chat_id)
        return bool(user and user.get("active") and user.get("role") == "admin")

    def get_role(self, chat_id: str) -> Role | None:
        user = self._get_user(chat_id)
        if not user or not user.get("active"):
            return None
        return user.get("role", "viewer")  # type: ignore[return-value]

    def requires_admin(self, command: str) -> bool:
        return command in ADMIN_COMMANDS

    def add_user(self, chat_id: str, username: str = "", role: Role = "viewer") -> None:
        self._db.table("bot_users").upsert(
            {
                "chat_id": chat_id,
                "username": username,
                "role": role,
                "active": True,
            },
            on_conflict="chat_id",
        ).execute()
        logger.info("Added user %s (role=%s)", chat_id, role)

    def deactivate_user(self, chat_id: str) -> None:
        self._db.table("bot_users").update({"active": False}).eq(
            "chat_id", chat_id
        ).execute()
        logger.info("Deactivated user %s", chat_id)

    def list_users(self) -> list[dict[str, Any]]:
        result = self._db.table("bot_users").select("*").execute()
        return result.data or []

    def _get_user(self, chat_id: str) -> dict[str, Any] | None:
        result = (
            self._db.table("bot_users")
            .select("chat_id,role,active")
            .eq("chat_id", str(chat_id))
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
