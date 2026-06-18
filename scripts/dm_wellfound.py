"""Wellfound DM fetcher: founder/profile scraping.

CLI:
    python scripts/dm_wellfound.py --domain radai.com

Reads company.name from Supabase, builds a Wellfound slug, and writes JSON.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)

LINKEDIN_RE = re.compile(
    r'https?://(?:www\.)?linkedin\.com/in/([^"\'\s/>]+)', re.IGNORECASE
)
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.5",
}


def _split_name(name: str) -> tuple[str, str]:
    parts = (name or "").strip().split(maxsplit=1)
    return (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")


def slugify(name: str) -> str:
    """Convert a company name to a Wellfound-style slug."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def extract_linkedin_urls(html: str) -> list[str]:
    """Find unique LinkedIn /in/ profile URLs and canonicalize without www."""
    slugs = LINKEDIN_RE.findall(html)
    seen: set[str] = set()
    result: list[str] = []
    for slug in slugs:
        if slug not in seen:
            seen.add(slug)
            result.append(f"https://linkedin.com/in/{slug}")
    return result


def extract_from_json_ld(html: str, source_url: str) -> list[dict]:
    """Extract founder/team people from embedded JSON script tags."""
    script_re = re.compile(
        r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
        re.DOTALL,
    )
    for match in script_re.finditer(html):
        try:
            data = json.loads(match.group(1))
        except Exception:
            continue
        if "founder" not in str(data).lower() and "team" not in str(data).lower():
            continue
        results = _parse_people_from_json(data, source_url)
        if results:
            return results
    return []


def _parse_people_from_json(data: dict, source_url: str) -> list[dict]:
    results: list[dict] = []
    startup = data.get("startup") or data
    for key in ("founders", "team", "people", "members"):
        people = startup.get(key) or []
        if not isinstance(people, list):
            continue
        for person in people:
            if not isinstance(person, dict):
                continue
            name = person.get("name") or person.get("fullName")
            if not name:
                continue
            first_name, last_name = _split_name(name)
            results.append({
                "first_name": first_name,
                "last_name": last_name,
                "info": person.get("title") or person.get("role"),
                "email": None,
                "phone": None,
                "linkedin_url": person.get("linkedinUrl") or person.get("linkedin_url"),
                "x_url": None,
                "facebook_url": None,
                "instagram_url": None,
                "other_channels": [{"type": "wellfound", "url": source_url}],
            })
    return results


def scrape_wellfound(slug: str) -> list[dict]:
    """Scrape a Wellfound company page by slug."""
    url = f"https://wellfound.com/company/{slug}"
    try:
        resp = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
    except Exception as exc:
        logger.warning("Wellfound fetch failed for %s: %s", slug, exc)
        return []

    if resp.status_code != 200:
        logger.info("Wellfound %s returned HTTP %s", slug, resp.status_code)
        return []

    html = resp.text
    results = extract_from_json_ld(html, url)
    if results:
        return results

    for linkedin_url in extract_linkedin_urls(html)[:5]:
        slug_part = linkedin_url.rstrip("/").split("/")[-1]
        first_name, last_name = _split_name(slug_part.replace("-", " ").title())
        results.append({
            "first_name": first_name,
            "last_name": last_name,
            "info": None,
            "email": None,
            "phone": None,
            "linkedin_url": linkedin_url,
            "x_url": None,
            "facebook_url": None,
            "instagram_url": None,
            "other_channels": [{"type": "wellfound", "url": url}],
        })
    return results


def fetch(domain: str) -> list[dict]:
    store = SupabaseStore()
    row = store.get_company(domain)
    name = (row or {}).get("name", "")
    if not name:
        logger.warning("Company name not found for %s", domain)
        return []
    return scrape_wellfound(slugify(name))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Wellfound DM fetcher")
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()
    print(json.dumps(fetch(args.domain), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
