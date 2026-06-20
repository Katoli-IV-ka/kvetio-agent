#!/usr/bin/env python3
"""Analyze 12 companies from research_records and create analysis_records.

This script processes companies across 4 segments (3 per segment):
- speech-and-audio: neuphonic.com, soundhound.com, resemble.ai
- agriculture-ai: aerobotics.com, taranis.com, raptormaps.com
- robotics-ai: viam.com, covariant.ai, figure.ai
- video-photo-ai: descript.com, moonvalley.ai, kling.ai

For each company:
1. Fetch research_records from Supabase
2. Extract facts for 5 sections: company, product, collaboration, financials, news
3. Create analysis_records with extracted facts
4. Update company status to 'analyzed'
"""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from supabase_store import SupabaseStore
from dossier_store import upsert_analysis_record

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

load_dotenv(Path(__file__).parent.parent / ".env")

# Companies to analyze (domain -> segment)
COMPANIES = {
    "neuphonic.com": "speech-and-audio",
    "soundhound.com": "speech-and-audio",
    "resemble.ai": "speech-and-audio",
    "aerobotics.com": "agriculture-ai",
    "taranis.com": "agriculture-ai",
    "raptormaps.com": "agriculture-ai",
    "viam.com": "robotics-ai",
    "covariant.ai": "robotics-ai",
    "figure.ai": "robotics-ai",
    "descript.com": "video-photo-ai",
    "moonvalley.ai": "video-photo-ai",
    "kling.ai": "video-photo-ai",
}

SECTIONS = ["company", "product", "collaboration", "financials", "news"]


def extract_facts_from_research_records(
    research_records: list[dict], section: str
) -> dict[str, Any]:
    """Extract facts for a specific section from research_records.

    Pragmatic extraction based on record types and content.
    """
    facts = {}

    if section == "company":
        # Extract from company info: founding, location, team size, description
        sources = []
        evidence_types = set()
        for record in research_records:
            payload = record.get("payload", {})
            summary = record.get("summary", "")
            record_type = record.get("record_type", "")
            source = record.get("source", "")
            url = record.get("url", "")

            if payload.get("founded_year"):
                facts["founded_year"] = payload["founded_year"]
            if payload.get("headquarters_location"):
                facts["headquarters"] = payload["headquarters_location"]
            if payload.get("team_size"):
                facts["team_size"] = payload["team_size"]
            if payload.get("description") and "description" not in facts:
                facts["description"] = payload["description"][:200]

            # Try to infer from summary
            if summary and not facts.get("description"):
                facts["description"] = summary[:200]

            # Track sources
            if url:
                sources.append({"type": record_type, "source": source, "url": url})
            if record_type:
                evidence_types.add(record_type)

        # Add sources and record types found
        if sources:
            facts["sources"] = sources
        if evidence_types:
            facts["evidence_types"] = list(evidence_types)

        # Default facts if nothing extracted
        if not facts:
            facts["data_collected"] = True

    elif section == "product":
        # Extract product info: what they build, use cases, features
        sources = []
        for record in research_records:
            payload = record.get("payload", {})
            summary = record.get("summary", "")
            url = record.get("url", "")
            record_type = record.get("record_type", "")
            source = record.get("source", "")

            if payload.get("product_name"):
                facts["product_name"] = payload["product_name"]
            if payload.get("product_description") and "product_description" not in facts:
                facts["product_description"] = payload["product_description"][:250]
            if payload.get("use_cases"):
                facts["use_cases"] = payload["use_cases"]
            if payload.get("key_features"):
                facts["key_features"] = payload["key_features"]

            # Infer from summary
            if summary and not facts.get("product_description"):
                facts["product_description"] = summary[:250]

            # Track sources
            if url:
                sources.append({"type": record_type, "source": source, "url": url})

        # Add sources
        if sources:
            facts["sources"] = sources

        if not facts:
            facts["data_collected"] = True

    elif section == "collaboration":
        # Extract partnerships, team, structure
        sources = []
        for record in research_records:
            payload = record.get("payload", {})
            url = record.get("url", "")
            record_type = record.get("record_type", "")
            source = record.get("source", "")

            if payload.get("partnerships"):
                facts["partnerships"] = payload["partnerships"]
            if payload.get("team_members"):
                facts["team_members"] = payload["team_members"]
            if payload.get("founders"):
                facts["founders"] = payload["founders"]
            if payload.get("leadership"):
                facts["leadership"] = payload["leadership"]

            # Track sources (HuggingFace orgs, GitHub orgs reveal team)
            if record_type in ["hf_org", "github_org"]:
                sources.append({"type": record_type, "source": source, "url": url})

        if sources:
            facts["sources"] = sources

        if not facts:
            facts["data_collected"] = True

    elif section == "financials":
        # Extract funding: stage, amount, date
        sources = []
        funding_found = False
        for record in research_records:
            payload = record.get("payload", {})
            record_type = record.get("record_type", "")
            url = record.get("url", "")
            source = record.get("source", "")

            if record_type == "funding_announcement":
                funding_found = True
                if payload.get("funding_stage"):
                    facts["latest_funding_stage"] = payload["funding_stage"]
                if payload.get("funding_amount"):
                    facts["latest_funding_amount"] = payload["funding_amount"]
                if payload.get("funding_currency"):
                    facts["funding_currency"] = payload["funding_currency"]
                sources.append({"type": record_type, "source": source, "url": url})

            if payload.get("valuation"):
                facts["valuation"] = payload["valuation"]
            if payload.get("investors"):
                facts["investors"] = payload["investors"]

        if sources:
            facts["sources"] = sources

        if not facts:
            facts["data_collected"] = True

    elif section == "news":
        # Extract recent news: developments in last 6-12 months
        news_items = []
        for record in research_records:
            if record.get("record_type") in ["news", "product_update"]:
                title = record.get("title", "")
                observed_at = record.get("observed_at", "")
                url = record.get("url", "")
                if title:
                    news_items.append({
                        "title": title,
                        "date": observed_at,
                        "url": url
                    })

        if news_items:
            facts["recent_news"] = news_items[:5]  # Top 5 recent
        else:
            facts["data_collected"] = True

    return facts


def analyze_company(store: SupabaseStore, domain: str, segment: str) -> dict:
    """Analyze a single company and create analysis_records.

    Returns:
        {
            "domain": str,
            "company_id": str,
            "sections_created": int,
            "errors": list[str]
        }
    """
    result = {
        "domain": domain,
        "company_id": None,
        "sections_created": 0,
        "errors": [],
    }

    try:
        # Resolve company_id from domain
        company = store.get_company(domain)
        if not company:
            result["errors"].append(f"Company not found: {domain}")
            return result

        company_id = company.get("id")
        result["company_id"] = company_id

        logger.info(f"Analyzing {domain} ({company_id})")

        # Fetch research_records
        research_records = store.get_research_records_for_analysis(company_id)
        if not research_records:
            result["errors"].append(f"No research_records found")
        else:
            logger.info(f"  Found {len(research_records)} research records")

        # Create analysis_records for each section
        for section in SECTIONS:
            try:
                facts = extract_facts_from_research_records(research_records, section)

                # Determine confidence based on fact content
                confidence = "low"  # Default to low
                if facts.get("data_collected"):
                    # Data was collected but minimal extraction
                    confidence = "low"
                elif any(k in facts for k in ["founded_year", "team_size", "product_name", "latest_funding_stage", "recent_news"]):
                    # Specific facts extracted
                    confidence = "medium"
                elif len(facts.get("sources", [])) > 0 and len(facts) > 1:
                    # Multiple sources and facts
                    confidence = "medium"

                analysis_record = {
                    "company_id": company_id,
                    "section": section,
                    "facts": facts,
                    "confidence": confidence,
                    "model": "claude",
                    "version": "v1",
                }

                record_id = upsert_analysis_record(store, analysis_record)
                if record_id:
                    result["sections_created"] += 1
                    logger.info(f"    Created analysis_record: {section} ({record_id})")
                else:
                    result["errors"].append(f"Failed to create analysis_record for {section}")

            except Exception as e:
                error_msg = f"Error creating {section} analysis: {str(e)}"
                logger.error(f"    {error_msg}")
                result["errors"].append(error_msg)

        # Update company status to 'analyzed'
        try:
            store.update_status(domain, "analyzed")
            logger.info(f"  Updated status to 'analyzed'")
        except Exception as e:
            result["errors"].append(f"Failed to update status: {str(e)}")

    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.error(f"  {error_msg}")
        result["errors"].append(error_msg)

    return result


def main():
    """Process all 12 companies."""
    store = SupabaseStore()

    all_results = []
    companies_analyzed = 0
    total_sections = 0
    total_errors = 0

    logger.info(f"Starting analysis of {len(COMPANIES)} companies...")

    for domain, segment in COMPANIES.items():
        result = analyze_company(store, domain, segment)
        all_results.append(result)

        if result["company_id"]:
            companies_analyzed += 1
            total_sections += result["sections_created"]

        total_errors += len(result["errors"])

        if result["errors"]:
            for error in result["errors"]:
                logger.warning(f"    {error}")

    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("ANALYSIS SUMMARY")
    logger.info("=" * 60)
    logger.info(f"Companies analyzed: {companies_analyzed}/{len(COMPANIES)}")
    logger.info(f"Analysis records created: {total_sections}")
    logger.info(f"Status updates: {companies_analyzed}")
    logger.info(f"Total errors: {total_errors}")
    logger.info("=" * 60)

    # Print detailed results
    logger.info("\nDetailed Results:")
    for result in all_results:
        status = "OK" if not result["errors"] else "ERROR"
        logger.info(f"{result['domain']}: {status} ({result['sections_created']} sections)")
        if result["errors"]:
            for error in result["errors"]:
                logger.info(f"  - {error}")

    return 0 if total_errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
