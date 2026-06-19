"""In-memory session store for NLP clarification dialogs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Callable, Literal

from bot.intent_agent import ParsedIntent


@dataclass
class BotSession:
    chat_id: str
    messages: list[dict]
    parsed_intent: ParsedIntent | None
    state: Literal["clarifying", "confirming"]
    clarification_count: int
    created_at: datetime


class SessionStore:
    def __init__(
        self,
        ttl: timedelta = timedelta(minutes=30),
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._sessions: dict[str, BotSession] = {}
        self._ttl = ttl
        self._now = now or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()

    async def get(self, chat_id: str) -> BotSession | None:
        async with self._lock:
            self._cleanup_locked()
            return self._sessions.get(chat_id)

    async def set(self, session: BotSession) -> None:
        async with self._lock:
            self._cleanup_locked()
            self._sessions[session.chat_id] = session

    async def delete(self, chat_id: str) -> None:
        async with self._lock:
            self._cleanup_locked()
            self._sessions.pop(chat_id, None)

    def _cleanup_locked(self) -> None:
        cutoff = self._now() - self._ttl
        expired = [
            chat_id
            for chat_id, session in self._sessions.items()
            if session.created_at < cutoff
        ]
        for chat_id in expired:
            self._sessions.pop(chat_id, None)
