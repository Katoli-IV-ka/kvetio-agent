"""RunConfig dataclass and constants for pipeline configuration.

This module contains pure configuration: data types, validation rules, and the
RunConfig dataclass. It has no external dependencies and is safe to import
without triggering database initialization.

Usage:
    from bot.config import RunConfig, VALID_STAGES, VALID_SEGMENTS
    cfg = RunConfig(segments=["medical-imaging"], limit_per_segment=30)
    cfg.validate()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

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
