"""GitHub Code Search source adapter.

Finds organizations with recent Python training scripts for ICP keywords,
fetches organization metadata through a Supabase-backed TTL cache, and yields
RawSignal objects compatible with the other Kvetio source adapters.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from http_client import HttpClient
from models import ICPQuery, RawSignal
from normalize import normalize_domain
from org_cache import OrgCache

logger = logging.getLogger(__name__)

SEARCH_API = "https://api.github.com/search/code"
ORGS_API = "https://api.github.com"
ACTIVE_WITHIN_DAYS = 90

_REPO_ROOT = Path(__file__).parent.parent


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _parse_github_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


class GitHubAdapter:
    name = "github"
    tier = "A"

    def __init__(
        self,
        *,
        org_cache: OrgCache | None = None,
        parser_version: str = "2026-05",
        rate_limit_rps: float = 0.5,
        github_token: str | None = None,
        active_within_days: int = ACTIVE_WITHIN_DAYS,
    ) -> None:
        self.parser_version = parser_version
        self._cache = org_cache if org_cache is not None else OrgCache()
        self._active_within_days = active_within_days

        token = github_token if github_token is not None else os.environ.get("GITHUB_TOKEN", "")
        extra_headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            extra_headers["Authorization"] = f"Bearer {token}"

        self._http = HttpClient(rate_limit_rps=rate_limit_rps, extra_headers=extra_headers)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "GitHubAdapter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def fetch(self, query: ICPQuery) -> Iterator[RawSignal]:
        cutoff = _utcnow() - timedelta(days=self._active_within_days)
        org_activity: dict[str, datetime] = {}

        for keyword in query.keywords_strong:
            try:
                keyword_activity = self._search_code(keyword)
            except Exception as exc:  # noqa: BLE001
                logger.warning("github: code search for %r failed: %s", keyword, exc)
                continue

            for org_login, last_pushed in keyword_activity.items():
                previous = org_activity.get(org_login)
                if previous is None or last_pushed > previous:
                    org_activity[org_login] = last_pushed

        for org_login, last_pushed in org_activity.items():
            if last_pushed < cutoff:
                logger.debug(
                    "github: org %s inactive (last push %s), skipping",
                    org_login,
                    last_pushed.date(),
                )
                continue

            try:
                signal = self._build_signal(org_login, last_pushed)
            except Exception as exc:  # noqa: BLE001
                logger.warning("github: org %s failed: %s", org_login, exc)
                continue

            if signal is not None:
                yield signal

    def _search_code(self, keyword: str) -> dict[str, datetime]:
        """Return org login -> most recent pushed_at for matching org-owned repos."""
        payload = self._http.get_json(
            SEARCH_API,
            params={
                "q": f'filename:train.py "{keyword}" language:Python',
                "per_page": 30,
            },
        )
        if not isinstance(payload, dict):
            return {}

        org_activity: dict[str, datetime] = {}
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            repo = item.get("repository") or {}
            owner = repo.get("owner") or {}
            if owner.get("type") != "Organization":
                continue

            org_login = (owner.get("login") or "").strip()
            pushed_at = _parse_github_datetime((repo.get("pushed_at") or "").strip())
            if not org_login or pushed_at is None:
                continue

            previous = org_activity.get(org_login)
            if previous is None or pushed_at > previous:
                org_activity[org_login] = pushed_at

        return org_activity

    def _build_signal(self, org_login: str, last_pushed: datetime) -> RawSignal | None:
        org_data = self._cache.get(org_login)
        if org_data is None:
            raw = self._http.get_json(f"{ORGS_API}/orgs/{org_login}")
            if not isinstance(raw, dict) or not raw:
                logger.debug("github: org %s returned empty metadata", org_login)
                return None
            self._cache.set(org_login, raw)
            org_data = raw

        company_name = (org_data.get("name") or org_login).strip()
        domain = self._extract_domain(org_data, org_login)

        return RawSignal(
            source=self.name,
            signal_type="github_repo",
            company_name=company_name,
            domain=domain,
            linkedin_url=None,
            evidence_url=f"https://github.com/{org_login}",
            signal_date=last_pushed.date(),
            confidence="medium",
            raw_payload={
                "org_login": org_login,
                "repo_count": org_data.get("public_repos"),
                "followers": org_data.get("followers"),
                "description": (org_data.get("description") or "")[:200],
                "last_pushed_at": last_pushed.isoformat(),
            },
            parser_version=self.parser_version,
        )

    def _extract_domain(self, org_data: dict, org_login: str) -> str | None:
        blog = (org_data.get("blog") or "").strip()
        if blog:
            try:
                return normalize_domain(blog)
            except ValueError:
                logger.debug("github: invalid blog domain for %s: %r", org_login, blog)

        email = (org_data.get("email") or "").strip()
        if email and "@" in email:
            try:
                return normalize_domain(email.split("@", 1)[1])
            except ValueError:
                logger.debug("github: invalid email domain for %s: %r", org_login, email)

        return self._llm_domain(org_data, org_login)

    def _llm_domain(self, org_data: dict, org_login: str) -> str | None:
        """Best-effort domain inference. Returns None on missing dependency/API/key."""
        try:
            import anthropic  # noqa: PLC0415

            prompt = (
                "GitHub organization:\n"
                f"Login: {org_login}\n"
                f"Name: {org_data.get('name', '')}\n"
                f"Description: {org_data.get('description', '')}\n\n"
                "What is this company's website domain? Reply with only the domain "
                "(for example acme.ai), or unknown if unsure."
            )
            client = anthropic.Anthropic()
            message = client.messages.create(
                model=os.environ.get("ANTHROPIC_MODEL", "claude-3-5-haiku-latest"),
                max_tokens=32,
                messages=[{"role": "user", "content": prompt}],
            )
            text = ""
            if message.content:
                text = (getattr(message.content[0], "text", "") or "").strip().lower()
            if not text or text == "unknown":
                return None
            return normalize_domain(text)
        except Exception as exc:  # noqa: BLE001
            logger.debug("github: LLM domain extraction for %s failed: %s", org_login, exc)
            return None


def _load_icp_query(segment: str) -> ICPQuery:
    raw = yaml.safe_load((_REPO_ROOT / "config" / "icp.yaml").read_text(encoding="utf-8"))
    for segment_config in raw.get("segments", []):
        if segment_config["name"] == segment:
            return ICPQuery(
                segment=segment_config["name"],
                keywords_strong=tuple(segment_config.get("keywords_strong", [])),
                keywords_weak=tuple(segment_config.get("keywords_weak", [])),
                industries=tuple(segment_config.get("industries", [])),
            )
    raise ValueError(f"Сегмент '{segment}' не найден в config/icp.yaml")


def _signal_to_dict(signal: RawSignal) -> dict:
    return {
        "source": signal.source,
        "signal_type": signal.signal_type,
        "company_name": signal.company_name,
        "domain": signal.domain,
        "linkedin_url": signal.linkedin_url,
        "evidence_url": signal.evidence_url,
        "signal_date": signal.signal_date.isoformat(),
        "confidence": signal.confidence,
        "raw_payload": signal.raw_payload,
        "parser_version": signal.parser_version,
        "source_page_url": signal.evidence_url,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="GitHub Code Search source adapter")
    parser.add_argument("--segment", required=True, help="ICP-сегмент из config/icp.yaml")
    parser.add_argument("--limit", type=int, default=50, help="Максимум сигналов на выходе")
    parser.add_argument("--active-within-days", type=int, default=ACTIVE_WITHIN_DAYS)
    parser.add_argument("--log-level", default=os.environ.get("KVETIO_LOG_LEVEL", "WARNING"))
    parser.add_argument("--dry-run", action="store_true", help="Совместимость с другими источниками")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    query = _load_icp_query(args.segment)
    results: list[dict] = []

    with GitHubAdapter(active_within_days=args.active_within_days) as adapter:
        for signal in adapter.fetch(query):
            results.append(_signal_to_dict(signal))
            if len(results) >= args.limit:
                break

    print(json.dumps(results, ensure_ascii=False, indent=2))
    logger.info("github: найдено сигналов: %d", len(results))
    if args.dry_run:
        logger.info("github: dry-run, запись в Supabase не выполняется этим скриптом")


if __name__ == "__main__":
    main()
