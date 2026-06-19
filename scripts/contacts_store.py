"""CRUD for contacts.

CLI:
    echo '{"company_domain":"radai.com","name":"Sarah Chen"}' \
        | python scripts/contacts_store.py --upsert
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

PRIMARY_OTHER_CHANNEL_TYPES = {
    "email",
    "phone",
    "linkedin",
    "linkedin_url",
    "x",
    "twitter",
    "twitter_url",
    "facebook",
    "facebook_url",
    "instagram",
    "instagram_url",
}


def contact_name(contact: dict) -> str:
    """Return contact name, accepting legacy first/last/full_name payloads."""
    explicit = (contact.get("name") or "").strip()
    if explicit:
        return explicit

    full_name = (contact.get("full_name") or "").strip()
    if full_name:
        return full_name

    first = (contact.get("first_name") or "").strip()
    last = (contact.get("last_name") or "").strip()
    name = " ".join(part for part in (first, last) if part).strip()
    if name:
        return name

    raise ValueError("name or first_name/full_name is required")


def normalize_x_url(contact: dict) -> str | None:
    """Return a full X URL from x_url, twitter_url, or twitter_handle."""
    explicit = contact.get("x_url") or contact.get("twitter_url")
    if explicit:
        return explicit
    handle = (contact.get("twitter_handle") or "").strip()
    if not handle:
        return None
    return f"https://x.com/{handle.lstrip('@')}"


def _channel(type_: str, url: str, label: str | None = None) -> dict:
    item = {"type": type_, "url": url}
    if label:
        item["label"] = label
    return item


def normalize_other_channels(contact: dict) -> list[dict]:
    """Normalize secondary contact channels and remove primary-channel duplicates."""
    candidates: list[dict] = []

    github_username = (contact.get("github_username") or "").strip()
    if github_username:
        candidates.append(_channel("github", f"https://github.com/{github_username}"))

    hf_username = (contact.get("hf_username") or "").strip()
    if hf_username:
        candidates.append(_channel("huggingface", f"https://huggingface.co/{hf_username}"))

    personal_website = contact.get("personal_website")
    if personal_website:
        candidates.append(_channel("personal_website", personal_website))

    for item in contact.get("other_channels") or []:
        if not isinstance(item, dict):
            continue
        type_ = str(item.get("type") or "").strip()
        url = str(item.get("url") or "").strip()
        if not type_ or not url:
            continue
        if type_ in PRIMARY_OTHER_CHANNEL_TYPES:
            continue
        normalized = {"type": type_, "url": url}
        if item.get("label"):
            normalized["label"] = str(item["label"])
        candidates.append(normalized)

    seen: set[tuple[str, str]] = set()
    result: list[dict] = []
    for item in candidates:
        key = (item["type"], item["url"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def resolve_company_ref(
    store: SupabaseStore,
    *,
    domain: str | None = None,
    company_id: str | None = None,
) -> dict:
    """Return company id/domain for contact writes."""
    if company_id:
        res = (
            store._client.table("companies")
            .select("id,domain")
            .eq("id", company_id)
            .limit(1)
            .execute()
        )
    elif domain:
        res = (
            store._client.table("companies")
            .select("id,domain")
            .eq("domain", domain)
            .limit(1)
            .execute()
        )
    else:
        raise ValueError("company_id or company_domain is required")

    if not res.data:
        ref = company_id or domain
        raise ValueError(f"company not found for contact: {ref}")
    return res.data[0]


def upsert_contact(store: SupabaseStore, contact: dict) -> str:
    """Upsert one contact. Conflict key: (company_id, contact_type, name)."""
    company_ref = resolve_company_ref(
        store,
        domain=contact.get("company_domain"),
        company_id=contact.get("company_id"),
    )
    name = contact_name(contact)
    contact_type = contact.get("contact_type", "person")
    row = {
        "company_id": company_ref["id"],
        "contact_type": contact_type,
        "name": name,
        "info": contact.get("info") or contact.get("title") or contact.get("title_normalized"),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "linkedin_url": contact.get("linkedin_url"),
        "x_url": normalize_x_url(contact),
        "facebook_url": contact.get("facebook_url"),
        "instagram_url": contact.get("instagram_url"),
        "other_channels": normalize_other_channels(contact),
        "updated_at": datetime.utcnow().isoformat(),
    }
    if contact.get("discovered_from_research_record_id"):
        row["discovered_from_research_record_id"] = contact[
            "discovered_from_research_record_id"
        ]
    res = store._client.table("contacts").upsert(
        row, on_conflict="company_id,contact_type,name"
    ).execute()
    logger.debug("upsert_contact: %s / %s", company_ref["domain"], name)
    if res.data:
        return res.data[0]["id"]
    return ""


def list_contacts(store: SupabaseStore, domain: str) -> list[dict]:
    """Return company contacts ordered by type and name."""
    company_ref = resolve_company_ref(store, domain=domain)
    res = (
        store._client.table("contacts")
        .select("*")
        .eq("company_id", company_ref["id"])
        .order("contact_type")
        .order("name")
        .execute()
    )
    return res.data or []


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="contacts_store CLI")
    parser.add_argument("--upsert", action="store_true", help="Upsert contact JSON from stdin")
    parser.add_argument("--list", metavar="DOMAIN", dest="list_domain")
    args = parser.parse_args()

    store = SupabaseStore()

    if args.upsert:
        contact = json.loads(sys.stdin.read())
        contact_id = upsert_contact(store, contact)
        print(f"OK (id={contact_id})")
    elif args.list_domain:
        contacts = list_contacts(store, args.list_domain)
        print(json.dumps(contacts, ensure_ascii=False, indent=2, default=str))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
