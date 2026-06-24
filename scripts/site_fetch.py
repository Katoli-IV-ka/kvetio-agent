"""Fetch a company site as compact JSON for SiteResearchAgent.

The preferred engine is the agent-browser CLI because it returns an accessibility
snapshot instead of raw HTML. If the CLI is unavailable or one fetch fails, this
module falls back to httpx plus BeautifulSoup.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

_LINK_RULES: list[tuple[str, str]] = [
    ("linkedin", r"linkedin\.com"),
    ("github", r"github\.com"),
    ("huggingface", r"huggingface\.co"),
    ("x", r"(?:twitter\.com|x\.com)"),
    ("facebook", r"facebook\.com"),
    ("instagram", r"instagram\.com"),
]

_PRIORITY_KEYWORDS = (
    "about",
    "team",
    "career",
    "job",
    "blog",
    "news",
    "press",
    "pricing",
    "contact",
    "company",
)


def classify_link(url: str) -> str | None:
    """Return the external-link type for a URL, or None if not recognized."""
    if url.lower().startswith("mailto:"):
        return "email"
    for kind, pattern in _LINK_RULES:
        if re.search(pattern, url, re.IGNORECASE):
            return kind
    return None


def _host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _same_host(base: str, url: str) -> bool:
    return _host(base) == _host(url)


def _email_from_mailto(url: str) -> str:
    return url[len("mailto:") :].split("?")[0].strip()


def parse_snapshot(page_url: str, snapshot: dict) -> dict:
    """Turn an agent-browser snapshot payload into structured page data."""
    text = snapshot.get("snapshot", "") or ""
    external_links: list[dict] = []
    internal_links: list[dict] = []
    emails: list[str] = []
    seen_ext: set[str] = set()
    seen_internal: set[str] = set()

    for ref in (snapshot.get("refs") or {}).values():
        url = ref.get("url")
        if not url:
            continue
        url = urljoin(page_url, url)
        kind = classify_link(url)
        if kind == "email":
            addr = _email_from_mailto(url)
            if addr and addr not in emails:
                emails.append(addr)
        elif kind is not None:
            if url not in seen_ext:
                external_links.append({"type": kind, "url": url})
                seen_ext.add(url)
        elif url.startswith("http") and _same_host(page_url, url) and url not in seen_internal:
            internal_links.append({"url": url, "name": ref.get("name", "")})
            seen_internal.add(url)

    return {
        "url": page_url,
        "text": text,
        "external_links": external_links,
        "internal_links": internal_links,
        "emails": emails,
    }


def select_subpages(internal_links: list[dict], max_pages: int = 5) -> list[str]:
    """Pick up to max_pages internal URLs, prioritizing keyword-bearing ones."""

    def score(link: dict) -> int:
        haystack = (link["url"] + " " + link.get("name", "")).lower()
        return sum(1 for keyword in _PRIORITY_KEYWORDS if keyword in haystack)

    ranked = sorted(internal_links, key=score, reverse=True)
    chosen: list[str] = []
    for link in ranked:
        if score(link) == 0:
            continue
        if link["url"] not in chosen:
            chosen.append(link["url"])
        if len(chosen) >= max_pages:
            break
    return chosen


def parse_html_fallback(page_url: str, html: str) -> dict:
    """Fallback parser using BeautifulSoup, with the same shape as parse_snapshot."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())

    external_links: list[dict] = []
    internal_links: list[dict] = []
    emails: list[str] = []
    seen_ext: set[str] = set()
    seen_internal: set[str] = set()

    for anchor in soup.find_all("a", href=True):
        url = urljoin(page_url, anchor["href"])
        kind = classify_link(url)
        if kind == "email":
            addr = _email_from_mailto(url)
            if addr and addr not in emails:
                emails.append(addr)
        elif kind is not None:
            if url not in seen_ext:
                external_links.append({"type": kind, "url": url})
                seen_ext.add(url)
        elif url.startswith("http") and _same_host(page_url, url) and url not in seen_internal:
            internal_links.append({"url": url, "name": anchor.get_text(strip=True)})
            seen_internal.add(url)

    return {
        "url": page_url,
        "text": text,
        "external_links": external_links,
        "internal_links": internal_links,
        "emails": emails,
    }


def resolve_engine() -> str:
    """Return agent-browser if the CLI is on PATH, else fallback."""
    return "agent-browser" if shutil.which("agent-browser") else "fallback"


def _http_get(url: str, timeout: float | None = 15.0) -> str:
    """Minimal GET for the fallback path. Raises on failure."""
    import httpx

    response = httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "kvetio-site-fetch/1.0"},
    )
    response.raise_for_status()
    return response.text


def _agent_browser_snapshot(url: str, domain: str, max_output: int) -> dict:
    """Open URL in agent-browser and return the snapshot data payload."""
    allowed = f"{domain},*.{domain}"
    cmd = [
        "agent-browser",
        "--json",
        "--allowed-domains",
        allowed,
        "--max-output",
        str(max_output),
        "batch",
        f"open {url}",
        "wait --load networkidle",
        "snapshot -i --urls",
    ]
    output = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
    payload = json.loads(output.stdout)
    steps = payload if isinstance(payload, list) else [payload]
    snapshot = steps[-1]
    return snapshot.get("data", snapshot)


def _fetch_one_agent_browser(url: str, domain: str, max_output: int) -> dict | None:
    try:
        snapshot = _agent_browser_snapshot(url, domain, max_output)
    except (subprocess.SubprocessError, OSError, ValueError, json.JSONDecodeError):
        return None
    return parse_snapshot(url, snapshot)


def _fetch_one_fallback(url: str) -> dict | None:
    try:
        html = _http_get(url)
    except Exception:
        return None
    return parse_html_fallback(url, html)


def _normalize_domain(domain: str) -> str:
    parsed = urlparse(domain if "://" in domain else f"https://{domain}")
    return (parsed.netloc or parsed.path).strip("/").lower().removeprefix("www.")


def fetch_site(domain: str, max_pages: int = 5, max_output: int = 50000) -> dict:
    """Fetch a company site and return compact structured data."""
    domain = _normalize_domain(domain)
    engine = resolve_engine()

    def fetch_one(url: str) -> dict | None:
        if engine == "agent-browser":
            page = _fetch_one_agent_browser(url, domain, max_output)
            if page is not None:
                return page
        return _fetch_one_fallback(url)

    home = None
    for candidate in (f"https://{domain}", f"https://www.{domain}"):
        home = fetch_one(candidate)
        if home is not None:
            break

    if home is None:
        return {
            "domain": domain,
            "engine": engine,
            "reachable": False,
            "pages": [],
            "external_links": [],
            "emails": [],
        }

    pages = [{"url": home["url"], "text": home["text"]}]
    external = list(home["external_links"])
    emails = list(home["emails"])
    ext_seen = {link["url"] for link in external}

    for sub_url in select_subpages(home["internal_links"], max_pages=max_pages):
        subpage = fetch_one(sub_url)
        if subpage is None:
            continue
        pages.append({"url": subpage["url"], "text": subpage["text"]})
        for link in subpage["external_links"]:
            if link["url"] not in ext_seen:
                external.append(link)
                ext_seen.add(link["url"])
        for addr in subpage["emails"]:
            if addr not in emails:
                emails.append(addr)

    return {
        "domain": domain,
        "engine": engine,
        "reachable": True,
        "pages": pages,
        "external_links": external,
        "emails": emails,
    }


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a company site as compact JSON")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--max-pages", type=int, default=_env_int("SITE_FETCH_MAX_PAGES", 5))
    parser.add_argument(
        "--max-output",
        type=int,
        default=_env_int("SITE_FETCH_MAX_OUTPUT", 50000),
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON (default)")
    args = parser.parse_args()
    result = fetch_site(args.domain, max_pages=args.max_pages, max_output=args.max_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
