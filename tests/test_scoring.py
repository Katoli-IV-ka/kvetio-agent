from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from score import ScoringConfig, score
from models import Company, Evidence


@pytest.fixture
def cfg(tmp_path: Path) -> ScoringConfig:
    """Cтабильный конфиг для тестов: пороги детерминированы."""
    raw = {
        "version": "test-1",
        "thresholds": {"qualified": 30, "manual_review": 15},
        "weights": {
            "training_intensity": {},
            "external_data_fit": {},
            "commercial_readiness": {},
            "freshness": {
                "signal_within_30d": 5,
                "signal_within_90d": 3,
                "signal_within_180d": 1,
            },
            "negative_flags": {},
        },
    }
    p = tmp_path / "scoring.yaml"
    p.write_text(yaml.safe_dump(raw))
    from score import load_config as load_scoring_config

    return load_scoring_config(p)


def _company(days_ago: int | None) -> Company:
    evs = []
    if days_ago is not None:
        evs.append(
            Evidence(
                source="greenhouse",
                signal_type="job_posting",
                url="https://example.com/job/1",
                signal_date=date.today() - timedelta(days=days_ago),
                confidence="high",
            )
        )
    return Company(
        normalized_domain="example.com",
        name="Example",
        website="https://example.com",
        evidences=evs,
    )


def test_no_evidence_zero(cfg: ScoringConfig) -> None:
    s = score(_company(None), cfg)
    assert s.total == 0
    assert s.bucket == "not_relevant"


@pytest.mark.parametrize(
    "days_ago,expected_total",
    [
        (5, 5),  # within 30
        (29, 5),
        (45, 3),  # within 90
        (89, 3),
        (150, 1),  # within 180
        (200, 0),  # too old
    ],
)
def test_freshness_buckets(cfg: ScoringConfig, days_ago: int, expected_total: int) -> None:
    s = score(_company(days_ago), cfg)
    assert s.total == expected_total


def test_pure_function(cfg: ScoringConfig) -> None:
    """Один и тот же вход -> один и тот же выход. Отлавливает скрытое глобальное состояние."""
    c = _company(10)
    s1 = score(c, cfg)
    s2 = score(c, cfg)
    assert s1 == s2
