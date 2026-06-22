"""Tests for notion_profile: pure profile-builder functions."""
from __future__ import annotations
import pytest
import notion_profile as np_mod


# ---------------------------------------------------------------------------
# _format_amount
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("usd,expected", [
    (12_000_000,        "$12M"),
    (3_500_000,         "$3.5M"),
    (750_000,           "$750K"),
    (1_000_000_000,     "$1B"),
    (1_200_000_000,     "$1.2B"),
    (500,               "$500"),
    (1_000,             "$1K"),
    (1_100,             "$1.1K"),
    (100_000_000,       "$100M"),
])
def test_format_amount(usd, expected):
    assert np_mod._format_amount(usd) == expected


# ---------------------------------------------------------------------------
# _compute_funding_info
# ---------------------------------------------------------------------------

def test_funding_info_both():
    result = np_mod._compute_funding_info("Series A", 12_000_000)
    assert result == "Series A · $12M"


def test_funding_info_stage_only():
    result = np_mod._compute_funding_info("Seed", None)
    assert result == "Seed"


def test_funding_info_amount_only():
    result = np_mod._compute_funding_info(None, 3_000_000)
    assert result == "$3M"


def test_funding_info_none():
    result = np_mod._compute_funding_info(None, None)
    assert result is None


# ---------------------------------------------------------------------------
# _compute_potential_data
# ---------------------------------------------------------------------------

_POTENTIAL_CFG = {
    "segments": {
        "medical-imaging": ["Medical Data", "Images", "Annotation"],
        "generative-ai": ["Text", "LLM Data", "Human Feedback"],
    },
    "status_overrides": {
        "data_partner": ["Data Supplier"],
    },
}


def test_potential_data_by_segment():
    result = np_mod._compute_potential_data("medical-imaging", "relevant", _POTENTIAL_CFG)
    assert result == ["Medical Data", "Images", "Annotation"]


def test_potential_data_union_with_status_override():
    result = np_mod._compute_potential_data("generative-ai", "data_partner", _POTENTIAL_CFG)
    assert result == ["Text", "LLM Data", "Human Feedback", "Data Supplier"]


def test_potential_data_no_duplicate_when_override_already_in_segment():
    cfg = {
        "segments": {"seg": ["A", "B"]},
        "status_overrides": {"data_partner": ["B", "C"]},
    }
    result = np_mod._compute_potential_data("seg", "data_partner", cfg)
    assert result == ["A", "B", "C"]


def test_potential_data_unknown_segment_returns_empty():
    result = np_mod._compute_potential_data("unknown-segment", "relevant", _POTENTIAL_CFG)
    assert result == []


def test_potential_data_none_segment_returns_empty():
    result = np_mod._compute_potential_data(None, None, _POTENTIAL_CFG)
    assert result == []


# ---------------------------------------------------------------------------
# _compute_last_info_update
# ---------------------------------------------------------------------------

def test_last_info_update_max_across_all_sources():
    company = {"updated_at": "2026-01-01T00:00:00"}
    dossier = {"updated_at": "2026-03-15T00:00:00"}
    aggregates = {
        "last_research_created_at": "2026-02-10",
        "last_contact_updated_at": "2026-04-01",
    }
    result = np_mod._compute_last_info_update(company, dossier, aggregates)
    assert result == "2026-04-01"


def test_last_info_update_ignores_none():
    company = {"updated_at": "2026-05-01T00:00:00"}
    result = np_mod._compute_last_info_update(company, None, {})
    assert result == "2026-05-01"


def test_last_info_update_returns_none_when_all_none():
    result = np_mod._compute_last_info_update({}, None, {})
    assert result is None
