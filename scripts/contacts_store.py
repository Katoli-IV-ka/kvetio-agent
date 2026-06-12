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


def upsert_contact(store: SupabaseStore, contact: dict) -> None:
    """Upsert one contact. Conflict key: (company_domain, full_name)."""
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
        "source_vector": contact.get("source_vector", "github"),
        "source_url": contact.get("source_url"),
        "confidence": contact.get("confidence", "medium"),
        "raw_payload": contact.get("raw_payload", {}),
        "updated_at": datetime.utcnow().isoformat(),
    }
    store._client.table("contacts").upsert(
        row, on_conflict="company_domain,full_name"
    ).execute()
    logger.debug("upsert_contact: %s / %s", row["company_domain"], row["full_name"])


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
        upsert_contact(store, contact)
        print("OK")
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
