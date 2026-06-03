"""Тесты Greenhouse-адаптера через respx (моки httpx)."""

from datetime import date
from pathlib import Path

import pytest
import respx
from httpx import Response

from greenhouse import API_BASE, GreenhouseAdapter
from models import ICPQuery


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def slugs_csv(tmp_path: Path) -> Path:
    p = tmp_path / "slugs.csv"
    p.write_text(
        "company_name,ats,slug,segment_hint,note\n"
        "Example Corp,greenhouse,example,medical-imaging,\n"
    )
    return p


@pytest.fixture
def query() -> ICPQuery:
    return ICPQuery(segment="medical-imaging", keywords_strong=())


def _patched_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Фиксируем "сегодня" так, чтобы тесты не сломались с течением времени."""
    fixed = date(2026, 4, 29)

    class FakeDate(date):
        @classmethod
        def today(cls) -> date:
            return fixed

    monkeypatch.setattr("greenhouse.date", FakeDate)


def test_filters_non_data_jobs(
    slugs_csv: Path, query: ICPQuery, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patched_today(monkeypatch)
    payload = (FIXTURES / "greenhouse_sample.json").read_text()

    with respx.mock(assert_all_called=True) as mock:
        mock.get(f"{API_BASE}/example/jobs").mock(
            return_value=Response(200, content=payload, headers={"content-type": "application/json"})
        )
        with GreenhouseAdapter(slugs_csv=slugs_csv, rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query))

    # Из 4 вакансий: 1001 (RLHF) + 1003 (Data Annotation, MRI) — два валидных сигнала.
    # 1002 — frontend, не data. 1004 — старше 180 дней.
    assert len(signals) == 2
    titles = {s.raw_payload["title"] for s in signals}
    assert any("RLHF" in t for t in titles)
    assert any("Annotation" in t for t in titles)


def test_signal_fields(
    slugs_csv: Path, query: ICPQuery, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patched_today(monkeypatch)
    payload = (FIXTURES / "greenhouse_sample.json").read_text()

    with respx.mock() as mock:
        mock.get(f"{API_BASE}/example/jobs").mock(
            return_value=Response(200, content=payload, headers={"content-type": "application/json"})
        )
        with GreenhouseAdapter(slugs_csv=slugs_csv, rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query))

    s = next(s for s in signals if "Annotation" in s.raw_payload["title"])
    assert s.source == "greenhouse"
    assert s.signal_type == "job_posting"
    assert s.company_name == "Example Corp"
    assert s.evidence_url.startswith("https://boards.greenhouse.io/")
    assert s.confidence == "high"
    # signal_date берётся из updated_at в фикстуре (2026-04-22).
    assert s.signal_date == date(2026, 4, 22)


def test_strong_keyword_segment_filter(
    slugs_csv: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Если в сегменте указаны keywords_strong — должен матчиться хотя бы один."""
    _patched_today(monkeypatch)
    payload = (FIXTURES / "greenhouse_sample.json").read_text()

    query = ICPQuery(segment="medical-imaging", keywords_strong=("MRI", "DICOM"))

    with respx.mock() as mock:
        mock.get(f"{API_BASE}/example/jobs").mock(
            return_value=Response(200, content=payload, headers={"content-type": "application/json"})
        )
        with GreenhouseAdapter(slugs_csv=slugs_csv, rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query))

    # Только 1003 содержит DICOM/MRI; 1001 (RLHF) — отбрасывается сегмент-фильтром.
    assert len(signals) == 1
    assert "Annotation" in signals[0].raw_payload["title"]


def test_empty_response(slugs_csv: Path, query: ICPQuery) -> None:
    with respx.mock() as mock:
        mock.get(f"{API_BASE}/example/jobs").mock(
            return_value=Response(200, json={"jobs": []})
        )
        with GreenhouseAdapter(slugs_csv=slugs_csv, rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query))
    assert signals == []


def test_404_treated_as_no_signals(slugs_csv: Path, query: ICPQuery) -> None:
    with respx.mock() as mock:
        mock.get(f"{API_BASE}/example/jobs").mock(return_value=Response(404))
        with GreenhouseAdapter(slugs_csv=slugs_csv, rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query))
    assert signals == []
