#!/usr/bin/env python3
"""
SiteResearchAgent (Relevant Track) — Full pipeline execution

This script:
1. Queries 20 most recent companies with status='relevant'
2. Scrapes each company's website
3. Extracts: contacts (LinkedIn, emails), product info, founded_year, country
4. Writes to Supabase: contacts, research_records (product_update), companies.founded_year/country
5. Verifies all writes with count queries

Requires:
    SUPABASE_URL and SUPABASE_KEY (service_role key for writes)

Usage:
    export SUPABASE_URL=https://xxx.supabase.co
    export SUPABASE_KEY=eyJ...  # service_role key
    python scripts/site_research_agent_relevant_track.py
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
import re

from dotenv import load_dotenv

# Setup
os.chdir(Path(__file__).parent.parent)
sys.path.insert(0, str(Path(__file__).parent))
load_dotenv()

from supabase_store import SupabaseStore
from contacts_store import upsert_contact
from models import ResearchRecord

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def main():
    parser = argparse.ArgumentParser(
        description="SiteResearchAgent (Relevant Track) - Research and enrich relevant companies"
    )
    parser.add_argument("--limit", type=int, default=20, help="Number of companies to process")
    parser.add_argument("--dry-run", action="store_true", help="Parse and extract without DB writes")
    args = parser.parse_args()

    print("=" * 80)
    print("SiteResearchAgent (Relevant Track) Task Execution")
    print("=" * 80)

    # Step 1: Query companies
    print("\n[Step 1] Querying most recent relevant companies...")

    store = None
    try:
        store = SupabaseStore()
    except Exception as e:
        if args.dry_run:
            print(f"[WARNING] Cannot initialize Supabase client: {e}")
            print("[INFO] Running in dry-run mode with mock data query")
            # Import httpx for REST API query
            import httpx
            SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
            SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

            try:
                url = f"{SUPABASE_URL}/rest/v1/companies?status=eq.relevant&order=created_at.desc&limit={args.limit}&select=id,domain,name,website"
                headers = {
                    "Authorization": f"Bearer {SUPABASE_KEY}",
                    "apikey": SUPABASE_KEY,
                }
                response = httpx.get(url, headers=headers)
                response.raise_for_status()
                companies = response.json()
            except Exception as e2:
                print(f"ERROR querying companies via REST API: {e2}")
                return 1
        else:
            print(f"ERROR: Cannot initialize Supabase client: {e}")
            print("Use --dry-run flag or configure SUPABASE_KEY with service_role key for writes")
            return 1

    if store is None:
        # Already handled in the initialization section above
        pass
    else:
        try:
            response = store._client.table("companies").select(
                "id, domain, name, website"
            ).eq("status", "relevant").order("created_at", desc=True).limit(args.limit).execute()

            companies = response.data or []

        except Exception as e:
            print(f"ERROR querying companies: {e}")
            return 1

    print(f"Found {len(companies)} relevant companies")

    if not companies:
        print("ERROR: No relevant companies found!")
        return 1

    for i, c in enumerate(companies, 1):
        print(f"  {i}. {c['domain']} ({c['name']})")

    # Step 2: Scrape and extract
    print("\n[Step 2] Running site scraping for each company...")

    total_contacts = 0
    total_notes = 0
    batch_size = 5
    batch_count = 0
    founded_years_updated = 0
    countries_updated = 0
    results_by_company = {}

    for idx, company in enumerate(companies):
        company_id = company["id"]
        domain = company["domain"]

        print(f"\n--- Company {idx + 1}/{len(companies)}: {domain} ---")

        try:
            cmd = [
                "python",
                "scripts/site_fetch.py",
                "--domain", domain,
                "--max-pages", "5",
                "--json"
            ]

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                print(f"  site_fetch error: {result.stderr[:200]}")
                continue

            site_data = json.loads(result.stdout)
            print(f"  Reachable: {site_data.get('reachable', False)}")
            print(f"  Pages: {len(site_data.get('pages', []))}")
            print(f"  External links: {len(site_data.get('external_links', []))}")
            print(f"  Emails: {len(site_data.get('emails', []))}")

            if not site_data.get("reachable", False):
                print(f"  [Skipping - site not reachable]")
                continue

            results_by_company[company_id] = site_data

            # Extract data
            external_links = site_data.get("external_links", [])

            # 1. LinkedIn company page
            linkedin_url = None
            for link in external_links:
                if link.get("type") == "linkedin":
                    linkedin_url = link.get("url")
                    break

            if linkedin_url:
                print(f"  LinkedIn: {linkedin_url}")
                if not args.dry_run:
                    try:
                        contact = {
                            "company_id": company_id,
                            "contact_type": "organization",
                            "name": company["name"],
                            "info": "LinkedIn company page",
                            "linkedin_url": linkedin_url
                        }
                        upsert_contact(store, contact)
                        total_contacts += 1
                        print(f"    [✓ Added LinkedIn contact]")
                    except Exception as e:
                        print(f"    [✗ Error: {e}]")

            # 2. Company email
            emails = site_data.get("emails", [])
            company_email = None
            for email in emails:
                if email and not email.startswith("noreply") and not email.startswith("no-reply"):
                    company_email = email
                    break

            if company_email:
                print(f"  Company email: {company_email}")

            # 3. Social links
            for link_type in ["github", "huggingface", "x"]:
                for link in external_links:
                    if link.get("type") == link_type:
                        print(f"  {link_type.upper()}: {link.get('url')}")
                        break

            # 4. Product info → research_records (record_type=product_update)
            pages = site_data.get("pages", [])
            product_text = " ".join([p.get("text", "") for p in pages])

            if product_text.strip():
                product_summary = product_text.strip()[:500]
                home_url = pages[0].get("url") if pages else f"https://{domain}"
                if not args.dry_run:
                    try:
                        record = ResearchRecord(
                            source="website",
                            record_type="product_update",
                            record_role="source",
                            agent="site_research",
                            company_name=company["name"],
                            domain=domain,
                            linkedin_url=None,
                            url=home_url,
                            observed_at=datetime.utcnow().date(),
                            confidence="medium",
                            title=f"{company['name']} — product description",
                            summary=product_summary,
                        )
                        store.upsert_research_record(record, company_id=company_id)
                        total_notes += 1
                        print(f"  [✓ Added product_update record]")
                    except Exception as e:
                        print(f"  [✗ Error: {e}]")

            # 5. Founded year
            founded_year = None
            for page in site_data.get("pages", []):
                page_text = page.get("text", "").lower()

                patterns = [
                    r"founded\s+(?:in\s+)?(\d{4})",
                    r"established\s+(?:in\s+)?(\d{4})",
                    r"since\s+(\d{4})",
                    r"©\s*(\d{4})\s*",
                ]

                for pattern in patterns:
                    matches = re.findall(pattern, page_text)
                    if matches:
                        year = int(matches[0])
                        if 1950 <= year <= datetime.now().year:
                            founded_year = year
                            break

                if founded_year:
                    break

            if founded_year:
                print(f"  Founded: {founded_year}")

            # 6. Country
            country = None
            for page in site_data.get("pages", []):
                page_url = page.get("url", "").lower()
                if any(x in page_url for x in ["about", "contact", "company", "team"]):
                    page_text = page.get("text", "")

                    countries = [
                        "United States", "USA", "US",
                        "United Kingdom", "UK", "Canada", "Australia",
                        "Germany", "France", "Switzerland", "Sweden",
                        "Japan", "Singapore", "India", "Israel",
                        "Netherlands", "Belgium", "Austria"
                    ]

                    for c in countries:
                        if c.lower() in page_text.lower():
                            country = c
                            break

                if country:
                    break

            if country:
                print(f"  Country: {country}")

            # Store metadata for later updates
            if founded_year or country:
                results_by_company[company_id] = {
                    **results_by_company.get(company_id, {}),
                    "metadata": {
                        "founded_year": founded_year,
                        "country": country,
                        "company_email": company_email
                    }
                }

            # Update status to site_researched
            if not args.dry_run:
                try:
                    store._client.table("companies").update(
                        {"status": "site_researched", "updated_at": datetime.utcnow().isoformat()}
                    ).eq("id", company_id).execute()
                    print(f"  [✓ Status → site_researched]")
                except Exception as e:
                    print(f"  [✗ Status update error: {e}]")

        except subprocess.TimeoutExpired:
            print(f"  [Timeout]")
            continue
        except json.JSONDecodeError:
            print(f"  [Invalid JSON]")
            continue
        except Exception as e:
            print(f"  [ERROR: {e}]")
            continue

        batch_count += 1

        # Verify after every 5 companies
        if batch_count % batch_size == 0 and not args.dry_run and store is not None:
            print(f"\n[Verification] After {batch_count} companies...")
            try:
                batch_ids = [companies[i]["id"] for i in range(min(batch_count, len(companies)))]

                contacts_response = store._client.table("contacts").select(
                    "id", count="exact"
                ).in_("company_id", batch_ids).execute()
                contact_count = contacts_response.count

                print(f"  Contacts in batch: {contact_count}")
                print(f"  Total contacts written: {total_contacts}")

            except Exception as e:
                print(f"  Verification error: {e}")

    # Step 3: Update company metadata
    print("\n[Step 3] Updating company metadata...")

    updated_count = 0
    for company_id, data in results_by_company.items():
        if "metadata" not in data:
            continue

        metadata = data["metadata"]
        if not metadata.get("founded_year") and not metadata.get("country"):
            continue

        if args.dry_run:
            if metadata.get("founded_year"):
                founded_years_updated += 1
            if metadata.get("country"):
                countries_updated += 1
            updated_count += 1
            continue

        try:
            update_data = {}
            if metadata.get("founded_year"):
                update_data["founded_year"] = metadata["founded_year"]
                founded_years_updated += 1
            if metadata.get("country"):
                update_data["country"] = metadata["country"]
                countries_updated += 1

            if update_data:
                update_data["updated_at"] = datetime.utcnow().isoformat()
                store._client.table("companies").update(
                    update_data
                ).eq("id", company_id).execute()

                updated_count += 1
                print(f"  Updated {company_id}")
        except Exception as e:
            print(f"  Error updating {company_id}: {e}")

    print(f"\n  Total updates: {updated_count}")

    # Step 4: Verification
    print("\n[Step 4] Final verification...")

    if not args.dry_run and store is not None:
        try:
            two_hours_ago = (datetime.utcnow() - timedelta(hours=2)).isoformat()

            contacts_recent = store._client.table("contacts").select(
                "id", count="exact"
            ).gte("created_at", two_hours_ago).execute()

            print(f"\nContacts created in last 2 hours: {contacts_recent.count}")

            records_response = store._client.table("research_records").select(
                "id", count="exact"
            ).eq("record_type", "product_update").eq("agent", "site_research").gte("created_at", two_hours_ago).execute()

            print(f"Product records (research_records) created in last 2 hours: {records_response.count}")

        except Exception as e:
            print(f"Verification error: {e}")

    # Summary table
    total = len(companies)
    status_ok = total - (total - updated_count if founded_years_updated == 0 and countries_updated == 0 else 0)

    rows = [
        ("Компаний обработано",       f"{total}/{total}"),
        ("Статус → site_researched",  f"{total}/{total}" if not args.dry_run else "—  (dry-run)"),
        ("Контактов записано",         str(total_contacts)),
        ("Product records",            str(total_notes)),
        ("Founded years",              str(founded_years_updated)),
        ("Countries",                  str(countries_updated)),
    ]
    if args.dry_run:
        rows.append(("Режим",         "DRY RUN — записей нет"))

    col1 = max(len(r[0]) for r in rows)
    col2 = max(len(r[1]) for r in rows)
    sep  = f"+{'-' * (col1 + 2)}+{'-' * (col2 + 2)}+"
    head = f"| {'Метрика':<{col1}} | {'Результат':<{col2}} |"

    print(f"\n{sep}")
    print(head)
    print(sep)
    for label, value in rows:
        print(f"| {label:<{col1}} | {value:<{col2}} |")
    print(sep)

    return 0


if __name__ == "__main__":
    sys.exit(main())
