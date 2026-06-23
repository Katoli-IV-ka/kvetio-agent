"""Shared persistence for contact fetchers."""

from __future__ import annotations

import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from contacts_store import upsert_contact
from models import ResearchRecord
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)


def best_evidence_url(domain: str, contact: dict) -> str:
    """Return the best evidence URL for a contact_found research record."""
    for field in ("linkedin_url", "x_url", "facebook_url", "instagram_url"):
        value = contact.get(field)
        if value:
            return str(value)
    for item in contact.get("other_channels") or []:
        if isinstance(item, dict) and item.get("url"):
            return str(item["url"])
    return f"https://{domain}"


def _channels_payload(contact: dict) -> dict:
    return {
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "linkedin_url": contact.get("linkedin_url"),
        "x_url": contact.get("x_url"),
        "facebook_url": contact.get("facebook_url"),
        "instagram_url": contact.get("instagram_url"),
        "other_channels": contact.get("other_channels") or [],
    }


def _write_audit(
    store: SupabaseStore,
    *,
    domain: str,
    source: str,
    contact: dict,
    contact_id: str,
) -> None:
    entry = ResearchRecord(
        source=source,
        record_type="contact_found",
        company_name=domain,
        domain=domain,
        linkedin_url=contact.get("linkedin_url"),
        url=best_evidence_url(domain, contact),
        observed_at=date.today(),
        confidence="medium",
        record_role="evidence",
        agent="contact_writer",
        title=str(contact.get("name") or "Contact found"),
        summary=str(contact.get("info") or f"Contact found via {source}"),
        payload={
            "contact_id": contact_id,
            "contact_name": contact.get("name"),
            "contact_type": contact.get("contact_type", "person"),
            "source": source,
            "channels": _channels_payload(contact),
        },
    )
    store.upsert_research_record(entry, domain=domain)


def write_contacts(
    *,
    domain: str,
    source: str,
    contacts: list[dict],
    store: SupabaseStore | None = None,
) -> dict[str, int]:
    """Persist contacts and contact_found audit rows.

    Returns counters for tests and logs. CLI callers should not print this as a
    JSON summary.
    """
    store = store or SupabaseStore()
    result = {"found": len(contacts), "written": 0, "skipped": 0, "audit_errors": 0}

    for contact in contacts:
        if not isinstance(contact, dict) or not str(contact.get("name") or "").strip():
            result["skipped"] += 1
            logger.warning("Skipping contact without name for %s from %s", domain, source)
            continue

        payload = {**contact, "company_domain": domain}
        contact_id = upsert_contact(store, payload)
        result["written"] += 1

        try:
            _write_audit(
                store,
                domain=domain,
                source=source,
                contact=contact,
                contact_id=contact_id,
            )
        except Exception as exc:  # noqa: BLE001
            result["audit_errors"] += 1
            logger.warning(
                "contact_found audit write failed for %s/%s: %s",
                domain,
                contact.get("name"),
                exc,
            )

    logger.info(
        "contacts %s: found=%s written=%s skipped=%s audit_errors=%s",
        domain,
        result["found"],
        result["written"],
        result["skipped"],
        result["audit_errors"],
    )
    return result
