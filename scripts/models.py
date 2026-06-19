"""Доменные типы Kvetio.

Переименовано из types.py → models.py, чтобы не конфликтовать
со стандартной библиотекой Python (import types).

Все dataclasses frozen — хешируемы, нет случайных мутаций.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

Tier = Literal["A", "B", "C"]
Confidence = Literal["high", "medium", "low"]
SignalType = Literal[
    "job_posting",
    "hf_org",
    "hf_model",
    "github_repo",
    "papers_with_code",
    "funding_announcement",
    "kaggle_sponsor",
    "scale_customer",
    "wandb_run",
    "directory_listing",
    "contact_found",
    "source_link",
    "news",
    "product_update",
    "foundation_model",
    "proprietary_ai",
    "proprietary_models",
]

CONFIDENCE_SCORE: dict[str, float] = {"high": 0.9, "medium": 0.5, "low": 0.2}


def confidence_to_score(value: "Confidence | float | int") -> float:
    """Convert a text confidence label or numeric value to a float in 0..1."""
    if isinstance(value, (int, float)):
        return float(value)
    return CONFIDENCE_SCORE.get(str(value), 0.5)
Status = Literal[
    "discovered",
    "relevant",
    "not_relevant",
    "manual_review",
    "sources_gathered",
    "analyzed",
    "dossier_ready",
]

# Canonical cleanup status model:
# discovered -> relevant/not_relevant/manual_review ->
# sources_gathered -> analyzed -> dossier_ready.
ALL_STATUSES: tuple[str, ...] = (
    "discovered",
    "relevant",
    "not_relevant",
    "manual_review",
    "sources_gathered",
    "analyzed",
    "dossier_ready",
)


@dataclass(frozen=True)
class ICPQuery:
    """Параметры запуска research-стадии для одного ICP-сегмента.

    Сегмент из config/icp.yaml превращается в ICPQuery, который передаётся
    в source-адаптеры. Адаптер сам решает, какие поля использовать.
    """

    segment: str
    keywords_strong: tuple[str, ...]
    keywords_weak: tuple[str, ...] = ()
    industries: tuple[str, ...] = ()
    funding_stages: tuple[str, ...] = ()
    geographies: tuple[str, ...] = ()
    min_team_size: int | None = None


@dataclass(frozen=True)
class RawSignal:
    """Минимальная единица найденного сигнала — то, что возвращает source-адаптер.

    Один сигнал = одно атомарное наблюдение о компании, привязанное к company_id.
    """

    source: str
    signal_type: SignalType
    company_name: str
    domain: str | None          # сырой домен; нормализуется при записи в storage
    linkedin_url: str | None
    url: str                    # evidence link (NOT unique; replaces evidence_url)
    signal_date: date
    confidence: "Confidence | float"
    agent: str | None = None    # producing agent name (discovery, dm_enrich, ...)
    title: str | None = None    # short human-readable label
    summary: str | None = None  # short description of the finding
    payload: dict = field(default_factory=dict)      # structured extracted fields
    raw_payload: dict = field(default_factory=dict)  # optional raw API snapshot

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("RawSignal.url обязателен")
        if not self.company_name.strip():
            raise ValueError("RawSignal.company_name не может быть пустым")


@dataclass(frozen=True)
class Evidence:
    """Каноническая ссылка на сигнал, прикреплённая к Company."""

    source: str
    signal_type: SignalType
    url: str
    signal_date: date
    confidence: Confidence
    snippet: str = ""


@dataclass
class Company:
    """Агрегат — компания в базе данных."""

    normalized_domain: str      # primary key для дедупа
    name: str
    website: str
    linkedin_url: str | None = None
    industries: list[str] = field(default_factory=list)
    funding_stage: str | None = None
    last_funding_date: date | None = None
    evidences: list[Evidence] = field(default_factory=list)
    notion_page_id: str | None = None
    last_verified: date | None = None
    status: Status = "discovered"
    icp_segment: str | None = None


# ── Contact ──────────────────────────────────────────────────────────────────

OtherChannel = dict[str, str]


@dataclass
class ContactRecord:
    """Current outreach contact for a company."""

    company_id: str
    first_name: str
    last_name: str = ""

    info: str | None = None

    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    x_url: str | None = None
    facebook_url: str | None = None
    instagram_url: str | None = None

    other_channels: list[OtherChannel] = field(default_factory=list)
