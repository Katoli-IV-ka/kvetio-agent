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
]
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

    Один сигнал = одна страница / вакансия / репозиторий, ровно одна evidence_url.
    """

    source: str
    signal_type: SignalType
    company_name: str
    domain: str | None          # сырой домен; нормализуется при записи в storage
    linkedin_url: str | None
    evidence_url: str
    signal_date: date
    confidence: Confidence
    raw_payload: dict = field(default_factory=dict)
    parser_version: str = "unknown"

    def __post_init__(self) -> None:
        if not self.evidence_url:
            raise ValueError("RawSignal.evidence_url обязателен")
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

ContactSource = Literal[
    "github",
    "huggingface",
    "team_page",
    "apollo",
    "wellfound",
    "arxiv",
    "contact_page",
]
EmailStatus = Literal["verified", "guessed", "bounced", "unknown", "scraped"]
ContactType = Literal["Person", "Company", "Related Person", "Other"]


@dataclass
class ContactRecord:
    """Decision-maker contact discovered by one or more DM vectors."""

    company_id: str
    company_domain: str
    full_name: str

    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    title_normalized: str | None = None
    dm_priority: int = 2

    email: str | None = None
    email_status: EmailStatus = "unknown"
    email_source: str | None = None
    linkedin_url: str | None = None
    twitter_handle: str | None = None
    github_username: str | None = None

    source_vector: ContactSource = "github"
    source_url: str | None = None
    confidence: Confidence = "medium"

    raw_payload: dict = field(default_factory=dict)

    # ── V2: новые поля для ручного управления контактами ─────────────────────
    contact_type: ContactType = "Person"
    phone: str | None = None
    instagram_url: str | None = None
    facebook_url: str | None = None
    info: str | None = None
