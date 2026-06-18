"""dm_wellfound tests via respx."""

from __future__ import annotations

import pytest
from httpx import Response

from dm_wellfound import (
    extract_from_json_ld,
    extract_linkedin_urls,
    scrape_wellfound,
    slugify,
)


def test_slugify_basic():
    assert slugify("Rad AI") == "rad-ai"


def test_slugify_dots():
    assert slugify("kvet.io") == "kvet-io"


def test_slugify_special_chars():
    assert slugify("Deep Vision, Inc.") == "deep-vision-inc"


def test_extract_linkedin_urls_finds_urls():
    html = """<a href="https://linkedin.com/in/sarahchen">Sarah</a>
              <a href="https://www.linkedin.com/in/alexngi">Alex</a>"""
    urls = extract_linkedin_urls(html)
    assert "https://linkedin.com/in/sarahchen" in urls
    assert "https://linkedin.com/in/alexngi" in urls


def test_extract_linkedin_urls_deduplicates():
    html = """<a href="https://linkedin.com/in/dup">1</a>
              <a href="https://linkedin.com/in/dup">2</a>"""
    urls = extract_linkedin_urls(html)
    assert urls.count("https://linkedin.com/in/dup") == 1


def test_extract_from_json_ld_finds_founders():
    html = """<script type="application/json">
    {"startup": {"founders": [{"name": "Alex Ngi", "title": "CTO",
    "linkedinUrl": "https://linkedin.com/in/alexngi"}]}}
    </script>"""
    results = extract_from_json_ld(html, "https://wellfound.com/company/rad-ai")
    assert len(results) == 1
    assert results[0]["first_name"] == "Alex"
    assert results[0]["last_name"] == "Ngi"
    assert results[0]["info"] == "CTO"
    assert results[0]["other_channels"] == [
        {"type": "wellfound", "url": "https://wellfound.com/company/rad-ai"},
    ]


@pytest.mark.respx(base_url="https://wellfound.com")
def test_scrape_wellfound_returns_empty_on_404(respx_mock):
    respx_mock.get("/company/unknown-co").mock(return_value=Response(404))
    results = scrape_wellfound("unknown-co")
    assert results == []
