"""Tests for GitHubAdapter."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest
import respx
from httpx import Response

from github import ORGS_API, SEARCH_API, GitHubAdapter
from models import ICPQuery

FIXTURES = Path(__file__).parent / "fixtures"
FIXED_NOW = datetime(2026, 5, 1, tzinfo=timezone.utc)


def _load(name: str) -> dict | list:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def fixed_now(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("github._utcnow", lambda: FIXED_NOW)


@pytest.fixture
def query_dicom() -> ICPQuery:
    return ICPQuery(segment="medical-imaging", keywords_strong=("DICOM",))


# -- GitHubAdapter ------------------------------------------------------------


def test_filters_user_accounts_and_inactive_orgs(query_dicom: ICPQuery) -> None:
    code_payload = _load("github_code_search_sample.json")
    org_payload = _load("github_org_sample.json")

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(return_value=Response(200, json=code_payload))
        mock.get(f"{ORGS_API}/orgs/MedVision-AI").mock(
            return_value=Response(200, json=org_payload)
        )

        with GitHubAdapter(rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query_dicom))

    assert len(signals) == 1
    signal = signals[0]
    assert signal.company_name == "MedVision AI"
    assert signal.source == "github"
    assert signal.signal_type == "github_repo"


def test_github_adapter_does_not_require_supabase_env(
    monkeypatch: pytest.MonkeyPatch,
    query_dicom: ICPQuery,
) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    code_payload = _load("github_code_search_sample.json")
    org_payload = _load("github_org_sample.json")

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(return_value=Response(200, json=code_payload))
        mock.get(f"{ORGS_API}/orgs/MedVision-AI").mock(
            return_value=Response(200, json=org_payload)
        )

        with GitHubAdapter(rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query_dicom))

    assert len(signals) == 1
    assert signals[0].company_name == "MedVision AI"


def test_signal_fields(query_dicom: ICPQuery) -> None:
    code_payload = _load("github_code_search_sample.json")
    org_payload = _load("github_org_sample.json")

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(return_value=Response(200, json=code_payload))
        mock.get(f"{ORGS_API}/orgs/MedVision-AI").mock(
            return_value=Response(200, json=org_payload)
        )

        with GitHubAdapter(rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query_dicom))

    signal = signals[0]
    assert signal.domain == "medvision.ai"
    assert signal.url == "https://github.com/MedVision-AI"
    assert signal.signal_date == date(2026, 4, 20)
    assert signal.confidence == "medium"
    assert signal.linkedin_url is None
    assert signal.payload["org_login"] == "MedVision-AI"
    assert signal.payload["repo_count"] == 12


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

        with GitHubAdapter(rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query))

    assert len(signals) == 1
    assert signals[0].company_name == "Acme AI"


def test_org_metadata_is_fetched_from_github_api(query_dicom: ICPQuery) -> None:
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
                    "full_name": "FetchedCo/ml",
                    "owner": {"login": "FetchedCo", "type": "Organization"},
                    "pushed_at": "2026-04-01T00:00:00Z",
                },
            }
        ],
    }
    org_payload = {
        "login": "FetchedCo",
        "name": "Fetched Company",
        "blog": "https://fetchedco.com",
        "email": None,
        "description": "Fetched",
        "public_repos": 3,
        "followers": 5,
    }

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(return_value=Response(200, json=code_payload))
        org_route = mock.get(f"{ORGS_API}/orgs/FetchedCo").mock(
            return_value=Response(200, json=org_payload)
        )

        with GitHubAdapter(rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query_dicom))

    assert org_route.called
    assert len(signals) == 1
    assert signals[0].company_name == "Fetched Company"


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

        with GitHubAdapter(rate_limit_rps=0) as adapter:
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

        with GitHubAdapter(rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query_dicom))

    assert len(signals) == 1
    assert signals[0].domain == "emailorg.io"
