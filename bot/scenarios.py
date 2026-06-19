"""Scenario registry for NLP-driven bot launches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScenarioSpec:
    name: str
    description: str
    required_params: list[str]
    optional_params: list[str]
    param_descriptions: dict[str, str]
    defaults: dict[str, Any]


SCENARIOS: dict[str, ScenarioSpec] = {
    "icp_segment": ScenarioSpec(
        name="ICP Pipeline",
        description="Поиск и квалификация компаний по ICP-сегментам",
        required_params=["segments"],
        optional_params=["limit_per_segment", "stages", "dry_run", "notion_sync"],
        param_descriptions={
            "segments": (
                "список сегментов из: medical-imaging, autonomous-vehicles, "
                "speech-and-audio, generative-ai, agriculture-ai, robotics-ai, video-photo-ai"
            ),
            "limit_per_segment": "максимум компаний на сегмент (1-200), по умолчанию 5",
            "stages": (
                "'full' или подмножество: discovery, relevance, scoring, enrichment, "
                "analysis, conclusions"
            ),
            "dry_run": "true/false, по умолчанию false",
            "notion_sync": "true/false, по умолчанию true",
        },
        defaults={
            "limit_per_segment": 5,
            "stages": "full",
            "dry_run": False,
            "notion_sync": True,
        },
    ),
    "single_company": ScenarioSpec(
        name="Анализ компании",
        description="Полный анализ одной конкретной компании",
        required_params=["company_name"],
        optional_params=["company_url", "stages", "notion_sync"],
        param_descriptions={
            "company_name": "название компании",
            "company_url": "URL сайта компании (опционально)",
            "stages": "'full' или подмножество стадий",
            "notion_sync": "true/false, по умолчанию true",
        },
        defaults={"stages": "full", "notion_sync": True},
    ),
    "startup_research": ScenarioSpec(
        name="Исследование стартапа",
        description="Исследование стартапа на основе информации от пользователя",
        required_params=["description"],
        optional_params=["company_name", "company_url", "focus_areas", "notion_sync"],
        param_descriptions={
            "description": "что делает стартап, раунд, размер команды - всё что знает пользователь",
            "company_name": "название компании (если известно)",
            "company_url": "URL сайта (если известен)",
            "focus_areas": "конкретные направления для исследования (опционально)",
            "notion_sync": "true/false, по умолчанию true",
        },
        defaults={"notion_sync": True},
    ),
}
