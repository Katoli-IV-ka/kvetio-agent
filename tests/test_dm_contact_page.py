"""Tests for dm_contact_page — corporate contact email scraper."""
from unittest.mock import MagicMock, patch


def test_extract_emails_finds_info_address():
    from scripts.dm_contact_page import extract_emails
    html = '<a href="mailto:info@radai.com">Contact us</a>'
    assert extract_emails(html, "radai.com") == ["info@radai.com"]


def test_extract_emails_ignores_other_domain():
    from scripts.dm_contact_page import extract_emails
    html = '<a href="mailto:info@other.com">Contact</a>'
    assert extract_emails(html, "radai.com") == []


def test_extract_emails_ignores_personal_prefix():
    from scripts.dm_contact_page import extract_emails
    html = "john.doe@radai.com"
    assert extract_emails(html, "radai.com") == []


def test_extract_emails_deduplicates():
    from scripts.dm_contact_page import extract_emails
    html = "info@radai.com info@radai.com hello@radai.com"
    result = extract_emails(html, "radai.com")
    assert result.count("info@radai.com") == 1
    assert "hello@radai.com" in result


def test_extract_emails_finds_multiple_known_prefixes():
    from scripts.dm_contact_page import extract_emails
    html = "info@acme.io press@acme.io founders@acme.io"
    result = extract_emails(html, "acme.io")
    assert set(result) == {"info@acme.io", "press@acme.io", "founders@acme.io"}


def test_find_contact_page_returns_none_when_all_404():
    from scripts.dm_contact_page import find_contact_page
    with patch("scripts.dm_contact_page.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=404, text="not found")
        result = find_contact_page("https://example.com")
    assert result is None


def test_find_contact_page_returns_url_and_html_on_success():
    from scripts.dm_contact_page import find_contact_page
    long_html = "<html>" + "x" * 300 + "</html>"
    with patch("scripts.dm_contact_page.httpx.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, text=long_html)
        result = find_contact_page("https://example.com")
    assert result is not None
    url, html = result
    assert url.startswith("https://example.com")
    assert html == long_html


def test_fetch_returns_empty_when_no_website(mocker):
    from scripts.dm_contact_page import fetch
    mock_store = MagicMock()
    mock_store.get_company.return_value = {}
    mocker.patch("scripts.dm_contact_page.SupabaseStore", return_value=mock_store)
    assert fetch("radai.com") == []


def test_fetch_returns_contact_records(mocker):
    from scripts.dm_contact_page import fetch
    mock_store = MagicMock()
    mock_store.get_company.return_value = {"website": "https://radai.com"}
    mocker.patch("scripts.dm_contact_page.SupabaseStore", return_value=mock_store)

    long_html = "info@radai.com " + "x" * 300
    mocker.patch(
        "scripts.dm_contact_page.find_contact_page",
        return_value=("https://radai.com/contact", long_html),
    )

    result = fetch("radai.com")
    assert len(result) == 1
    assert result[0]["first_name"] == "Contact"
    assert result[0]["last_name"] == ""
    assert result[0]["info"] == "General contact address found on https://radai.com/contact"
    assert result[0]["email"] == "info@radai.com"
    assert result[0]["other_channels"] == [
        {"type": "contact_page", "url": "https://radai.com/contact"},
    ]
