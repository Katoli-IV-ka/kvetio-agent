"""Greenhouse Job Board API — source-адаптер.

API:  GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
Auth: не требуется.
Rate: держим 1 req/sec.

CLI (вызывается Claude через Bash):
    python scripts/greenhouse.py --segment medical-imaging
    python scripts/greenhouse.py --segment autonomous-vehicles --output json

Выводит JSON-массив найденных сигналов в stdout.
"""

from __future__ import annotations

import argparse
import csv
import html as html_module
import json
import logging
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

# Плоский импорт из той же папки
sys.path.insert(0, str(Path(__file__).parent))
from http_client import HttpClient
from models import ICPQuery, RawSignal

logger = logging.getLogger(__name__)

API_BASE = "https://boards-api.greenhouse.io/v1/boards"

# Универсальные сигналы спроса на внешние данные.
DATA_KEYWORDS = (
    "training data",
    "data annotation",
    "annotation pipeline",
    "data labeling",
    "rlhf",
    "reinforcement learning from human feedback",
    "data collection",
    "dataset curation",
    "dataset",
    "fine-tuning",
    "data pipeline",
    "ml engineer",
    "data annotation engineer",
    "mlops",
    "data operations",
)

RECENT_DAYS = 180

_HTML_TAG = re.compile(r"<[^>]+>")

# Путь к CSV с slug'ами — относительно корня репозитория
_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_SLUGS = _REPO_ROOT / "data" / "known_ats_slugs.csv"


def _strip_html(s: str) -> str:
    s = html_module.unescape(s)
    s = _HTML_TAG.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _matches_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(k in lowered for k in keywords)


def _matches_segment(text: str, query: ICPQuery) -> bool:
    if not query.keywords_strong:
        return True
    return _matches_keyword(text, tuple(k.lower() for k in query.keywords_strong))


def _parse_signal_date(updated_at: str | None) -> date:
    if not updated_at:
        return date.today()
    try:
        return datetime.fromisoformat(updated_at.replace("Z", "+00:00")).date()
    except ValueError:
        return date.today()


def load_slugs(slugs_csv: Path) -> list[tuple[str, str, str | None]]:
    """Возвращает [(company_name, slug, website_or_None), ...] из CSV.

    Поддерживает как старый формат (без колонки website),
    так и новый (с колонкой website).
    Строки-комментарии (начинаются с #) пропускаются.
    """
    if not slugs_csv.exists():
        logger.warning("Slugs CSV не найден: %s", slugs_csv)
        return []
    rows: list[tuple[str, str, str | None]] = []
    with slugs_csv.open(encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Пропускаем строки-комментарии
            first_value = next(iter(row.values()), "")
            if first_value.strip().startswith("#"):
                continue
            if (row.get("ats") or "").strip().lower() != "greenhouse":
                continue
            slug = (row.get("slug") or "").strip()
            name = (row.get("company_name") or "").strip()
            if not slug or not name:
                continue
            website = (row.get("website") or "").strip() or None
            rows.append((name, slug, website))
    return rows


class GreenhouseAdapter:
    name = "greenhouse"
    tier = "A"

    def __init__(
        self,
        *,
        slugs_csv: Path = _DEFAULT_SLUGS,
        parser_version: str = "2026-05",
        rate_limit_rps: float = 1.0,
        recent_days: int = RECENT_DAYS,
    ) -> None:
        self.parser_version = parser_version
        self._slugs_csv = slugs_csv
        self._recent_days = recent_days
        self._http = HttpClient(rate_limit_rps=rate_limit_rps)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GreenhouseAdapter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch(self, query: ICPQuery) -> Iterator[RawSignal]:
        cutoff = date.today() - timedelta(days=self._recent_days)
        for company_name, slug, website in load_slugs(self._slugs_csv):
            url = f"{API_BASE}/{slug}/jobs"
            try:
                payload = self._http.get_json(url, params={"content": "true"})
            except Exception as exc:  # noqa: BLE001
                logger.warning("Greenhouse %s: ошибка (%s)", slug, exc)
                continue
            jobs = payload.get("jobs") if isinstance(payload, dict) else None
            if not jobs:
                continue
            for job in jobs:
                yield from self._maybe_signal(query, company_name, slug, website, job, cutoff)

    def _maybe_signal(
        self,
        query: ICPQuery,
        company_name: str,
        slug: str,
        website: str | None,
        job: dict,
        cutoff: date,
    ) -> Iterator[RawSignal]:
        title = (job.get("title") or "").strip()
        content_text = _strip_html(job.get("content") or "")
        combined = f"{title}\n{content_text}"

        if not _matches_keyword(combined, DATA_KEYWORDS):
            return
        if not _matches_segment(combined, query):
            return

        signal_date = _parse_signal_date(job.get("updated_at"))
        if signal_date < cutoff:
            return

        evidence_url = (
            job.get("absolute_url")
            or f"https://boards.greenhouse.io/{slug}/jobs/{job.get('id', '')}"
        )

        # Нормализуем домен из website если он есть в CSV
        domain: str | None = None
        if website:
            try:
                sys.path.insert(0, str(Path(__file__).parent))
                from normalize import normalize_domain
                domain = normalize_domain(website)
            except Exception:  # noqa: BLE001
                domain = website  # fallback: используем как есть

        yield RawSignal(
            source=self.name,
            signal_type="job_posting",
            company_name=company_name,
            domain=domain,  # None если website не задан в CSV — агент найдёт через WebSearch
            linkedin_url=None,
            evidence_url=evidence_url,
            signal_date=signal_date,
            confidence="high",
            raw_payload={
                "slug": slug,
                "job_id": job.get("id"),
                "title": title,
                "snippet": content_text[:300],
                "location": (job.get("location") or {}).get("name"),
                "website_from_csv": website,  # для отладки
            },
            parser_version=self.parser_version,
        )


def _load_icp_query(segment: str) -> ICPQuery:
    """Загружает параметры сегмента из config/icp.yaml."""
    import yaml  # noqa: PLC0415

    config_path = _REPO_ROOT / "config" / "icp.yaml"
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    for seg in raw.get("segments", []):
        if seg["name"] == segment:
            return ICPQuery(
                segment=seg["name"],
                keywords_strong=tuple(seg.get("keywords_strong", [])),
                keywords_weak=tuple(seg.get("keywords_weak", [])),
                industries=tuple(seg.get("industries", [])),
            )
    raise ValueError(f"Сегмент '{segment}' не найден в config/icp.yaml")


def _signal_to_dict(s: RawSignal) -> dict:
    return {
        "source": s.source,
        "signal_type": s.signal_type,
        "company_name": s.company_name,
        "domain": s.domain,
        "evidence_url": s.evidence_url,
        "signal_date": s.signal_date.isoformat(),
        "confidence": s.confidence,
        "raw_payload": s.raw_payload,
        "parser_version": s.parser_version,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Greenhouse ATS source adapter")
    parser.add_argument("--segment", required=True, help="ICP-сегмент из config/icp.yaml")
    parser.add_argument(
        "--slugs-csv",
        default=str(_DEFAULT_SLUGS),
        help="Путь к CSV с Greenhouse slug'ами",
    )
    parser.add_argument("--recent-days", type=int, default=RECENT_DAYS)
    args = parser.parse_args()

    query = _load_icp_query(args.segment)
    results = []

    with GreenhouseAdapter(
        slugs_csv=Path(args.slugs_csv),
        recent_days=args.recent_days,
    ) as adapter:
        for signal in adapter.fetch(query):
            results.append(_signal_to_dict(signal))

    print(json.dumps(results, ensure_ascii=False, indent=2))
    logger.info("Найдено сигналов: %d", len(results))
