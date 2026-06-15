"""RunConfig, pipeline_runs CRUD, status machine, and concurrency lock.

Usage:
    from bot.runs import RunConfig, RunsStore
    store = RunsStore(supabase_client)
    run_id = store.enqueue(config, trigger_type="manual", triggered_by="chat:123")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

logger = logging.getLogger(__name__)

# Valid pipeline stages
VALID_STAGES = frozenset(
    ["discovery", "relevance", "scoring", "enrichment", "analysis", "conclusions"]
)
VALID_SEGMENTS = frozenset(
    [
        "medical-imaging",
        "autonomous-vehicles",
        "speech-and-audio",
        "generative-ai",
        "agriculture-ai",
        "robotics-ai",
        "video-photo-ai",
    ]
)

RunStatus = Literal["draft", "queued", "running", "succeeded", "failed", "cancelled"]
TriggerType = Literal["manual", "scheduled", "api"]


@dataclass
class RunConfig:
    segments: list[str]
    limit_per_segment: int
    stages: str | list[str]       # "full" or subset list
    dry_run: bool = False
    notion_sync: bool = True
    triggered_by: str = ""
    trigger_type: TriggerType = "manual"

    def validate(self) -> None:
        if not self.segments:
            raise ValueError("segments must be non-empty")
        unknown = set(self.segments) - VALID_SEGMENTS
        if unknown:
            raise ValueError(f"unknown segments: {unknown}")
        if not (1 <= self.limit_per_segment <= 200):
            raise ValueError("limit_per_segment must be between 1 and 200")
        if self.stages != "full":
            if not isinstance(self.stages, list) or not self.stages:
                raise ValueError("stages must be 'full' or a non-empty list")
            unknown_stages = set(self.stages) - VALID_STAGES
            if unknown_stages:
                raise ValueError(f"unknown stages: {unknown_stages}")
        if self.trigger_type not in ("manual", "scheduled", "api"):
            raise ValueError(f"invalid trigger_type: {self.trigger_type}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "segments": self.segments,
            "limit_per_segment": self.limit_per_segment,
            "stages": self.stages,
            "dry_run": self.dry_run,
            "notion_sync": self.notion_sync,
            "triggered_by": self.triggered_by,
            "trigger_type": self.trigger_type,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunConfig":
        return cls(
            segments=data["segments"],
            limit_per_segment=data["limit_per_segment"],
            stages=data.get("stages", "full"),
            dry_run=data.get("dry_run", False),
            notion_sync=data.get("notion_sync", True),
            triggered_by=data.get("triggered_by", ""),
            trigger_type=data.get("trigger_type", "manual"),
        )


class RunsStore:
    """CRUD and status machine for pipeline_runs table."""

    HEARTBEAT_TIMEOUT_SEC = 300  # 5 min — stale runs auto-failed

    def __init__(self, client: Any) -> None:
        self._db = client

    # ── Enqueue ──────────────────────────────────────────────────────────────

    def enqueue(
        self,
        config: RunConfig,
        *,
        trigger_type: TriggerType = "manual",
        triggered_by: str = "",
        tg_chat_id: str | None = None,
    ) -> str:
        """Insert a queued run. Returns the run UUID string."""
        config.validate()
        row: dict[str, Any] = {
            "trigger_type": trigger_type,
            "triggered_by": triggered_by,
            "config": config.to_dict(),
            "status": "queued",
        }
        if tg_chat_id:
            row["tg_chat_id"] = tg_chat_id
        result = self._db.table("pipeline_runs").insert(row).execute()
        run_id: str = result.data[0]["id"]
        logger.info("Enqueued run %s (%s)", run_id, trigger_type)
        return run_id

    # ── Acquire lock (one running at a time) ─────────────────────────────────

    def try_start_next(self) -> dict[str, Any] | None:
        """Claim the oldest queued run if no run is currently running.

        Returns the run row dict, or None if nothing to start or lock is held.
        """
        active = (
            self._db.table("pipeline_runs")
            .select("id")
            .eq("status", "running")
            .execute()
        )
        if active.data:
            return None

        self._expire_stale_runs()

        queued = (
            self._db.table("pipeline_runs")
            .select("*")
            .eq("status", "queued")
            .order("queued_at", desc=False)
            .limit(1)
            .execute()
        )
        if not queued.data:
            return None

        run = queued.data[0]
        now = _now_iso()
        self._db.table("pipeline_runs").update(
            {"status": "running", "started_at": now, "heartbeat_at": now}
        ).eq("id", run["id"]).eq("status", "queued").execute()

        updated = (
            self._db.table("pipeline_runs")
            .select("*")
            .eq("id", run["id"])
            .eq("status", "running")
            .execute()
        )
        if not updated.data:
            return None  # lost the race
        logger.info("Started run %s", run["id"])
        return updated.data[0]

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    def heartbeat(self, run_id: str) -> None:
        self._db.table("pipeline_runs").update(
            {"heartbeat_at": _now_iso()}
        ).eq("id", run_id).execute()

    # ── Status transitions ────────────────────────────────────────────────────

    def finish(self, run_id: str, summary: dict[str, Any]) -> None:
        self._db.table("pipeline_runs").update(
            {
                "status": "succeeded",
                "finished_at": _now_iso(),
                "summary": summary,
            }
        ).eq("id", run_id).execute()
        logger.info("Run %s succeeded", run_id)

    def fail(self, run_id: str, error: str) -> None:
        self._db.table("pipeline_runs").update(
            {
                "status": "failed",
                "finished_at": _now_iso(),
                "error": error[:2000],
            }
        ).eq("id", run_id).execute()
        logger.warning("Run %s failed: %s", run_id, error[:200])

    def cancel(self, run_id: str) -> bool:
        """Cancel a queued or running run. Returns True if cancelled."""
        result = (
            self._db.table("pipeline_runs")
            .update({"status": "cancelled", "finished_at": _now_iso()})
            .eq("id", run_id)
            .in_("status", ["queued", "running"])
            .execute()
        )
        cancelled = bool(result.data)
        if cancelled:
            logger.info("Cancelled run %s", run_id)
        return cancelled

    # ── Queries ───────────────────────────────────────────────────────────────

    def get(self, run_id: str) -> dict[str, Any] | None:
        result = (
            self._db.table("pipeline_runs").select("*").eq("id", run_id).execute()
        )
        return result.data[0] if result.data else None

    def get_active(self) -> dict[str, Any] | None:
        result = (
            self._db.table("pipeline_runs")
            .select("*")
            .in_("status", ["queued", "running"])
            .order("queued_at", desc=False)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def list_recent(self, limit: int = 5) -> list[dict[str, Any]]:
        result = (
            self._db.table("pipeline_runs")
            .select("id,status,trigger_type,triggered_by,queued_at,finished_at,summary,error")
            .order("queued_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []

    def set_tg_message_id(self, run_id: str, message_id: int) -> None:
        self._db.table("pipeline_runs").update(
            {"tg_message_id": message_id}
        ).eq("id", run_id).execute()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _expire_stale_runs(self) -> None:
        """Mark running runs with stale heartbeat as failed."""
        from datetime import timedelta

        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=self.HEARTBEAT_TIMEOUT_SEC
        )
        self._db.table("pipeline_runs").update(
            {
                "status": "failed",
                "finished_at": _now_iso(),
                "error": "heartbeat timeout — worker may have crashed",
            }
        ).eq("status", "running").lt("heartbeat_at", cutoff.isoformat()).execute()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
