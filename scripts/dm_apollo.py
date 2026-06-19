"""Apollo.io DM fetcher: People Search without email-credit reveal.

CLI:
    python scripts/dm_apollo.py --domain radai.com

Requires APOLLO_API_KEY in .env or environment.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))

logger = logging.getLogger(__name__)
load_dotenv(Path(__file__).parent.parent / ".env")

APOLLO_BASE = "https://api.apollo.io/v1"

TITLE_KEYWORDS = [
    "head of data",
    "vp of data",
    "director of data",
    "head of ml",
    "head of machine learning",
    "vp machine learning",
    "vp of ml",
    "head of ai",
    "vp of ai",
    "chief ai officer",
    "research lead",
    "head of research",
    "research director",
    "machine learning lead",
    "ml platform",
    "ml infrastructure",
    "cto",
    "co-founder",
    "chief technology officer",
    "head of engineering",
    # mid-level
    "ml engineer",
    "machine learning engineer",
    "research scientist",
    "applied scientist",
    "data scientist",
    "product manager",
    "head of product",
]

SENIORITIES = ["vp", "director", "c_suite", "founder", "partner", "senior", "manager"]


def _split_name(name: str) -> tuple[str, str]:
    parts = (name or "").strip().split(maxsplit=1)
    return (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")


def search_people(domain: str, api_key: str) -> list[dict]:
    """POST /mixed_people/search without requesting revealed email addresses."""
    payload = {
        "api_key": api_key,
        "q_organization_domains": domain,
        "person_titles": TITLE_KEYWORDS,
        "person_seniorities": SENIORITIES,
        "page": 1,
        "per_page": 25,
    }
    try:
        resp = httpx.post(
            f"{APOLLO_BASE}/mixed_people/search",
            json=payload,
            headers={"Content-Type": "application/json", "Cache-Control": "no-cache"},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        logger.warning("Apollo search failed for %s: %s", domain, exc)
        return []

    results: list[dict] = []
    for person in data.get("people", []):
        name = person.get("name")
        if not name:
            name = " ".join(
                part for part in (person.get("first_name"), person.get("last_name")) if part
            )
        results.append({
            "name": name,
            "contact_type": "person",
            "info": person.get("title") or person.get("seniority"),
            "email": None,
            "phone": None,
            "linkedin_url": person.get("linkedin_url"),
            "x_url": None,
            "facebook_url": None,
            "instagram_url": None,
            "other_channels": [],
        })
    return results


def fetch(domain: str) -> list[dict]:
    api_key = os.getenv("APOLLO_API_KEY")
    if not api_key:
        logger.warning("APOLLO_API_KEY not set; skipping Apollo")
        return []
    return search_people(domain, api_key)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Apollo.io DM fetcher")
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()
    print(json.dumps(fetch(args.domain), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
