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
RecordType = SignalType
RecordRole = Literal["primary", "verification", "source", "monitor", "evidence"]
ContactType = Literal["person", "organization"]

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


@dataclass(frozen=True, init=False)
class ResearchRecord:
    """One atomic observation about a company, keyed to company_id."""

    source: str
    record_type: RecordType
    company_name: str
    domain: str | None          # raw domain; normalized when written to storage
    linkedin_url: str | None
    url: str                    # evidence link
    observed_at: date
    confidence: "Confidence | float"
    record_role: RecordRole = "evidence"
    agent: str | None = None
    title: str | None = None
    summary: str | None = None
    payload: dict = field(default_factory=dict)      # structured extracted fields
    raw_payload: dict = field(default_factory=dict)  # -> DB column raw_data

    def __init__(
        self,
        *,
        source: str,
        record_type: RecordType | None = None,
        signal_type: RecordType | None = None,
        company_name: str,
        domain: str | None,
        linkedin_url: str | None,
        url: str,
        observed_at: date | None = None,
        signal_date: date | None = None,
        confidence: "Confidence | float",
        record_role: RecordRole = "evidence",
        agent: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        payload: dict | None = None,
        raw_payload: dict | None = None,
    ) -> None:
        chosen_type = record_type or signal_type
        chosen_date = observed_at or signal_date
        if chosen_type is None:
            raise TypeError("ResearchRecord.record_type is required")
        if chosen_date is None:
            raise TypeError("ResearchRecord.observed_at is required")

        object.__setattr__(self, "source", source)
        object.__setattr__(self, "record_type", chosen_type)
        object.__setattr__(self, "company_name", company_name)
        object.__setattr__(self, "domain", domain)
        object.__setattr__(self, "linkedin_url", linkedin_url)
        object.__setattr__(self, "url", url)
        object.__setattr__(self, "observed_at", chosen_date)
        object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "record_role", record_role)
        object.__setattr__(self, "agent", agent)
        object.__setattr__(self, "title", title)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "payload", payload or {})
        object.__setattr__(self, "raw_payload", raw_payload or {})
        self.__post_init__()

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("ResearchRecord.url обязателен")
        if not self.company_name.strip():
            raise ValueError("ResearchRecord.company_name не может быть пустым")

    @property
    def signal_type(self) -> RecordType:
        """Deprecated compatibility alias for old source-adapter callers."""
        return self.record_type

    @property
    def signal_date(self) -> date:
        """Deprecated compatibility alias for old source-adapter callers."""
        return self.observed_at


# Deprecated alias — remove after all callers update to ResearchRecord.
RawSignal = ResearchRecord


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
    """Current outreach touchpoint for a company (person or organization)."""

    company_id: str
    name: str
    contact_type: ContactType = "person"
    info: str | None = None

    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    x_url: str | None = None
    facebook_url: str | None = None
    instagram_url: str | None = None

    other_channels: list[OtherChannel] = field(default_factory=list)
    discovered_from_research_record_id: str | None = None
