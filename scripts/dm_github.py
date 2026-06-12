"""GitHub DM fetcher: org members plus commit email extraction.

CLI:
    python scripts/dm_github.py --domain radai.com

Reads GitHub org login from Supabase signals and writes JSON to stdout.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
from http_client import HttpClient
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)

GH_API = "https://api.github.com"
NOREPLY_RE = re.compile(r"(^|@|\+)noreply|@users\.noreply\.github\.com$", re.IGNORECASE)


def extract_org_login(source_page_url: str) -> str | None:
    """Return org login from a github.com URL."""
    if not source_page_url:
        return None
    parsed = urlparse(source_page_url)
    if "github.com" not in (parsed.netloc or ""):
        return None
    parts = [p for p in parsed.path.strip("/").split("/") if p]
    return parts[0] if parts else None


def is_real_email(email: str | None) -> bool:
    """True when email is not a GitHub privacy/noreply address."""
    if not email:
        return False
    return not NOREPLY_RE.search(email)


def get_github_org_for_domain(domain: str, store: SupabaseStore) -> str | None:
    """Find GitHub org login from stored company signals."""
    signals = store.get_signals_for_company(domain)
    for sig in signals:
        url = sig.get("source_page_url") or sig.get("evidence_url") or ""
        login = extract_org_login(url)
        if login:
            return login
    return None


def fetch_org_members(org: str, client: HttpClient) -> list[dict]:
    """GET /orgs/{org}/members."""
    data = client.get_json(f"{GH_API}/orgs/{org}/members", params={"per_page": 100})
    return data if isinstance(data, list) else []


def fetch_user_profile(login: str, client: HttpClient) -> dict | None:
    """GET /users/{login} and map useful profile fields."""
    data = client.get_json(f"{GH_API}/users/{login}")
    if not isinstance(data, dict) or "login" not in data:
        return None
    return {
        "source": "github_profile",
        "github_username": login,
        "full_name": data.get("name") or login,
        "email": data.get("email"),
        "bio": data.get("bio"),
        "twitter_handle": data.get("twitter_username"),
        "blog": data.get("blog"),
        "company": data.get("company"),
    }


def fetch_commit_authors(org: str, client: HttpClient, max_repos: int = 3) -> list[dict]:
    """Extract real author emails from commits in top repositories."""
    repos = client.get_json(
        f"{GH_API}/orgs/{org}/repos",
        params={"per_page": 30, "sort": "pushed"},
    )
    if not isinstance(repos, list):
        return []

    top_repos = sorted(
        repos,
        key=lambda repo: repo.get("stargazers_count", 0),
        reverse=True,
    )[:max_repos]

    seen_emails: set[str] = set()
    results: list[dict] = []

    for repo in top_repos:
        repo_name = repo.get("name")
        if not repo_name:
            continue
        commits = client.get_json(
            f"{GH_API}/repos/{org}/{repo_name}/commits",
            params={"per_page": 100},
        )
        if not isinstance(commits, list):
            continue
        for commit in commits:
            author_data = commit.get("commit", {}).get("author", {})
            name = author_data.get("name", "")
            email = author_data.get("email", "")
            login = (commit.get("author") or {}).get("login") or None

            if not is_real_email(email) or email in seen_emails:
                continue
            seen_emails.add(email)

            results.append({
                "source": "github_commit",
                "github_username": login,
                "full_name": name,
                "email": email,
                "bio": None,
                "twitter_handle": None,
                "blog": None,
                "company": org,
            })

    return results


def fetch(domain: str) -> list[dict]:
    """Return GitHub contacts for a company domain."""
    store = SupabaseStore()
    org = get_github_org_for_domain(domain, store)
    if not org:
        logger.info("No GitHub org found for %s", domain)
        return []

    token = os.getenv("GITHUB_TOKEN")
    headers = {"Authorization": f"Bearer {token}"} if token else None
    rps = 5.0 if token else 0.5

    with HttpClient(rate_limit_rps=rps, extra_headers=headers) as client:
        members = fetch_org_members(org, client)
        profiles: list[dict] = []
        for member in members:
            login = member.get("login", "")
            if not login:
                continue
            profile = fetch_user_profile(login, client)
            if profile:
                profiles.append(profile)
        commit_authors = fetch_commit_authors(org, client)

    return profiles + commit_authors


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="GitHub DM fetcher")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    results = fetch(args.domain)
    if args.dry_run:
        print(f"Found {len(results)} contacts (dry-run, not saved)", file=sys.stderr)
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
