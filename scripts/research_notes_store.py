"""Store research notes and manage category options for SiteResearchAgent."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from supabase_store import SupabaseStore

VALID_NOTE_TYPES = {"product", "press_release", "cooperative", "finance"}


def content_hash(content: str) -> str:
    """Return a stable SHA-256 hex digest for note content."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def upsert_note(
    store: SupabaseStore,
    *,
    company_id: str,
    note_type: str,
    content: str,
    source_url: str | None = None,
) -> str:
    """Insert a research note unless an identical one exists. Returns row id."""
    if note_type not in VALID_NOTE_TYPES:
        raise ValueError(f"invalid note_type: {note_type}")

    digest = content_hash(content)
    existing = (
        store._client.table("research_notes")
        .select("id")
        .eq("company_id", company_id)
        .eq("note_type", note_type)
        .eq("content_hash", digest)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]

    row = {
        "company_id": company_id,
        "note_type": note_type,
        "content": content,
        "content_hash": digest,
        "source_url": source_url,
    }
    result = store._client.table("research_notes").insert(row).execute()
    return result.data[0]["id"] if result.data else ""


def ensure_category(store: SupabaseStore, value: str, label: str | None = None) -> None:
    """Ensure a category select option exists before assigning it to a company."""
    existing = (
        store._client.table("category_options")
        .select("value")
        .eq("value", value)
        .execute()
    )
    if existing.data:
        return
    store._client.table("category_options").insert(
        {"value": value, "label": label or value}
    ).execute()
