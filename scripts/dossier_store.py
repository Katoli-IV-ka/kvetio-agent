"""CRUD for research_records, analysis_records, analysis_links, dossiers, dossier_links.

All tables are keyed by company_id (UUID), not company_domain.
For company_id lookup, use store.resolve_company_id(domain=...).
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

DOSSIER_COLUMNS = (
    "company_id",
    "funding_stage",
    "funding_amount_usd",
    "funding_date",
    "product_category",
    "ai_use_case",
    "icp_fit",
    "last_news_date",
    "extra_facts",
    "section_summaries",
    "summary_md",
    "audit_md",
    # Sales-brief fields (029)
    "pain_summary",
    "outreach_hook",
    "pitch_angle",
    "why_interesting",
    "next_step",
    "entry_point_contact_id",
    "notion_page_id",
    "notion_synced_at",
    "derived_from_model",
    "version",
)


def upsert_analysis_record(store: SupabaseStore, record: dict) -> str | None:
    """Upsert one analysis section. Conflict key: (company_id, section, version)."""
    row = {
        "company_id": record["company_id"],
        "section": record["section"],
        "facts": record.get("facts", {}),
        "confidence": confidence_to_score(record.get("confidence", "medium")),
        "model": record.get("model"),
        "version": record.get("version", "v1"),
        "updated_at": datetime.utcnow().isoformat(),
    }
    res = store._client.table("analysis_records").upsert(
        row, on_conflict="company_id,section,version"
    ).execute()
    logger.debug("upsert_analysis_record: %s / %s", row["company_id"], row["section"])
    rows = res.data or [{}]
    return rows[0].get("id") if rows else None


def link_analysis_to_research(
    store: SupabaseStore,
    analysis_record_id: str,
    research_record_ids: list[str],
    role: str = "supports",
    note: str | None = None,
) -> None:
    """Link an analysis_record to one or more research_records."""
    if not research_record_ids:
        return
    rows = [
        {
            "analysis_record_id": analysis_record_id,
            "research_record_id": rid,
            "role": role,
            "note": note,
        }
        for rid in research_record_ids
    ]
    store._client.table("analysis_links").upsert(
        rows, on_conflict="analysis_record_id,research_record_id"
    ).execute()
    logger.debug(
        "link_analysis_to_research: analysis=%s research=%s",
        analysis_record_id,
        research_record_ids,
    )


def get_analysis_records(store: SupabaseStore, company_id: str) -> list[dict]:
    """All analysis records for a company."""
    res = (
        store._client.table("analysis_records")
        .select("*")
        .eq("company_id", company_id)
        .execute()
    )
    return res.data or []


def upsert_dossier(store: SupabaseStore, dossier: dict) -> None:
    """Upsert one finalized typed dossier. Conflict key: company_id."""
    row = {k: dossier[k] for k in DOSSIER_COLUMNS if k in dossier}
    row["company_id"] = dossier["company_id"]
    store._client.table("dossiers").upsert(
        row, on_conflict="company_id"
    ).execute()
    logger.debug("upsert_dossier: %s", row["company_id"])


def get_dossier(store: SupabaseStore, company_id: str) -> dict | None:
    """Return one company dossier or None."""
    res = (
        store._client.table("dossiers")
        .select("*")
        .eq("company_id", company_id)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else None


def link_dossier_to_analysis(
    store: SupabaseStore,
    company_id: str,
    analysis_record_ids: list[str],
    contributed_to_map: dict[str, str],
) -> None:
    """Link a dossier to the analysis_records that contributed to it."""
    if not analysis_record_ids:
        return
    rows = [
        {
            "company_id": company_id,
            "analysis_record_id": aid,
            "contributed_to": contributed_to_map.get(aid),
        }
        for aid in analysis_record_ids
    ]
    store._client.table("dossier_links").upsert(
        rows, on_conflict="company_id,analysis_record_id"
    ).execute()


def get_research_records(store: SupabaseStore, company_id: str) -> list[dict]:
    """Convenience wrapper for analysis-agent input."""
    return store.get_research_records_for_analysis(company_id)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--upsert-analysis-record", action="store_true")
    parser.add_argument("--list-analysis-records", metavar="COMPANY_ID")
    parser.add_argument("--upsert-dossier", action="store_true")
    parser.add_argument("--get-dossier", metavar="COMPANY_ID")
    return parser


def _run(args: argparse.Namespace, store: SupabaseStore) -> None:
    if args.upsert_analysis_record:
        upsert_analysis_record(store, json.load(sys.stdin))
    elif args.list_analysis_records:
        print(json.dumps(get_analysis_records(store, args.list_analysis_records), indent=2))
    elif args.upsert_dossier:
        upsert_dossier(store, json.load(sys.stdin))
    elif args.get_dossier:
        print(json.dumps(get_dossier(store, args.get_dossier), indent=2))


def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    _run(_build_parser().parse_args(), SupabaseStore())


if __name__ == "__main__":
    _main()
