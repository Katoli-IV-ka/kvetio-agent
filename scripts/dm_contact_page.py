"""Corporate contact email scraper.

CLI:
    python scripts/dm_contact_page.py --domain radai.com
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
from contact_writer import write_contacts
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)

CONTACT_PATHS = [
    "/contact",
    "/contact-us",
    "/about/contact",
    "/reach-us",
    "/get-in-touch",
    "/contacts",
]

CONTACT_PREFIXES = {"info", "hello", "contact", "press", "founders", "team", "support", "hi"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.5",
}

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def extract_emails(html: str, domain: str) -> list[str]:
    """Return corporate emails matching domain with a known contact prefix."""
    found = EMAIL_RE.findall(html)
    results: list[str] = []
    seen: set[str] = set()
    for email in found:
        local, _, host = email.partition("@")
        if host.lower() != domain.lower():
            continue
        if local.lower() not in CONTACT_PREFIXES:
            continue
        if email in seen:
            continue
        seen.add(email)
        results.append(email)
    return results


def find_contact_page(website: str) -> tuple[str, str] | None:
    """Return (url, html) for the first reachable contact path."""
    base = website.rstrip("/")
    for path in CONTACT_PATHS:
        url = base + path
        try:
            resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
        except Exception as exc:
            logger.debug("contact page %s failed: %s", url, exc)
            continue
        if resp.status_code == 200 and len(resp.text) > 200:
            return url, resp.text
    return None


def fetch(domain: str) -> list[dict]:
    """Return corporate contact records for a domain."""
    store = SupabaseStore()
    row = store.get_company(domain)
    website = (row or {}).get("website", "")
    if not website:
        logger.info("No website for %s", domain)
        return []

    result = find_contact_page(website)
    if not result:
        logger.info("No contact page found for %s", domain)
        return []

    url, html = result
    emails = extract_emails(html, domain)
    if not emails:
        logger.info("No contact emails found on %s", url)
        return []

    return [
        {
            "name": "Contact",
            "contact_type": "organization",
            "info": f"General contact address found on {url}",
            "email": email,
            "phone": None,
            "linkedin_url": None,
            "x_url": None,
            "facebook_url": None,
            "instagram_url": None,
            "other_channels": [{"type": "contact_page", "url": url}],
        }
        for email in emails
    ]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Corporate contact page scraper")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    results = fetch(args.domain)
    if args.write:
        write_contacts(domain=args.domain, source="contact_page", contacts=results)
        return
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
