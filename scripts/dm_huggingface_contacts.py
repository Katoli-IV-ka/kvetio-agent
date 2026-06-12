"""HuggingFace org member fetcher for bio-based contact extraction.

CLI:
    python scripts/dm_huggingface_contacts.py --domain radai.com

Reads HF org name from Supabase signals and writes JSON to stdout.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
from http_client import HttpClient
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)

HF_API = "https://huggingface.co/api"
_HF_SYSTEM_PATHS = {"models", "datasets", "spaces", "api", "docs", ""}


def get_hf_org_for_domain(domain: str, store: SupabaseStore) -> str | None:
    """Find HF org from company signals."""
    signals = store.get_signals_for_company(domain)
    for sig in signals:
        url = sig.get("source_page_url") or sig.get("evidence_url") or ""
        parsed = urlparse(url)
        if "huggingface.co" not in (parsed.netloc or ""):
            continue
        parts = [part for part in parsed.path.strip("/").split("/") if part]
        org = parts[0] if parts else ""
        if org and org not in _HF_SYSTEM_PATHS:
            return org
    return None


def fetch_members(org: str, client: HttpClient) -> list[dict]:
    """GET /api/organizations/{org}/members."""
    data = client.get_json(f"{HF_API}/organizations/{org}/members")
    return data if isinstance(data, list) else []


def fetch_user_overview(username: str, client: HttpClient) -> dict | None:
    """GET /api/users/{username}/overview."""
    data = client.get_json(f"{HF_API}/users/{username}/overview")
    if not isinstance(data, dict) or "user" not in data:
        return None
    return data


def fetch(domain: str) -> list[dict]:
    store = SupabaseStore()
    org = get_hf_org_for_domain(domain, store)
    if not org:
        logger.info("No HF org found for %s", domain)
        return []

    with HttpClient(rate_limit_rps=3.0) as client:
        members = fetch_members(org, client)
        results: list[dict] = []
        for member in members[:50]:
            username = member.get("user", "")
            if not username:
                continue
            overview = fetch_user_overview(username, client)
            if not overview:
                continue
            results.append({
                "hf_username": username,
                "full_name": overview.get("fullname") or member.get("fullname") or username,
                "bio": overview.get("details"),
                "source_url": f"https://huggingface.co/{username}",
            })
    return results


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="HuggingFace contacts fetcher")
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()
    print(json.dumps(fetch(args.domain), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
