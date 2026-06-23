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


def test_parse_contacts_with_gemini_returns_contacts(mocker):
    from scripts.dm_team_page import parse_contacts_with_gemini

    response = mocker.MagicMock()
    response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": '[{"name":"Alice Chen","contact_type":"person","info":"CTO","email":null,"phone":null,"linkedin_url":"https://linkedin.com/in/alice","x_url":null,"facebook_url":null,"instagram_url":null,"other_channels":[]}]'
                        }
                    ]
                }
            }
        ]
    }
    post = mocker.patch("scripts.dm_team_page._post_with_retries", return_value=response)

    contacts = parse_contacts_with_gemini(
        "Alice Chen - CTO",
        api_key="key",
        source_url="https://acme.ai/team",
    )

    assert contacts == [
        {
            "name": "Alice Chen",
            "contact_type": "person",
            "info": "CTO",
            "email": None,
            "phone": None,
            "linkedin_url": "https://linkedin.com/in/alice",
            "x_url": None,
            "facebook_url": None,
            "instagram_url": None,
            "other_channels": [{"type": "team_page", "url": "https://acme.ai/team"}],
        }
    ]
    assert post.call_args.kwargs["attempts"] == 3


def test_parse_contacts_with_gemini_invalid_json_returns_empty(mocker, caplog):
    from scripts.dm_team_page import parse_contacts_with_gemini

    response = mocker.MagicMock()
    response.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "not json"}]}}]
    }
    mocker.patch("scripts.dm_team_page._post_with_retries", return_value=response)

    assert parse_contacts_with_gemini("Team text", api_key="key", source_url="https://x/team") == []
    assert "Gemini team-page parsing returned invalid JSON" in caplog.text


def test_fetch_returns_structured_contacts_from_team_page(mocker):
    from scripts.dm_team_page import fetch

    store = mocker.MagicMock()
    store.get_company.return_value = {"website": "https://acme.ai"}
    mocker.patch("scripts.dm_team_page.SupabaseStore", return_value=store)
    mocker.patch(
        "scripts.dm_team_page.find_team_page",
        return_value=("https://acme.ai/team", "<p>Alice Chen - CTO</p>" * 20),
    )
    mocker.patch(
        "scripts.dm_team_page.parse_contacts_with_gemini",
        return_value=[{"name": "Alice Chen", "contact_type": "person"}],
    )
    mocker.patch.dict("os.environ", {"GEMINI_API_KEY": "key"})

    assert fetch("acme.ai") == [{"name": "Alice Chen", "contact_type": "person"}]


def test_main_write_calls_contact_writer(mocker):
    from scripts import dm_team_page

    mocker.patch("scripts.dm_team_page.fetch", return_value=[{"name": "Alice"}])
    writer = mocker.patch("scripts.dm_team_page.write_contacts")
    mocker.patch("sys.argv", ["dm_team_page.py", "--domain", "acme.ai", "--write"])

    dm_team_page.main()

    writer.assert_called_once_with(
        domain="acme.ai",
        source="team_page",
        contacts=[{"name": "Alice"}],
    )
