"""RunConfig dataclass and constants for pipeline configuration.

This module contains pure configuration: data types, validation rules, and the
RunConfig dataclass. It has no external dependencies and is safe to import
without triggering database initialization.

Usage:
    from bot.config import DEFAULT_LIMIT_PER_SEGMENT, RunConfig, VALID_STAGES, VALID_SEGMENTS
    cfg = RunConfig(
        segments=["medical-imaging"],
        limit_per_segment=DEFAULT_LIMIT_PER_SEGMENT,
        stages="full",
    )
    cfg.validate()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Valid pipeline stages
VALID_STAGES = frozenset(
    ["discovery", "relevance", "scoring", "enrichment", "analysis", "conclusions"]
)
ENRICH_DEFAULT_STAGES = [
    "relevance",
    "scoring",
    "enrichment",
    "analysis",
    "conclusions",
]
ENRICH_VALID_STAGES = frozenset(ENRICH_DEFAULT_STAGES)
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
DEFAULT_LIMIT_PER_SEGMENT = 5

RunStatus = Literal["draft", "queued", "running", "succeeded", "failed", "cancelled"]
TriggerType = Literal["manual", "scheduled", "api"]
RunMode = Literal["icp_segment", "single_company", "startup_research", "enrich_existing"]


@dataclass
class RunConfig:
    segments: list[str]
    limit_per_segment: int
    stages: str | list[str]       # "full" or subset list
    dry_run: bool = False
    notion_sync: bool = True
    triggered_by: str = ""
    trigger_type: TriggerType = "manual"
    run_mode: RunMode = "icp_segment"
    company_name: str = ""
    company_url: str = ""
    startup_description: str = ""
    focus_areas: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.run_mode == "icp_segment":
            if not self.segments:
                raise ValueError("segments must be non-empty")
            unknown = set(self.segments) - VALID_SEGMENTS
            if unknown:
                raise ValueError(f"unknown segments: {unknown}")
            if not (1 <= self.limit_per_segment <= 200):
                raise ValueError("limit_per_segment must be between 1 and 200")
        elif self.run_mode == "single_company":
            if not self.company_name:
                raise ValueError("company_name is required for single_company mode")
        elif self.run_mode == "startup_research":
            if not self.startup_description:
                raise ValueError("description is required for startup_research mode")
        elif self.run_mode == "enrich_existing":
            unknown = set(self.segments) - VALID_SEGMENTS
            if unknown:
                raise ValueError(f"unknown segments: {unknown}")
            if self.limit_per_segment < 1 or self.limit_per_segment > 200:
                raise ValueError("limit_per_segment must be between 1 and 200")
        else:
            raise ValueError(f"invalid run_mode: {self.run_mode}")

        if self.run_mode == "icp_segment" and self.stages != "full":
            if not isinstance(self.stages, list) or not self.stages:
                raise ValueError("stages must be 'full' or a non-empty list")
            unknown_stages = set(self.stages) - VALID_STAGES
            if unknown_stages:
                raise ValueError(f"unknown stages: {unknown_stages}")
        if self.run_mode == "enrich_existing":
            if not isinstance(self.stages, list) or not self.stages:
                raise ValueError("stages must be a non-empty list")
            unknown_stages = set(self.stages) - ENRICH_VALID_STAGES
            if unknown_stages:
                raise ValueError(f"unknown stages: {unknown_stages}")
        if self.trigger_type not in ("manual", "scheduled", "api"):
            raise ValueError(f"invalid trigger_type: {self.trigger_type}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_mode": self.run_mode,
            "segments": self.segments,
            "limit_per_segment": self.limit_per_segment,
            "stages": self.stages,
            "dry_run": self.dry_run,
            "notion_sync": self.notion_sync,
            "triggered_by": self.triggered_by,
            "trigger_type": self.trigger_type,
            "company_name": self.company_name,
            "company_url": self.company_url,
            "startup_description": self.startup_description,
            "focus_areas": self.focus_areas,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunConfig":
        return cls(
            segments=data.get("segments", []),
            limit_per_segment=data.get("limit_per_segment", DEFAULT_LIMIT_PER_SEGMENT),
            stages=data.get("stages", "full"),
            dry_run=data.get("dry_run", False),
            notion_sync=data.get("notion_sync", True),
            triggered_by=data.get("triggered_by", ""),
            trigger_type=data.get("trigger_type", "manual"),
            run_mode=data.get("run_mode", "icp_segment"),
            company_name=data.get("company_name", ""),
            company_url=data.get("company_url", ""),
            startup_description=data.get("startup_description", ""),
            focus_areas=data.get("focus_areas", []),
        )
