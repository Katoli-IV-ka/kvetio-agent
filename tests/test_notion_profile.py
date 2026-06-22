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
