"""Supabase-backed TTL cache for GitHub /orgs/{login} API responses."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from supabase import Client, create_client

logger = logging.getLogger(__name__)

_TABLE = "github_org_cache"
_REPO_ROOT = Path(__file__).parent.parent

load_dotenv(_REPO_ROOT / ".env")


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_cached_at(value: str) -> datetime:
    cached_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)
    return cached_at


class OrgCache:
    """Read/write cache for GitHub organization metadata."""

    def __init__(self, ttl_days: int = 30) -> None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL и SUPABASE_KEY должны быть в .env")
        self._client: Client = create_client(url, key)
        self._ttl = timedelta(days=ttl_days)

    def get(self, org_login: str) -> dict | None:
        """Return cached org data if present and fresh; otherwise None."""
        res = (
            self._client.table(_TABLE)
            .select("data,cached_at")
            .eq("org_login", org_login)
            .maybe_single()
            .execute()
        )
        if not res.data:
            return None

        cached_at = _parse_cached_at(res.data["cached_at"])
        age = _utcnow() - cached_at
        if age > self._ttl:
            logger.debug("OrgCache stale for %s (age=%s)", org_login, age)
            return None

        logger.debug("OrgCache hit for %s", org_login)
        return res.data["data"]

    def set(self, org_login: str, data: dict) -> None:
        """Upsert org data and refresh cached_at."""
        row = {
            "org_login": org_login,
            "data": data,
            "cached_at": _utcnow().isoformat(),
        }
        self._client.table(_TABLE).upsert(row, on_conflict="org_login").execute()
        logger.debug("OrgCache stored %s", org_login)
