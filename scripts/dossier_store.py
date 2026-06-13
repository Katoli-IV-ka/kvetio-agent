"""CRUD для сущностей глубокого досье: source_links, analysis_notes, dossiers.

Образец — contacts_store.py: dict-CRUD поверх SupabaseStore._client.

CLI:
    echo '{"company_domain":"radai.com","kind":"github_org","url":"https://github.com/radai"}' \
        | python scripts/dossier_store.py --upsert-source-link
    python scripts/dossier_store.py --list-source-links radai.com
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)


def upsert_source_link(store: SupabaseStore, link: dict) -> None:
    """Upsert одной ссылки-источника. Conflict key: (company_domain, kind, url)."""
    row = {
        "company_domain": link["company_domain"],
        "kind": link["kind"],
        "url": link["url"],
        "source": link.get("source", "unknown"),
        "confidence": link.get("confidence", "medium"),
        "found_via": link.get("found_via"),
        "raw": link.get("raw", {}),
        "fetched_at": datetime.utcnow().isoformat(),
    }
    store._client.table("source_links").upsert(
        row, on_conflict="company_domain,kind,url"
    ).execute()
    logger.debug("upsert_source_link: %s / %s", row["company_domain"], row["kind"])


def get_source_links(store: SupabaseStore, domain: str) -> list[dict]:
    """Все ссылки-источники компании, свежие сверху."""
    res = (
        store._client.table("source_links")
        .select("*")
        .eq("company_domain", domain)
        .order("fetched_at", desc=True)
        .execute()
    )
    return res.data or []


def upsert_analysis_note(store: SupabaseStore, note: dict) -> None:
    """Upsert факта-секции этапа 4. Conflict key: (company_domain, section, version)."""
    row = {
        "company_domain": note["company_domain"],
        "section": note["section"],
        "facts": note.get("facts", {}),
        "sources": note.get("sources", []),
        "confidence": note.get("confidence", "medium"),
        "model": note.get("model"),
        "version": note.get("version", "v1"),
        "created_at": datetime.utcnow().isoformat(),
    }
    store._client.table("analysis_notes").upsert(
        row, on_conflict="company_domain,section,version"
    ).execute()
    logger.debug("upsert_analysis_note: %s / %s", row["company_domain"], row["section"])


def get_analysis_notes(store: SupabaseStore, domain: str) -> list[dict]:
    """Все факты-секции компании."""
    res = (
        store._client.table("analysis_notes")
        .select("*")
        .eq("company_domain", domain)
        .execute()
    )
    return res.data or []


def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--upsert-source-link", action="store_true")
    parser.add_argument("--list-source-links", metavar="DOMAIN")
    args = parser.parse_args()

    store = SupabaseStore()
    if args.upsert_source_link:
        upsert_source_link(store, json.load(sys.stdin))
    elif args.list_source_links:
        print(json.dumps(get_source_links(store, args.list_source_links), indent=2))


if __name__ == "__main__":
    _main()
