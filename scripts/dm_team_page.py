"""Website team page fetcher: cleaned text for agent-side LLM parsing.

CLI:
    python scripts/dm_team_page.py --domain radai.com

Writes plain text, not JSON. The agent extracts structured contacts.
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)

TEAM_PATHS = [
    "/team",
    "/about",
    "/people",
    "/leadership",
    "/company",
    "/company/team",
    "/about-us",
    "/about/team",
    "/our-team",
    "/who-we-are",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

LINKEDIN_RE = re.compile(
    r'https?://(?:www\.)?linkedin\.com/in/([^"\'\s/>]+)', re.IGNORECASE
)


def clean_html(html: str) -> str:
    """Strip non-content tags and return clean text capped at 6000 chars."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "meta", "link"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:6000]


def extract_linkedin_urls(html: str) -> list[str]:
    """Find unique LinkedIn /in/ profile URLs and canonicalize without www."""
    slugs = LINKEDIN_RE.findall(html)
    seen: set[str] = set()
    result: list[str] = []
    for slug in slugs:
        if slug not in seen:
            seen.add(slug)
            result.append(f"https://linkedin.com/in/{slug}")
    return result[:20]


def find_team_page(website: str) -> tuple[str, str] | None:
    """Return (url, html) for the first useful team/about page."""
    base = website.rstrip("/")
    for path in TEAM_PATHS:
        url = base + path
        try:
            resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        except Exception as exc:
            logger.debug("team page %s failed: %s", url, exc)
            continue
        if resp.status_code == 200 and len(resp.text) > 500:
            return url, resp.text
    return None


def fetch(domain: str) -> str:
    """Return cleaned page text or an empty string if no team page is found."""
    store = SupabaseStore()
    row = store.get_company(domain)
    website = (row or {}).get("website", "")
    if not website:
        logger.info("No website for %s", domain)
        return ""

    result = find_team_page(website)
    if not result:
        logger.info("No team page found for %s", domain)
        return ""

    url, html = result
    text = clean_html(html)
    linkedin_urls = extract_linkedin_urls(html)

    output = f"[SOURCE: {url}]\n\n{text}"
    if linkedin_urls:
        output += "\n\n[LINKEDIN_URLS]\n" + "\n".join(linkedin_urls)
    return output


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Team page fetcher")
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()
    print(fetch(args.domain))


if __name__ == "__main__":
    main()
