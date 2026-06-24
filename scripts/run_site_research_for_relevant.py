#!/usr/bin/env python3
"""
Orchestrate site research for 20 most recent relevant companies.

This script:
1. Queries companies with status='relevant'
2. Selects 20 most recent
3. Passes them to agent for site scraping and enrichment
"""

import json
import os
from datetime import datetime

def get_relevant_companies(limit: int = 20) -> list[dict]:
    """Fetch relevant companies from Supabase."""
    try:
        from scripts.supabase_store import SupabaseStore

        store = SupabaseStore(
            os.getenv('SUPABASE_URL'),
            os.getenv('SUPABASE_KEY')
        )

        result = store.db.table('companies').select(
            'id, domain, name, website, created_at'
        ).eq('status', 'relevant').order('created_at', desc=True).limit(limit).execute()

        return result.data
    except Exception as e:
        print(f"Error fetching companies: {e}")
        return []


def format_companies_for_agent(companies: list[dict]) -> str:
    """Format companies list for agent input."""
    if not companies:
        return "No relevant companies found."

    lines = [f"Found {len(companies)} relevant companies:\n"]
    for i, c in enumerate(companies, 1):
        lines.append(f"{i}. {c['domain']} ({c['name']}) - {c['website']}")

    return "\n".join(lines)


def main():
    print("Fetching relevant companies...")
    companies = get_relevant_companies(20)

    if not companies:
        print("No relevant companies found in database.")
        return

    summary = format_companies_for_agent(companies)
    print(summary)

    # Return for agent processing
    return {
        'timestamp': datetime.now().isoformat(),
        'companies_count': len(companies),
        'companies': companies
    }


if __name__ == '__main__':
    result = main()
    if result:
        print(f"\n✓ Ready for agent processing: {result['companies_count']} companies")
