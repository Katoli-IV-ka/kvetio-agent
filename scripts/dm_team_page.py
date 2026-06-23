"""Website team page fetcher: cleaned text for agent-side LLM parsing.

CLI:
    python scripts/dm_team_page.py --domain radai.com

Writes plain text, not JSON. The agent extracts structured contacts.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from contact_writer import write_contacts
from supabase_store import SupabaseStore
from translate import DEFAULT_GEMINI_TRANSLATION_MODEL, GEMINI_ENDPOINT, _post_with_retries

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


def _team_page_prompt(text: str, source_url: str) -> str:
    return (
        "Extract decision-maker contacts from this company team/about page. "
        "Return only a JSON array. Each item must contain exactly these keys: "
        "name, contact_type, info, email, phone, linkedin_url, x_url, "
        "facebook_url, instagram_url, other_channels. Use contact_type='person' "
        "for named people and 'organization' only for company-level channels. "
        "Use null for unknown scalar fields and [] for other_channels. "
        "Do not invent emails, titles, links, or people. Source URL: "
        f"{source_url}\n\n{text}"
    )


def _extract_gemini_text(data: dict[str, Any]) -> str:
    return (
        data.get("candidates", [{}])[0]
        .get("content", {})
        .get("parts", [{}])[0]
        .get("text", "")
    )


def _normalize_contact_from_team_page(contact: dict, source_url: str) -> dict | None:
    name = str(contact.get("name") or "").strip()
    if not name:
        return None
    normalized = {
        "name": name,
        "contact_type": contact.get("contact_type") or "person",
        "info": contact.get("info"),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "linkedin_url": contact.get("linkedin_url"),
        "x_url": contact.get("x_url"),
        "facebook_url": contact.get("facebook_url"),
        "instagram_url": contact.get("instagram_url"),
        "other_channels": [
            item for item in (contact.get("other_channels") or [])
            if isinstance(item, dict)
        ],
    }
    if not any(
        item.get("type") == "team_page" and item.get("url") == source_url
        for item in normalized["other_channels"]
    ):
        normalized["other_channels"].append({"type": "team_page", "url": source_url})
    return normalized


def parse_contacts_with_gemini(
    text: str,
    *,
    api_key: str,
    source_url: str,
    model: str = DEFAULT_GEMINI_TRANSLATION_MODEL,
) -> list[dict]:
    payload = {
        "contents": [{"role": "user", "parts": [{"text": _team_page_prompt(text, source_url)}]}],
        "generationConfig": {"temperature": 0.1},
    }
    headers = {"x-goog-api-key": api_key, "Content-Type": "application/json"}
    response = _post_with_retries(
        GEMINI_ENDPOINT.format(model=model),
        payload,
        headers,
        timeout=30.0,
        attempts=3,
    )
    raw_text = _extract_gemini_text(response.json()).strip()
    if raw_text.startswith("```"):
        raw_text = raw_text.strip("`")
        raw_text = raw_text.removeprefix("json").strip()
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("Gemini team-page parsing returned invalid JSON for %s", source_url)
        return []
    if not isinstance(parsed, list):
        logger.warning("Gemini team-page parsing returned non-list JSON for %s", source_url)
        return []
    contacts: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_contact_from_team_page(item, source_url)
        if normalized:
            contacts.append(normalized)
    return contacts


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


def fetch(domain: str) -> list[dict]:
    """Return structured contacts extracted from a company team/about page."""
    store = SupabaseStore()
    row = store.get_company(domain)
    website = (row or {}).get("website", "") or f"https://{domain}"

    result = find_team_page(website)
    if not result:
        logger.info("No team page found for %s", domain)
        return []

    url, html = result
    text = clean_html(html)
    linkedin_urls = extract_linkedin_urls(html)
    if linkedin_urls:
        text += "\n\nLinkedIn URLs:\n" + "\n".join(linkedin_urls)

    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        logger.warning("GEMINI_API_KEY not set; skipping team-page parsing for %s", domain)
        return []

    try:
        return parse_contacts_with_gemini(text, api_key=api_key, source_url=url)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Gemini team-page parsing failed for %s: %s", domain, exc)
        return []


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Team page fetcher")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    results = fetch(args.domain)
    if args.write:
        write_contacts(domain=args.domain, source="team_page", contacts=results)
        return
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
