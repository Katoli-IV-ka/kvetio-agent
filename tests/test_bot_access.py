"""Tests for allowlist and role management."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.access import AccessStore, ADMIN_COMMANDS


def _make_store(user_row: dict | None = None) -> tuple[AccessStore, MagicMock]:
    client = MagicMock()
    store = AccessStore(client)
    data = [user_row] if user_row else []
    (
        client.table.return_value
        .select.return_value
        .eq.return_value
        .limit.return_value
        .execute.return_value.data
    ) = data
    return store, client


class TestAccessStore:
    def test_allowed_active_user(self) -> None:
        store, _ = _make_store({"chat_id": "1", "role": "viewer", "active": True})
        assert store.is_allowed("1") is True

    def test_blocked_inactive_user(self) -> None:
        store, _ = _make_store({"chat_id": "1", "role": "admin", "active": False})
        assert store.is_allowed("1") is False

    def test_unknown_user_not_allowed(self) -> None:
        store, _ = _make_store(None)
        assert store.is_allowed("999") is False

    def test_admin_role(self) -> None:
        store, _ = _make_store({"chat_id": "1", "role": "admin", "active": True})
        assert store.is_admin("1") is True

    def test_viewer_not_admin(self) -> None:
        store, _ = _make_store({"chat_id": "1", "role": "viewer", "active": True})
        assert store.is_admin("1") is False

    def test_get_role_active_viewer(self) -> None:
        store, _ = _make_store({"chat_id": "1", "role": "viewer", "active": True})
        assert store.get_role("1") == "viewer"

    def test_get_role_inactive_returns_none(self) -> None:
        store, _ = _make_store({"chat_id": "1", "role": "admin", "active": False})
        assert store.get_role("1") is None

    def test_admin_commands(self) -> None:
        assert store_any().requires_admin("/run") is True
        assert store_any().requires_admin("/cancel") is True
        assert store_any().requires_admin("/status") is False
        assert store_any().requires_admin("/last") is False
        assert store_any().requires_admin("/help") is False

    def test_add_user_calls_upsert(self) -> None:
        store, client = _make_store()
        client.table.return_value.upsert.return_value.execute.return_value.data = []
        store.add_user("42", username="alice", role="admin")
        upsert_call = client.table.return_value.upsert
        row = upsert_call.call_args[0][0]
        assert row["chat_id"] == "42"
        assert row["role"] == "admin"
        assert row["active"] is True


def store_any() -> AccessStore:
    return AccessStore(MagicMock())
