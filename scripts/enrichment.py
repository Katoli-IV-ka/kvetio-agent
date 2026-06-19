"""Этап 3 (Enrichment): резолверы ссылок-источников -> research_records.

Детерминированные HTTP-резолверы. MCP/WebSearch-ручки (HF org, новости, соцсети)
собирает EnrichmentAgent в промпте и пишет как source research records.

CLI:
    python scripts/enrichment.py --domain radai.com
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).parent))
from dm_github import extract_org_login
from http_client import HttpClient
from models import ResearchRecord
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)


class Resolver(Protocol):
    kind: str
    enabled: bool

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> dict | None:
        ...


class _DisabledStub:
    """Стаб платного источника. Реализовать resolve() и enabled=True при подключении."""

    enabled = False

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> dict | None:
        return None


class GithubOrgResolver:
    """Ссылка на GitHub-организацию из уже собранных сигналов компании."""

    kind = "github_org"
    enabled = True

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> dict | None:
        for sig in store.get_research_records_for_company(company["domain"]):
            url = sig.get("url") or ""
            login = extract_org_login(url)
            if login:
                return {
                    "company_id": company["id"],
                    "kind": self.kind,
                    "url": f"https://github.com/{login}",
                    "source": "github_org_resolver",
                    "confidence": "high",
                }
        return None


WAYBACK_API = "http://archive.org/wayback/available"


class WaybackResolver:
    """Ближайший снапшот сайта в Wayback Machine — для динамики позиционирования."""

    kind = "wayback"
    enabled = True

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> dict | None:
        data = client.get_json(f"{WAYBACK_API}?url={company['domain']}")
        closest = (data.get("archived_snapshots") or {}).get("closest") or {}
        url = closest.get("url")
        if not url:
            return None
        return {
            "company_id": company["id"],
            "kind": self.kind,
            "url": url,
            "source": "wayback_resolver",
            "confidence": "high",
        }


# Стабы платных источников (tier C). Зарегистрированы, но выключены.
LINKEDIN_STUB = _DisabledStub("linkedin")
CRUNCHBASE_STUB = _DisabledStub("crunchbase")
SIMILARWEB_STUB = _DisabledStub("similarweb")


def run_enrichment(
    company: dict,
    store: SupabaseStore,
    client: HttpClient,
    resolvers: list[Resolver] | None = None,
) -> list[dict]:
    """Run enabled resolvers and write found source URLs as research_records."""
    active = resolvers if resolvers is not None else RESOLVERS
    written: list[dict] = []
    for r in active:
        if not getattr(r, "enabled", False):
            continue
        try:
            link = r.resolve(company, store, client)
        except Exception as exc:  # noqa: BLE001 — резолвер не должен ронять этап
            logger.warning("resolver %s failed: %s", getattr(r, "kind", "?"), exc)
            continue
        if link:
            payload = {
                k: v for k, v in link.items()
                if k not in {"company_id", "source", "url", "confidence"}
            }
            payload.setdefault("fetched_at", datetime.utcnow().isoformat())
            entry = ResearchRecord(
                source=link.get("source", "unknown"),
                record_type="source_link",
                company_name=company.get("name") or company["domain"],
                domain=company.get("domain"),
                linkedin_url=company.get("linkedin_url"),
                url=link["url"],
                observed_at=date.today(),
                confidence=link.get("confidence", "medium"),
                record_role="source",
                agent="enrichment",
                title=link.get("kind"),
                payload=payload,
            )
            store.upsert_research_record(entry, domain=company["domain"])
            written.append(link)
    return written


RESOLVERS: list[Resolver] = [
    GithubOrgResolver(),
    WaybackResolver(),
    LINKEDIN_STUB,
    CRUNCHBASE_STUB,
    SIMILARWEB_STUB,
]


def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    store = SupabaseStore()
    company = store.get_company(args.domain)
    if not company:
        print(json.dumps({"error": "company not found", "domain": args.domain}))
        return
    with HttpClient(rate_limit_rps=1.0) as client:
        written = run_enrichment(company, store, client)
    print(json.dumps({"domain": args.domain, "written": written}, indent=2))


if __name__ == "__main__":
    _main()
