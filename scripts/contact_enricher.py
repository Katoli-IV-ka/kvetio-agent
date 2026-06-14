"""Contact enricher: email guesser, Hunter.io verify, social/website discovery.

CLI:
    python scripts/contact_enricher.py --domain radai.com
    python scripts/contact_enricher.py --domain radai.com --skip-hunter
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from contacts_store import list_contacts, upsert_contact
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)

HUNTER_API = "https://api.hunter.io/v2"
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
    l = last.lower().strip()
    local_map = {
        "first.last": f"{f}.{l}",
        "first": f,
        "flast": f"{f[0]}{l}",
        "firstlast": f"{f}{l}",
    }
    local = local_map.get(pattern, f"{f}.{l}")
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
            "email_status": "guessed",
            "email_source": "pattern_guesser",
            "confidence": "low",
        })
    return updated


# ── Step 2: Hunter.io Verify ───────────────────────────────────────────────


def verify_with_hunter(email: str, api_key: str) -> str:
    """Call Hunter.io Email Verifier. Returns: valid | invalid | accept_all | unknown."""
    try:
        resp = httpx.get(
            f"{HUNTER_API}/email-verifier",
            params={"email": email, "api_key": api_key},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("data", {}).get("result", "unknown")
    except Exception as exc:
        logger.warning("Hunter.io verify failed for %s: %s", email, exc)
        return "unknown"


def run_hunter_verify(contacts: list[dict], api_key: str) -> list[dict]:
    """Verify guessed emails via Hunter.io. Returns only contacts that were updated."""
    updated: list[dict] = []
    for contact in contacts:
        if contact.get("email_status") != "guessed":
            continue
        status = verify_with_hunter(contact["email"], api_key)
        patch: dict = {"email_status": status, "email_source": "hunter_verify"}
        if status == "invalid":
            patch["email"] = None
        updated.append({**contact, **patch})
    return updated


# ── Step 3: Social/Website Discovery ──────────────────────────────────────


def enrich_from_github(contacts: list[dict]) -> list[dict]:
    """Fill twitter_handle and personal_website from GitHub profile API."""
    token = os.getenv("GITHUB_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    updated: list[dict] = []
    for contact in contacts:
        username = contact.get("github_username")
        if not username:
            continue
        if contact.get("twitter_handle") and contact.get("personal_website"):
            continue
        try:
            resp = httpx.get(f"{GH_API}/users/{username}", headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.debug("GitHub profile fetch failed for %s: %s", username, exc)
            continue
        patch: dict = {}
        if not contact.get("twitter_handle") and data.get("twitter_username"):
            patch["twitter_handle"] = data["twitter_username"]
        if not contact.get("personal_website") and data.get("blog"):
            patch["personal_website"] = data["blog"]
        if patch:
            updated.append({**contact, **patch})
    return updated


def enrich_from_huggingface(contacts: list[dict]) -> list[dict]:
    """Fill twitter_handle and personal_website by parsing HuggingFace bio."""
    updated: list[dict] = []
    for contact in contacts:
        username = contact.get("hf_username")
        if not username:
            continue
        if contact.get("twitter_handle") and contact.get("personal_website"):
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
        if not contact.get("twitter_handle"):
            m = TWITTER_RE.search(bio)
            if m:
                patch["twitter_handle"] = m.group(1)
        if not contact.get("personal_website"):
            m = re.search(r"https?://\S+", bio)
            if m:
                patch["personal_website"] = m.group(0)
        if patch:
            updated.append({**contact, **patch})
    return updated
