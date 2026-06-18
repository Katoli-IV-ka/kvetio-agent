"""Contact enricher: email guesser and social/website discovery.

CLI:
    python scripts/contact_enricher.py --domain radai.com
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from contacts_store import list_contacts, upsert_contact
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)

GH_API = "https://api.github.com"
HF_API = "https://huggingface.co/api"
TWITTER_RE = re.compile(r"@([A-Za-z0-9_]{1,15})")

# ── Step 1: Email Pattern Guesser ─────────────────────────────────────────


def _infer_pattern(contacts_with_email: list[dict]) -> str | None:
    """Infer the most common email pattern from contacts that already have emails."""
    patterns: list[str] = []
    for c in contacts_with_email:
        email = (c.get("email") or "").lower()
        first = (c.get("first_name") or "").lower().strip()
        last = (c.get("last_name") or "").lower().strip()
        if not email or not first or not last:
            continue
        local = email.split("@")[0]
        if local == f"{first}.{last}":
            patterns.append("first.last")
        elif local == first:
            patterns.append("first")
        elif local == f"{first[0]}{last}":
            patterns.append("flast")
        elif local == f"{first}{last}":
            patterns.append("firstlast")
    if not patterns:
        return None
    return Counter(patterns).most_common(1)[0][0]


def _apply_pattern(pattern: str, first: str, last: str, domain: str) -> str:
    """Build an email address from a pattern and name components."""
    f = first.lower().strip()
    ln = last.lower().strip()
    local_map = {
        "first.last": f"{f}.{ln}",
        "first": f,
        "flast": f"{f[0]}{ln}",
        "firstlast": f"{f}{ln}",
    }
    local = local_map.get(pattern, f"{f}.{ln}")
    return f"{local}@{domain}"


def guess_emails(domain: str, contacts: list[dict]) -> list[dict]:
    """Return contacts with guessed emails (only those that were missing an email)."""
    with_email = [c for c in contacts if c.get("email")]
    without_email = [
        c for c in contacts
        if not c.get("email") and c.get("first_name") and c.get("last_name")
    ]

    pattern = _infer_pattern(with_email)
    chosen_pattern = pattern or "first.last"

    updated: list[dict] = []
    for contact in without_email:
        guessed = _apply_pattern(
            chosen_pattern,
            contact["first_name"],
            contact["last_name"],
            domain,
        )
        updated.append({
            **contact,
            "email": guessed,
        })
    return updated


# ── Step 2: Social/Website Discovery ──────────────────────────────────────


def _channel_username(contact: dict, type_: str, legacy_key: str) -> str | None:
    legacy = contact.get(legacy_key)
    if legacy:
        return str(legacy).strip()
    for item in contact.get("other_channels") or []:
        if not isinstance(item, dict) or item.get("type") != type_:
            continue
        url = str(item.get("url") or "").strip()
        if not url:
            continue
        return urlparse(url).path.strip("/").split("/")[0]
    return None


def _has_channel(contact: dict, type_: str) -> bool:
    return any(
        isinstance(item, dict) and item.get("type") == type_ and item.get("url")
        for item in contact.get("other_channels") or []
    )


def _with_channel(contact: dict, type_: str, url: str) -> dict:
    channels = [
        item for item in contact.get("other_channels") or []
        if isinstance(item, dict)
    ]
    if not any(item.get("type") == type_ and item.get("url") == url for item in channels):
        channels.append({"type": type_, "url": url})
    return {**contact, "other_channels": channels}


def enrich_from_github(contacts: list[dict]) -> list[dict]:
    """Fill x_url and personal website channel from GitHub profile API."""
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    updated: list[dict] = []
    for contact in contacts:
        username = _channel_username(contact, "github", "github_username")
        if not username:
            continue
        if contact.get("x_url") and _has_channel(contact, "personal_website"):
            continue
        try:
            resp = httpx.get(f"{GH_API}/users/{username}", headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug("GitHub profile fetch failed for %s: %s", username, exc)
            continue
        patch: dict = {}
        if not contact.get("x_url") and data.get("twitter_username"):
            patch["x_url"] = f"https://x.com/{data['twitter_username'].lstrip('@')}"
        enriched = {**contact, **patch}
        if data.get("blog") and not _has_channel(enriched, "personal_website"):
            enriched = _with_channel(enriched, "personal_website", data["blog"])
        if enriched != contact:
            updated.append(enriched)
    return updated


def enrich_from_huggingface(contacts: list[dict]) -> list[dict]:
    """Fill x_url and personal website channel by parsing HuggingFace bio."""
    updated: list[dict] = []
    for contact in contacts:
        username = _channel_username(contact, "huggingface", "hf_username")
        if not username:
            continue
        if contact.get("x_url") and _has_channel(contact, "personal_website"):
            continue
        try:
            resp = httpx.get(f"{HF_API}/users/{username}/overview", timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug("HF overview fetch failed for %s: %s", username, exc)
            continue
        bio = (data.get("user") or {}).get("details") or ""
        patch: dict = {}
        if not contact.get("x_url"):
            m = TWITTER_RE.search(bio)
            if m:
                patch["x_url"] = f"https://x.com/{m.group(1)}"
        enriched = {**contact, **patch}
        if not _has_channel(enriched, "personal_website"):
            m = re.search(r"https?://\S+", bio)
            if m:
                enriched = _with_channel(enriched, "personal_website", m.group(0))
        if enriched != contact:
            updated.append(enriched)
    return updated


# ── Orchestrator ───────────────────────────────────────────────────────────


def run(domain: str, skip_hunter: bool = False) -> None:
    """Run all enrichment steps for a domain in sequence."""
    if skip_hunter:
        logger.debug("skip_hunter is deprecated; Hunter verification is not in the default flow")
    store = SupabaseStore()

    # Step 1: guess missing emails
    contacts = list_contacts(store, domain)
    if not contacts:
        logger.info("No contacts for %s, skipping enrichment", domain)
        return

    guessed = guess_emails(domain, contacts)
    for contact in guessed:
        upsert_contact(store, {**contact, "company_domain": domain})

    # Step 2: social/website discovery from GitHub
    contacts = list_contacts(store, domain)
    for contact in enrich_from_github(contacts):
        upsert_contact(store, {**contact, "company_domain": domain})

    # Step 3: social/website discovery from HuggingFace
    contacts = list_contacts(store, domain)
    for contact in enrich_from_huggingface(contacts):
        upsert_contact(store, {**contact, "company_domain": domain})

    logger.info("Enrichment complete for %s", domain)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Contact enricher")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--skip-hunter", action="store_true")
    args = parser.parse_args()
    run(args.domain, skip_hunter=args.skip_hunter)


if __name__ == "__main__":
    main()
