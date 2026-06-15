"""CRUD for contacts plus dm_enriched_at marker on companies.

CLI:
    echo '{"company_domain":"radai.com","full_name":"Sarah Chen","source_vector":"apollo"}' \
        | python scripts/contacts_store.py --upsert
    python scripts/contacts_store.py --mark-enriched radai.com
    python scripts/contacts_store.py --list radai.com
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


def upsert_contact(store: SupabaseStore, contact: dict) -> str:
    """Upsert one contact. Conflict key: (company_domain, full_name).

    Returns the contact's UUID (id).
    """
    row = {
        "company_domain": contact["company_domain"],
        "full_name": contact["full_name"],
        "first_name": contact.get("first_name"),
        "last_name": contact.get("last_name"),
        "title": contact.get("title"),
        "title_normalized": contact.get("title_normalized"),
        "dm_priority": contact.get("dm_priority", 2),
        "email": contact.get("email"),
        "email_status": contact.get("email_status", "unknown"),
        "email_source": contact.get("email_source"),
        "linkedin_url": contact.get("linkedin_url"),
        "twitter_handle": contact.get("twitter_handle"),
        "github_username": contact.get("github_username"),
        "hf_username": contact.get("hf_username"),
        "personal_website": contact.get("personal_website"),
        "source_vector": contact.get("source_vector", "github"),
        "source_url": contact.get("source_url"),
        "confidence": contact.get("confidence", "medium"),
        "raw_payload": contact.get("raw_payload", {}),
        # V2 fields
        "contact_type": contact.get("contact_type", "Person"),
        "phone": contact.get("phone"),
        "instagram_url": contact.get("instagram_url"),
        "facebook_url": contact.get("facebook_url"),
        "info": contact.get("info"),
        "contact_result": contact.get("contact_result"),
        "updated_at": datetime.utcnow().isoformat(),
    }
    res = store._client.table("contacts").upsert(
        row, on_conflict="company_domain,full_name"
    ).execute()
    logger.debug("upsert_contact: %s / %s", row["company_domain"], row["full_name"])
    if res.data:
        return res.data[0]["id"]
    return ""


def link_contact_to_companies(
    store: SupabaseStore, contact_id: str, company_domains: list[str]
) -> None:
    """Upsert rows in contact_companies join table (idempotent)."""
    if not company_domains:
        return
    rows = [
        {"contact_id": contact_id, "company_domain": domain}
        for domain in company_domains
    ]
    store._client.table("contact_companies").upsert(
        rows, on_conflict="contact_id,company_domain", ignore_duplicates=True
    ).execute()
    logger.debug("link_contact_to_companies: %s -> %s", contact_id, company_domains)


def get_company_domains_for_contact(
    store: SupabaseStore, contact_id: str
) -> list[str]:
    """Return all company_domains linked to a contact."""
    res = (
        store._client.table("contact_companies")
        .select("company_domain")
        .eq("contact_id", contact_id)
        .execute()
    )
    return [r["company_domain"] for r in (res.data or [])]


def mark_enriched(store: SupabaseStore, domain: str) -> None:
    """Set dm_enriched_at on the company row."""
    now = datetime.utcnow().isoformat()
    store._client.table("companies").update({
        "dm_enriched_at": now,
        "updated_at": now,
    }).eq("domain", domain).execute()
    logger.debug("mark_enriched: %s", domain)


def list_contacts(store: SupabaseStore, domain: str) -> list[dict]:
    """Return company contacts ordered by dm_priority."""
    res = (
        store._client.table("contacts")
        .select("*")
        .eq("company_domain", domain)
        .order("dm_priority")
        .execute()
    )
    return res.data or []


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="contacts_store CLI")
    parser.add_argument("--upsert", action="store_true", help="Upsert contact JSON from stdin")
    parser.add_argument("--mark-enriched", metavar="DOMAIN", dest="mark_enriched")
    parser.add_argument("--list", metavar="DOMAIN", dest="list_domain")
    args = parser.parse_args()

    store = SupabaseStore()

    if args.upsert:
        contact = json.loads(sys.stdin.read())
        contact_id = upsert_contact(store, contact)
        if contact.get("company_domains"):
            link_contact_to_companies(store, contact_id, contact["company_domains"])
        print(f"OK (id={contact_id})")
    elif args.mark_enriched:
        mark_enriched(store, args.mark_enriched)
        print(f"Marked {args.mark_enriched} as dm_enriched")
    elif args.list_domain:
        contacts = list_contacts(store, args.list_domain)
        print(json.dumps(contacts, ensure_ascii=False, indent=2, default=str))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
