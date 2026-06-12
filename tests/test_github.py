"""Tests for GitHubAdapter and OrgCache."""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import respx
from httpx import Response

from github import ORGS_API, SEARCH_API, GitHubAdapter
from models import ICPQuery
from org_cache import OrgCache

FIXTURES = Path(__file__).parent / "fixtures"
FIXED_NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)


# -- Helpers -----------------------------------------------------------------


def _load(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _make_cache(ttl_days: int = 30) -> OrgCache:
    """Return OrgCache with mocked Supabase client."""
    cache = OrgCache.__new__(OrgCache)
    cache._client = MagicMock()
    cache._ttl = timedelta(days=ttl_days)
    return cache


def _stub_supabase_get(cache: OrgCache, data: dict | None) -> None:
    """Wire mock chain: table().select().eq().maybe_single().execute().data."""
    (
        cache._client
        .table.return_value
        .select.return_value
        .eq.return_value
        .maybe_single.return_value
        .execute.return_value
        .data
    ) = data


def _cache_miss() -> OrgCache:
    cache = _make_cache()
    _stub_supabase_get(cache, None)
    cache._client.table.return_value.upsert.return_value.execute.return_value = MagicMock()
    return cache


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("github._utcnow", lambda: FIXED_NOW)
    monkeypatch.setattr("org_cache._utcnow", lambda: FIXED_NOW)


@pytest.fixture
def query_dicom() -> ICPQuery:
    return ICPQuery(segment="medical-imaging", keywords_strong=("DICOM",))


# -- OrgCache.get -------------------------------------------------------------


def test_cache_miss_returns_none() -> None:
    cache = _make_cache()
    _stub_supabase_get(cache, None)
    assert cache.get("some-org") is None


def test_cache_hit_returns_data() -> None:
    cache = _make_cache()
    _stub_supabase_get(
        cache,
        {
            "data": {"name": "Acme Corp", "blog": "https://acme.ai"},
            "cached_at": FIXED_NOW.isoformat(),
        },
    )

    assert cache.get("acme-corp") == {"name": "Acme Corp", "blog": "https://acme.ai"}


def test_stale_entry_returns_none() -> None:
    cache = _make_cache(ttl_days=30)
    stale_ts = (FIXED_NOW - timedelta(days=31)).isoformat()
    _stub_supabase_get(cache, {"data": {"name": "Old Corp"}, "cached_at": stale_ts})

    assert cache.get("old-corp") is None


def test_entry_just_within_ttl_returns_data() -> None:
    cache = _make_cache(ttl_days=30)
    fresh_ts = (FIXED_NOW - timedelta(days=29)).isoformat()
    _stub_supabase_get(cache, {"data": {"name": "Fresh Corp"}, "cached_at": fresh_ts})

    assert cache.get("fresh-corp") == {"name": "Fresh Corp"}


# -- OrgCache.set -------------------------------------------------------------


def test_cache_set_calls_upsert() -> None:
    cache = _make_cache()
    upsert_mock = cache._client.table.return_value.upsert.return_value.execute

    cache.set("new-org", {"name": "New Org"})

    assert upsert_mock.called
    row = cache._client.table.return_value.upsert.call_args[0][0]
    assert row["org_login"] == "new-org"
    assert row["data"] == {"name": "New Org"}
    assert row["cached_at"] == FIXED_NOW.isoformat()


# -- GitHubAdapter ------------------------------------------------------------


def test_filters_user_accounts_and_inactive_orgs(query_dicom: ICPQuery) -> None:
    code_payload = _load("github_code_search_sample.json")
    org_payload = _load("github_org_sample.json")

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(return_value=Response(200, json=code_payload))
        mock.get(f"{ORGS_API}/orgs/MedVision-AI").mock(
            return_value=Response(200, json=org_payload)
        )

        with GitHubAdapter(org_cache=_cache_miss(), rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query_dicom))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.company_name == "MedVision AI"
    assert signal.source == "github"
    assert signal.signal_type == "github_repo"


def test_signal_fields(query_dicom: ICPQuery) -> None:
    code_payload = _load("github_code_search_sample.json")
    org_payload = _load("github_org_sample.json")

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(return_value=Response(200, json=code_payload))
        mock.get(f"{ORGS_API}/orgs/MedVision-AI").mock(
            return_value=Response(200, json=org_payload)
        )

        with GitHubAdapter(org_cache=_cache_miss(), rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query_dicom))

    signal = signals[0]
    assert signal.domain == "medvision.ai"
    assert signal.evidence_url == "https://github.com/MedVision-AI"
    assert signal.signal_date == date(2026, 4, 20)
    assert signal.confidence == "medium"
    assert signal.linkedin_url is None
    assert signal.raw_payload["org_login"] == "MedVision-AI"
    assert signal.raw_payload["repo_count"] == 12


def test_deduplicates_org_across_keywords() -> None:
    query = ICPQuery(segment="medical-imaging", keywords_strong=("DICOM", "MRI"))
    single_org_payload = {
        "total_count": 1,
        "incomplete_results": False,
        "items": [
            {
                "name": "train.py",
                "path": "train.py",
                "repository": {
                    "id": 1,
                    "name": "ml-platform",
                    "full_name": "Acme-AI/ml-platform",
                    "owner": {"login": "Acme-AI", "type": "Organization"},
                    "pushed_at": "2026-04-01T00:00:00Z",
                },
            }
        ],
    }
    org_payload = {
        "login": "Acme-AI",
        "name": "Acme AI",
        "blog": "https://acme.ai",
        "email": None,
        "description": "AI company",
        "public_repos": 5,
        "followers": 10,
    }

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(return_value=Response(200, json=single_org_payload))
        mock.get(f"{ORGS_API}/orgs/Acme-AI").mock(return_value=Response(200, json=org_payload))

        with GitHubAdapter(org_cache=_cache_miss(), rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query))

    assert len(signals) == 1
    assert signals[0].company_name == "Acme AI"


def test_cache_hit_skips_org_api_call(query_dicom: ICPQuery) -> None:
    code_payload = {
        "total_count": 1,
        "incomplete_results": False,
        "items": [
            {
                "name": "train.py",
                "path": "train.py",
                "repository": {
                    "id": 1,
                    "name": "ml",
                    "full_name": "CachedCo/ml",
                    "owner": {"login": "CachedCo", "type": "Organization"},
                    "pushed_at": "2026-04-01T00:00:00Z",
                },
            }
        ],
    }
    cached_org = {
        "login": "CachedCo",
        "name": "Cached Company",
        "blog": "https://cachedco.com",
        "email": None,
        "description": "Cached",
        "public_repos": 3,
        "followers": 5,
    }
    cache = _make_cache()
    _stub_supabase_get(cache, {"data": cached_org, "cached_at": FIXED_NOW.isoformat()})

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(return_value=Response(200, json=code_payload))

        with GitHubAdapter(org_cache=cache, rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query_dicom))

    assert len(signals) == 1
    assert signals[0].company_name == "Cached Company"


def test_code_search_error_skips_keyword_continues() -> None:
    query = ICPQuery(segment="medical-imaging", keywords_strong=("BADKW", "DICOM"))
    code_payload = _load("github_code_search_sample.json")
    org_payload = _load("github_org_sample.json")
    def search_side_effect(request):
        if "BADKW" in str(request.url):
            raise RuntimeError("search failed")
        return Response(200, json=code_payload)

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(side_effect=search_side_effect)
        mock.get(f"{ORGS_API}/orgs/MedVision-AI").mock(
            return_value=Response(200, json=org_payload)
        )

        with GitHubAdapter(org_cache=_cache_miss(), rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query))

    assert len(signals) == 1
    assert signals[0].company_name == "MedVision AI"


def test_domain_extracted_from_email_when_blog_missing(query_dicom: ICPQuery) -> None:
    code_payload = {
        "total_count": 1,
        "incomplete_results": False,
        "items": [
            {
                "name": "train.py",
                "path": "train.py",
                "repository": {
                    "id": 2,
                    "name": "ml",
                    "full_name": "EmailOrg/ml",
                    "owner": {"login": "EmailOrg", "type": "Organization"},
                    "pushed_at": "2026-04-01T00:00:00Z",
                },
            }
        ],
    }
    org_payload_no_blog = {
        "login": "EmailOrg",
        "name": "Email Org",
        "blog": "",
        "email": "hello@emailorg.io",
        "description": "Test",
        "public_repos": 2,
        "followers": 1,
    }

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(return_value=Response(200, json=code_payload))
        mock.get(f"{ORGS_API}/orgs/EmailOrg").mock(
            return_value=Response(200, json=org_payload_no_blog)
        )

        with GitHubAdapter(org_cache=_cache_miss(), rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query_dicom))

    assert len(signals) == 1
    assert signals[0].domain == "emailorg.io"
