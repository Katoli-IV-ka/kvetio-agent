"""dm_apollo tests via respx."""

from __future__ import annotations

import pytest
from httpx import Response

from dm_apollo import APOLLO_BASE, TITLE_KEYWORDS, fetch, search_people


@pytest.mark.respx(base_url=APOLLO_BASE)
def test_search_people_maps_response(respx_mock):
    respx_mock.post("/mixed_people/search").mock(
        return_value=Response(200, json={
            "people": [{
                "name": "Sarah Chen",
                "first_name": "Sarah",
                "last_name": "Chen",
                "title": "Head of ML",
                "linkedin_url": "https://linkedin.com/in/sarahchen",
                "email_status": "verified",
                "seniority": "vp",
            }]
        })
    )
    results = search_people("radai.com", "test_key")
    assert len(results) == 1
    assert results[0]["name"] == "Sarah Chen"
    assert results[0]["contact_type"] == "person"
    assert results[0]["info"] == "Head of ML"
    assert results[0]["email"] is None
    assert results[0]["linkedin_url"] == "https://linkedin.com/in/sarahchen"
    assert results[0]["other_channels"] == []


@pytest.mark.respx(base_url=APOLLO_BASE)
def test_search_people_empty_result(respx_mock):
    respx_mock.post("/mixed_people/search").mock(
        return_value=Response(200, json={"people": []})
    )
    results = search_people("unknown.com", "test_key")
    assert results == []


@pytest.mark.respx(base_url=APOLLO_BASE)
def test_search_people_handles_api_error(respx_mock):
    respx_mock.post("/mixed_people/search").mock(
        return_value=Response(429, json={"error": "rate limit"})
    )
    results = search_people("radai.com", "test_key")
    assert results == []


def test_fetch_returns_empty_without_api_key(monkeypatch):
    monkeypatch.delenv("APOLLO_API_KEY", raising=False)
    results = fetch("radai.com")
    assert results == []


def test_title_keywords_covers_key_roles():
    keywords_lower = [keyword.lower() for keyword in TITLE_KEYWORDS]
    assert any("head of data" in keyword for keyword in keywords_lower)
    assert any("cto" in keyword for keyword in keywords_lower)
    assert any("head of ml" in keyword or "machine learning" in keyword for keyword in keywords_lower)


def test_title_keywords_include_mid_level():
    from scripts.dm_apollo import TITLE_KEYWORDS
    assert "ml engineer" in TITLE_KEYWORDS
    assert "research scientist" in TITLE_KEYWORDS
    assert "data scientist" in TITLE_KEYWORDS
    assert "product manager" in TITLE_KEYWORDS


def test_seniorities_include_manager():
    from scripts.dm_apollo import SENIORITIES
    assert "manager" in SENIORITIES
    assert "senior" in SENIORITIES


def test_search_people_uses_per_page_25():
    from scripts.dm_apollo import search_people
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.json.return_value = {"people": []}
    mock_resp.raise_for_status = MagicMock()

    with patch("scripts.dm_apollo.httpx.post", return_value=mock_resp) as mock_post:
        search_people("radai.com", "fake-key")
        # httpx.post is called with json= kwarg
        actual_payload = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert actual_payload["per_page"] == 25
