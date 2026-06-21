"""Tests for the Verification stage deterministic core (Phase 2)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest
from httpx import Response

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from http_client import HttpClient
from verification import (
    classify_freshness,
    link_status,
    load_thresholds,
    run_verification,
    verify_record,
)

TODAY = date(2026, 6, 21)
THRESHOLDS = {
    "news_event_months": 12,
    "news_priority_months": 6,
    "funding_signal_months": 18,
    "financial_record_types": ["form_d", "grant", "funding_announcement"],
}


def test_load_thresholds_reads_config():
    t = load_thresholds()
    assert t["news_event_months"] == 12
    assert t["funding_signal_months"] == 18
    assert "form_d" in t["financial_record_types"]


def test_classify_freshness_news_stale_after_12_months():
    assert classify_freshness("news", date(2025, 1, 1), THRESHOLDS, TODAY) == "stale"
    assert classify_freshness("news", date(2026, 3, 1), THRESHOLDS, TODAY) == "fresh"


def test_classify_freshness_funding_stale_after_18_months():
    assert classify_freshness("form_d", date(2024, 1, 1), THRESHOLDS, TODAY) == "stale"
    assert classify_freshness("grant", date(2025, 6, 1), THRESHOLDS, TODAY) == "fresh"


def test_classify_freshness_non_dated_types_are_fresh():
    # Types without a freshness rule (e.g. github_repo) never go stale on age alone.
    assert classify_freshness("github_repo", date(2019, 1, 1), THRESHOLDS, TODAY) == "fresh"


@pytest.mark.respx(base_url="https://example.com")
def test_link_status_live(respx_mock):
    respx_mock.head("/page").mock(return_value=Response(200))
    with HttpClient(rate_limit_rps=0) as client:
        assert link_status("https://example.com/page", client) == "live"


@pytest.mark.respx(base_url="https://example.com")
def test_link_status_dead_on_404(respx_mock):
    respx_mock.head("/gone").mock(return_value=Response(404))
    with HttpClient(rate_limit_rps=0) as client:
        assert link_status("https://example.com/gone", client) == "dead"


def test_link_status_dead_when_wayback_only():
    # web.archive.org URLs are treated as not-live (the original is gone).
    assert link_status("https://web.archive.org/web/2020/https://x.com", MagicMock()) == "dead"


@pytest.mark.respx(base_url="https://example.com")
def test_verify_record_verified(respx_mock):
    respx_mock.head("/p").mock(return_value=Response(200))
    record = {"id": "r1", "record_type": "grant", "url": "https://example.com/p",
              "observed_at": "2025-06-01"}
    with HttpClient(rate_limit_rps=0) as client:
        assert verify_record(record, client, THRESHOLDS, TODAY) == "verified"


@pytest.mark.respx(base_url="https://example.com")
def test_verify_record_unverified_when_link_dead(respx_mock):
    respx_mock.head("/p").mock(return_value=Response(404))
    record = {"id": "r1", "record_type": "grant", "url": "https://example.com/p",
              "observed_at": "2025-06-01"}
    with HttpClient(rate_limit_rps=0) as client:
        assert verify_record(record, client, THRESHOLDS, TODAY) == "unverified"


def test_verify_record_stale_when_old():
    # Freshness takes precedence: a stale record short-circuits before the link check.
    record = {"id": "r1", "record_type": "form_d", "url": "https://example.com/p",
              "observed_at": "2023-01-01"}
    client = MagicMock()
    assert verify_record(record, client, THRESHOLDS, TODAY) == "stale"
    client.head_status.assert_not_called()


@pytest.mark.respx(base_url="https://example.com")
def test_run_verification_writes_status_per_record(respx_mock):
    respx_mock.head("/a").mock(return_value=Response(200))
    respx_mock.head("/b").mock(return_value=Response(404))
    store = MagicMock()
    records = [
        {"id": "a", "record_type": "grant", "url": "https://example.com/a", "observed_at": "2025-06-01"},
        {"id": "b", "record_type": "grant", "url": "https://example.com/b", "observed_at": "2025-06-01"},
    ]
    with HttpClient(rate_limit_rps=0) as client:
        results = run_verification(records, store, client, today=TODAY, thresholds=THRESHOLDS)
    assert dict(results) == {"a": "verified", "b": "unverified"}
    assert store.set_record_verification.call_count == 2
