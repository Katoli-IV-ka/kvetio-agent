"""CRUD для сущностей глубокого досье: source_links, analysis_notes, dossiers.

Все таблицы ключуются по company_id (UUID), а не по company_domain.
Для получения company_id используйте store.resolve_company_id(domain=...).

CLI:
    echo '{"company_id":"<uuid>","kind":"github_org","url":"https://github.com/acme"}' \
        | python scripts/dossier_store.py --upsert-source-link
    python scripts/dossier_store.py --list-source-links <company_id>
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from models import confidence_to_score
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)


def upsert_source_link(store: SupabaseStore, link: dict) -> None:
    """Upsert одной ссылки-источника. Conflict key: (company_id, kind, url)."""
    row = {
        "company_id": link["company_id"],
        "kind": link["kind"],
        "url": link["url"],
        "source": link.get("source", "unknown"),
        "confidence": confidence_to_score(link.get("confidence", "medium")),
        "found_via": link.get("found_via"),
        "source_signal_id": link.get("source_signal_id"),
        "raw": link.get("raw", {}),
        "fetched_at": datetime.utcnow().isoformat(),
    }
    store._client.table("source_links").upsert(
        row, on_conflict="company_id,kind,url"
    ).execute()
    logger.debug("upsert_source_link: %s / %s", row["company_id"], row["kind"])


def get_source_links(store: SupabaseStore, company_id: str) -> list[dict]:
    """Все ссылки-источники компании, свежие сверху."""
    res = (
        store._client.table("source_links")
        .select("*")
        .eq("company_id", company_id)
        .order("fetched_at", desc=True)
        .execute()
    )
    return res.data or []


def upsert_analysis_note(store: SupabaseStore, note: dict) -> str | None:
    """Upsert факта-секции этапа 4. Conflict key: (company_id, section, version).

    Returns the note id (for linking to signals via link_note_to_signals).
    """
    row = {
        "company_id": note["company_id"],
        "section": note["section"],
        "facts": note.get("facts", {}),
        "confidence": confidence_to_score(note.get("confidence", "medium")),
        "model": note.get("model"),
        "version": note.get("version", "v1"),
        "created_at": datetime.utcnow().isoformat(),
    }
    res = store._client.table("analysis_notes").upsert(
        row, on_conflict="company_id,section,version"
    ).execute()
    logger.debug("upsert_analysis_note: %s / %s", row["company_id"], row["section"])
    rows = res.data or [{}]
    return rows[0].get("id") if rows else None


def link_note_to_signals(
    store: SupabaseStore,
    note_id: str,
    signal_ids: list[str],
    role: str = "supports",
) -> None:
    """Link an analysis_note to one or more signals via the junction table.

    Args:
        role: 'supports' | 'contradicts' | 'context'
    """
    if not signal_ids:
        return
    rows = [
        {"analysis_note_id": note_id, "signal_id": sid, "role": role}
        for sid in signal_ids
    ]
    store._client.table("analysis_note_signals").upsert(
        rows, on_conflict="analysis_note_id,signal_id"
    ).execute()
    logger.debug("link_note_to_signals: note=%s signals=%s", note_id, signal_ids)


def get_analysis_notes(store: SupabaseStore, company_id: str) -> list[dict]:
    """Все факты-секции компании."""
    res = (
        store._client.table("analysis_notes")
        .select("*")
        .eq("company_id", company_id)
        .execute()
    )
    return res.data or []


def upsert_dossier(store: SupabaseStore, dossier: dict) -> None:
    """Upsert финального досье. Conflict key: company_id (одно на компанию)."""
    row = {
        "company_id": dossier["company_id"],
        "summary_md": dossier.get("summary_md"),
        "sections": dossier.get("sections", {}),
        "audit_md": dossier.get("audit_md"),
        "table_fields": dossier.get("table_fields", {}),
        "version": dossier.get("version", "v1"),
        "generated_at": datetime.utcnow().isoformat(),
    }
    store._client.table("dossiers").upsert(
        row, on_conflict="company_id"
    ).execute()
    logger.debug("upsert_dossier: %s", row["company_id"])


def get_dossier(store: SupabaseStore, company_id: str) -> dict | None:
    """Досье компании или None."""
    res = (
        store._client.table("dossiers")
        .select("*")
        .eq("company_id", company_id)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upsert-source-link", action="store_true")
    parser.add_argument("--list-source-links", metavar="COMPANY_ID")
    parser.add_argument("--upsert-analysis-note", action="store_true")
    parser.add_argument("--list-analysis-notes", metavar="COMPANY_ID")
    parser.add_argument("--upsert-dossier", action="store_true")
    parser.add_argument("--get-dossier", metavar="COMPANY_ID")
    return parser


def _run(args: argparse.Namespace, store: SupabaseStore) -> None:
    if args.upsert_source_link:
        upsert_source_link(store, json.load(sys.stdin))
    elif args.list_source_links:
        print(json.dumps(get_source_links(store, args.list_source_links), indent=2))
    elif args.upsert_analysis_note:
        upsert_analysis_note(store, json.load(sys.stdin))
    elif args.list_analysis_notes:
        print(json.dumps(get_analysis_notes(store, args.list_analysis_notes), indent=2))
    elif args.upsert_dossier:
        upsert_dossier(store, json.load(sys.stdin))
    elif args.get_dossier:
        print(json.dumps(get_dossier(store, args.get_dossier), indent=2))


def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    _run(_build_parser().parse_args(), SupabaseStore())


if __name__ == "__main__":
    _main()
