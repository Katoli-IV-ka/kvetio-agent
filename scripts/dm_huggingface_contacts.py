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


def _split_name(name: str) -> tuple[str, str]:
    parts = (name or "").strip().split(maxsplit=1)
    return (parts[0], parts[1] if len(parts) > 1 else "") if parts else ("", "")


def get_hf_org_for_domain(domain: str, store: SupabaseStore) -> str | None:
    """Find HF org from company signals."""
    signals = store.get_signals_for_company(domain)
    for sig in signals:
        url = sig.get("url") or ""
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
            first_name, last_name = _split_name(
                overview.get("fullname") or member.get("fullname") or username
            )
            results.append({
                "first_name": first_name,
                "last_name": last_name,
                "info": overview.get("details"),
                "email": None,
                "phone": None,
                "linkedin_url": None,
                "x_url": None,
                "facebook_url": None,
                "instagram_url": None,
                "other_channels": [
                    {"type": "huggingface", "url": f"https://huggingface.co/{username}"},
                ],
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
