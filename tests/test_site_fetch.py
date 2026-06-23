from scripts.site_fetch import (
    classify_link,
    fetch_site,
    parse_html_fallback,
    parse_snapshot,
    resolve_engine,
    select_subpages,
)


def test_classify_link_types():
    assert classify_link("https://www.linkedin.com/company/acme") == "linkedin"
    assert classify_link("https://github.com/acme") == "github"
    assert classify_link("https://huggingface.co/acme") == "huggingface"
    assert classify_link("https://twitter.com/acme") == "x"
    assert classify_link("https://x.com/acme") == "x"
    assert classify_link("https://facebook.com/acme") == "facebook"
    assert classify_link("https://instagram.com/acme") == "instagram"
    assert classify_link("mailto:hello@acme.ai") == "email"
    assert classify_link("https://acme.ai/random") is None


def test_parse_snapshot_extracts_links_emails_text():
    snapshot = {
        "snapshot": '- heading "Acme"\n- link "LinkedIn"\n- link "Careers"',
        "refs": {
            "e1": {"role": "heading", "name": "Acme"},
            "e2": {
                "role": "link",
                "name": "LinkedIn",
                "url": "https://linkedin.com/company/acme",
            },
            "e3": {"role": "link", "name": "Careers", "url": "https://acme.ai/careers"},
            "e4": {"role": "link", "name": "Email", "url": "mailto:hi@acme.ai"},
        },
    }
    parsed = parse_snapshot("https://acme.ai", snapshot)
    assert parsed["text"].startswith("- heading")
    assert {"type": "linkedin", "url": "https://linkedin.com/company/acme"} in parsed[
        "external_links"
    ]
    assert "hi@acme.ai" in parsed["emails"]
    assert "https://acme.ai/careers" in [link["url"] for link in parsed["internal_links"]]


def test_select_subpages_prioritizes_keywords():
    links = [
        {"url": "https://acme.ai/blog/post-1", "name": "Blog post 1"},
        {"url": "https://acme.ai/about", "name": "About us"},
        {"url": "https://acme.ai/random", "name": "Random"},
        {"url": "https://acme.ai/careers", "name": "Careers"},
        {"url": "https://acme.ai/pricing", "name": "Pricing"},
    ]
    chosen = select_subpages(links, max_pages=3)
    assert "https://acme.ai/about" in chosen
    assert "https://acme.ai/careers" in chosen
    assert len(chosen) == 3
    assert "https://acme.ai/random" not in chosen


def test_parse_html_fallback_extracts_links_text():
    html = """
    <html><head><title>Acme</title></head>
    <body>
      <h1>Acme builds models</h1>
      <a href="https://github.com/acme">GitHub</a>
      <a href="https://acme.ai/team">Team</a>
      <a href="mailto:hi@acme.ai">Email</a>
    </body></html>
    """
    parsed = parse_html_fallback("https://acme.ai", html)
    assert "Acme builds models" in parsed["text"]
    assert {"type": "github", "url": "https://github.com/acme"} in parsed["external_links"]
    assert "hi@acme.ai" in parsed["emails"]
    assert "https://acme.ai/team" in [link["url"] for link in parsed["internal_links"]]


def test_resolve_engine_prefers_agent_browser_when_present(monkeypatch):
    monkeypatch.setattr("scripts.site_fetch.shutil.which", lambda name: "/usr/local/bin/agent-browser")
    assert resolve_engine() == "agent-browser"


def test_resolve_engine_falls_back_when_absent(monkeypatch):
    monkeypatch.setattr("scripts.site_fetch.shutil.which", lambda name: None)
    assert resolve_engine() == "fallback"


def test_fetch_site_unreachable_via_fallback(monkeypatch):
    monkeypatch.setattr("scripts.site_fetch.resolve_engine", lambda: "fallback")

    def boom(url, timeout=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("scripts.site_fetch._http_get", boom)
    result = fetch_site("dead.example", max_pages=3)
    assert result["reachable"] is False
    assert result["engine"] == "fallback"
    assert result["pages"] == []


def test_fetch_site_reachable_via_fallback(monkeypatch):
    monkeypatch.setattr("scripts.site_fetch.resolve_engine", lambda: "fallback")

    def fake_get(url, timeout=None):
        if url == "https://acme.ai":
            return (
                "<html><body><h1>Acme</h1>"
                "<a href='https://github.com/acme'>gh</a>"
                "<a href='https://acme.ai/about'>About</a></body></html>"
            )
        if url == "https://acme.ai/about":
            return "<html><body><h1>About Acme</h1></body></html>"
        raise RuntimeError("404")

    monkeypatch.setattr("scripts.site_fetch._http_get", fake_get)
    result = fetch_site("acme.ai", max_pages=3)
    assert result["reachable"] is True
    assert result["domain"] == "acme.ai"
    assert any(link["type"] == "github" for link in result["external_links"])
    assert len(result["pages"]) >= 1
