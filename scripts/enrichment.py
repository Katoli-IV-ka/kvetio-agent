"""Этап 3 (Enrichment): резолверы ссылок-источников → source_links.

Детерминированные HTTP-резолверы. MCP/WebSearch-ручки (HF org, новости, соцсети)
собирает EnrichmentAgent в промпте и пишет через dossier_store.

CLI:
    python scripts/enrichment.py --domain radai.com
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).parent))
from dossier_store import upsert_source_link
from http_client import HttpClient
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
    """Прогнать включённые резолверы, записать найденные ссылки в source_links."""
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
            upsert_source_link(store, link)
            written.append(link)
    return written


# Реестр заполняется в Task 2 реальными резолверами; пока — только стабы.
RESOLVERS: list[Resolver] = [LINKEDIN_STUB, CRUNCHBASE_STUB, SIMILARWEB_STUB]


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
