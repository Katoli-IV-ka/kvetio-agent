"""dm_team_page tests."""

from __future__ import annotations

import pytest
from httpx import Response

from dm_team_page import TEAM_PATHS, clean_html, extract_linkedin_urls, find_team_page


def test_clean_html_strips_scripts():
    html = "<html><script>alert(1)</script><p>Sarah Chen - Head of ML</p></html>"
    text = clean_html(html)
    assert "alert" not in text
    assert "Sarah Chen" in text


def test_clean_html_strips_nav():
    html = "<nav>Menu</nav><main><p>Alex Ngi - CTO</p></main>"
    text = clean_html(html)
    assert "Menu" not in text
    assert "Alex Ngi" in text


def test_clean_html_truncates_at_6000():
    html = "<p>" + "x" * 10000 + "</p>"
    text = clean_html(html)
    assert len(text) <= 6000


def test_extract_linkedin_urls_finds_profiles():
    html = """<a href="https://linkedin.com/in/sarahchen">Profile</a>"""
    urls = extract_linkedin_urls(html)
    assert "https://linkedin.com/in/sarahchen" in urls


def test_team_paths_contains_common_paths():
    assert "/team" in TEAM_PATHS
    assert "/about" in TEAM_PATHS
    assert "/people" in TEAM_PATHS


@pytest.mark.respx(base_url="https://radai.com", assert_all_called=False)
def test_find_team_page_returns_first_200(respx_mock):
    respx_mock.get("/team").mock(return_value=Response(404))
    respx_mock.get("/about").mock(
        return_value=Response(200, text="<p>Sarah Chen - Head of ML at Rad AI</p>" * 20)
    )
    for path in TEAM_PATHS[2:]:
        respx_mock.get(path).mock(return_value=Response(404))
    result = find_team_page("https://radai.com")
    assert result is not None
    url, html = result
    assert url == "https://radai.com/about"
    assert "Sarah Chen" in html


@pytest.mark.respx(base_url="https://nodomain.com")
def test_find_team_page_returns_none_on_all_404(respx_mock):
    for path in TEAM_PATHS:
        respx_mock.get(path).mock(return_value=Response(404))
    result = find_team_page("https://nodomain.com")
    assert result is None
