"""Tests for NewsAgent deterministic core (scripts/news.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import Response

import news
from http_client import HttpClient
from news import (
    Article,
    classify_event,
    fetch_gdelt,
    fetch_google_news,
    fetch_hn,
    make_dedupe_key,
    monitor_company,
    resolve_company_domain,
    scan_segment,
    signal_class_for,
)


# ── Classification ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,event_type,signal_class",
    [
        ("Rad AI raises $50M Series B", "funding_round", "strong"),
        ("Acme emerges from stealth with new vision model", "stealth_exit", "strong"),
        ("Startup is hiring ML engineers", "hiring_surge", "strong"),
        ("Foo partners with Bar on logistics", "partnership", "soft"),
        ("Company appoints new CTO", "leadership_change", "soft"),
        ("Startup layoffs hit 20%", "negative", "soft"),
        ("A perfectly ordinary sentence", None, None),
        ("", None, None),
    ],
)
def test_classify_event(text, event_type, signal_class):
    assert classify_event(text) == (event_type, signal_class)


def test_signal_class_for():
    assert signal_class_for("funding_round") == "strong"
    assert signal_class_for("partnership") == "soft"
    assert signal_class_for("unknown_event") == "soft"


# ── Entity resolution / dedup ──────────────────────────────────────────────────


def test_resolve_company_domain_normalizes():
    assert resolve_company_domain("https://www.radai.com/about") == "radai.com"
    assert resolve_company_domain("RadAI.com") == "radai.com"


def test_resolve_company_domain_none_on_empty():
    assert resolve_company_domain("") is None
    assert resolve_company_domain(None) is None


def test_dedupe_key_is_stable():
    a = make_dedupe_key("radai.com", "funding_round", "2026-06-19")
    b = make_dedupe_key("radai.com", "funding_round", "2026-06-19")
    assert a == b


def test_dedupe_key_collapses_same_week():
    # 2026-06-15 and 2026-06-19 fall in the same ISO week → one event.
    monday = make_dedupe_key("radai.com", "funding_round", "2026-06-15")
    friday = make_dedupe_key("radai.com", "funding_round", "2026-06-19")
    assert monday == friday


def test_dedupe_key_differs_by_event_type_and_domain():
    base = make_dedupe_key("radai.com", "funding_round", "2026-06-19")
    assert base != make_dedupe_key("radai.com", "model_launch", "2026-06-19")
    assert base != make_dedupe_key("other.com", "funding_round", "2026-06-19")


# ── Fetchers ───────────────────────────────────────────────────────────────────


@pytest.mark.respx(base_url="https://api.gdeltproject.org")
def test_fetch_gdelt_parses_articles(respx_mock):
    respx_mock.get("/api/v2/doc/doc").mock(return_value=Response(200, json={
        "articles": [
            {"url": "https://techcrunch.com/rad-ai", "title": "Rad AI raises $50M",
             "seendate": "20260619T120000Z", "domain": "techcrunch.com"},
        ],
    }))
    with HttpClient(rate_limit_rps=0) as client:
        articles = fetch_gdelt(client, '"Rad AI"')
    assert len(articles) == 1
    art = articles[0]
    assert art.source == "gdelt"
    assert art.url == "https://techcrunch.com/rad-ai"
    assert art.published == "2026-06-19"
    assert art.publisher_domain == "techcrunch.com"


_RSS = """<?xml version="1.0"?>
<rss version="2.0"><channel>
  <item>
    <title>Rad AI raises Series B</title>
    <link>https://news.example.com/rad-ai</link>
    <pubDate>Fri, 19 Jun 2026 09:00:00 GMT</pubDate>
    <description>Funding news</description>
  </item>
</channel></rss>"""


@pytest.mark.respx(base_url="https://news.google.com")
def test_fetch_google_news_parses_rss(respx_mock):
    respx_mock.get("/rss/search").mock(return_value=Response(200, text=_RSS))
    with HttpClient(rate_limit_rps=0) as client:
        articles = fetch_google_news(client, '"Rad AI"')
    assert len(articles) == 1
    art = articles[0]
    assert art.source == "google_news"
    assert art.url == "https://news.example.com/rad-ai"
    assert art.published == "2026-06-19"


@pytest.mark.respx(base_url="https://hn.algolia.com")
def test_fetch_hn_parses_hits(respx_mock):
    respx_mock.get("/api/v1/search").mock(return_value=Response(200, json={
        "hits": [
            {"objectID": "1", "title": "Show HN: our new model",
             "url": "https://example.com/model", "created_at": "2026-06-19T10:00:00Z"},
            {"objectID": "2", "title": "Ask HN", "url": None,
             "created_at": "2026-06-18T10:00:00Z"},
        ],
    }))
    with HttpClient(rate_limit_rps=0) as client:
        articles = fetch_hn(client, "new model")
    assert articles[0].url == "https://example.com/model"
    # url-less story falls back to the HN item permalink
    assert articles[1].url == "https://news.ycombinator.com/item?id=2"


# ── Monitoring flow ─────────────────────────────────────────────────────────────


_COMPANY = {
    "domain": "radai.com",
    "name": "Rad AI",
    "status": "dossier_ready",
    "linkedin_url": None,
}


def _patch_sources(monkeypatch, google, gdelt):
    monkeypatch.setattr(news, "fetch_google_news", lambda *a, **k: google)
    monkeypatch.setattr(news, "fetch_gdelt", lambda *a, **k: gdelt)


def test_monitor_company_dedups_and_collects_alt_urls(monkeypatch):
    store = MagicMock()
    google = [Article("Rad AI raises $50M Series B", "https://a/1", "google_news", "2026-06-19")]
    gdelt = [Article("Rad AI raises Series B round", "https://a/2", "gdelt", "2026-06-18")]
    _patch_sources(monkeypatch, google, gdelt)

    results = monitor_company(_COMPANY, store, MagicMock(), allow_refresh=True)

    assert len(results) == 1  # same event, one row
    ev = results[0]
    assert ev["event_type"] == "funding_round"
    assert ev["signal_class"] == "strong"
    assert ev["alt_urls"] == ["https://a/2"]
    # one record written, with the event dedupe_key passed through
    assert store.upsert_research_record.call_count == 1
    _, kwargs = store.upsert_research_record.call_args
    assert kwargs["dedupe_key"] == ev["dedupe_key"]
    entry = store.upsert_research_record.call_args[0][0]
    assert entry.record_type == "news"
    assert entry.record_role == "monitor"
    assert entry.payload["event_type"] == "funding_round"
    assert entry.payload["alt_urls"] == ["https://a/2"]
    # strong signal on a dossier_ready company → refresh flag
    store.set_needs_refresh.assert_called_once_with("radai.com")


def test_monitor_company_dry_run_writes_nothing(monkeypatch):
    store = MagicMock()
    google = [Article("Rad AI raises $50M Series B", "https://a/1", "google_news", "2026-06-19")]
    _patch_sources(monkeypatch, google, [])

    results = monitor_company(_COMPANY, store, MagicMock(), dry_run=True, allow_refresh=True)

    assert len(results) == 1
    store.upsert_research_record.assert_not_called()
    store.set_needs_refresh.assert_not_called()


def test_monitor_company_soft_signal_no_refresh(monkeypatch):
    store = MagicMock()
    google = [Article("Rad AI partners with Hospital", "https://a/1", "google_news", "2026-06-19")]
    _patch_sources(monkeypatch, google, [])

    results = monitor_company(_COMPANY, store, MagicMock(), allow_refresh=True)

    assert results[0]["signal_class"] == "soft"
    store.upsert_research_record.assert_called_once()
    store.set_needs_refresh.assert_not_called()


def test_monitor_company_refresh_gated_by_status(monkeypatch):
    store = MagicMock()
    company = {**_COMPANY, "status": "relevant"}
    google = [Article("Rad AI raises Series B", "https://a/1", "google_news", "2026-06-19")]
    _patch_sources(monkeypatch, google, [])

    monitor_company(company, store, MagicMock(), allow_refresh=True)
    # not dossier_ready → no refresh flag even on a strong signal
    store.set_needs_refresh.assert_not_called()


def test_monitor_company_unclassified_skipped(monkeypatch):
    store = MagicMock()
    google = [Article("A perfectly ordinary press note", "https://a/1", "google_news", "2026-06-19")]
    _patch_sources(monkeypatch, google, [])

    results = monitor_company(_COMPANY, store, MagicMock())
    assert results == []
    store.upsert_research_record.assert_not_called()


# ── Discovery scan ──────────────────────────────────────────────────────────────


def test_scan_segment_classifies_without_writing(monkeypatch):
    config = {"segments": {"medical-imaging": {"queries": ['"radiology AI" raises']}}}
    google = [
        Article("NewCo raises Series A for radiology AI", "https://a/1", "google_news", "2026-06-19"),
        Article("Generic industry roundup", "https://a/2", "google_news", "2026-06-19"),
    ]
    monkeypatch.setattr(news, "fetch_google_news", lambda *a, **k: google)

    candidates = scan_segment(config, "medical-imaging", MagicMock())
    assert len(candidates) == 1  # only the classified one
    assert candidates[0]["event_type"] == "funding_round"
    assert candidates[0]["segment"] == "medical-imaging"
