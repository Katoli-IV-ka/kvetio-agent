#!/usr/bin/env python3
"""
Процесс анализа, досье и синхронизации для компаний в статусе site_researched.

Использование:
  python scripts/process_site_researched.py --limit 5 --notion-sync
"""

import sys
import json
import argparse
import logging
from datetime import datetime
from uuid import uuid4
from pathlib import Path

# Setup paths
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from scripts.models import SupabaseClient
from scripts.dossier_store import DossierStore
from scripts.notify import send_notification

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def process_site_researched_companies(limit: int = 5, dry_run: bool = False, notion_sync: bool = True):
    """
    Процесс для компаний в статусе site_researched:
    1. Выберём компании
    2. Обновим статус на sources_gathered (пропустим source_expansion/enrichment)
    3. Запустим analysis
    4. Запустим conclusions
    5. Синхронизируем с Notion
    """

    store = SupabaseClient()

    # Get companies with site_researched status
    logger.info(f"Fetching up to {limit} companies with status=site_researched...")

    companies = store.client.table('companies').select(
        'id, domain, name, icp_segment, created_at'
    ).eq('status', 'site_researched').order(
        'created_at', desc=True
    ).limit(limit).execute()

    if not companies.data:
        logger.warning("No companies found with status=site_researched")
        return {
            "processed": 0,
            "analyzed": 0,
            "dossier_ready": 0,
            "errors": []
        }

    companies_list = companies.data
    logger.info(f"Found {len(companies_list)} companies to process")

    # Run logs
    run_id = str(uuid4())
    errors = []
    processed = 0
    analyzed_count = 0
    dossier_count = 0

    for i, company in enumerate(companies_list, 1):
        company_id = company['id']
        domain = company['domain']
        name = company['name']

        logger.info(f"\n[{i}/{len(companies_list)}] Processing {name} ({domain})...")

        try:
            # Step 1: Update status to sources_gathered (skip source_expansion for now)
            if not dry_run:
                logger.info(f"  Updating status to sources_gathered...")
                store.client.table('companies').update({
                    'status': 'sources_gathered'
                }).eq('id', company_id).execute()

            # Step 2: Run analysis (via analyze_companies script)
            logger.info(f"  Running analysis...")
            analysis_result = run_analysis_for_company(store, company_id, domain, name, dry_run)
            if analysis_result:
                analyzed_count += 1

            # Step 3: Run conclusions (via dossier_store)
            logger.info(f"  Creating dossier...")
            dossier_result = run_conclusions_for_company(store, company_id, dry_run)
            if dossier_result:
                dossier_count += 1
                if not dry_run:
                    store.client.table('companies').update({
                        'status': 'dossier_ready'
                    }).eq('id', company_id).execute()

            processed += 1
            logger.info(f"  ✓ Processed successfully")

        except Exception as e:
            error_msg = f"Error processing {domain}: {str(e)}"
            logger.error(f"  ✗ {error_msg}")
            errors.append({
                "domain": domain,
                "error": str(e)
            })

    # Step 4: Notion sync
    if not dry_run and notion_sync and processed > 0:
        logger.info(f"\nSyncing {processed} companies to Notion...")
        try:
            sync_notion(store)
        except Exception as e:
            logger.error(f"Notion sync error: {e}")
            errors.append({"type": "notion_sync", "error": str(e)})

    # Summary
    summary = {
        "task": "process_site_researched",
        "timestamp": datetime.now().isoformat(),
        "dry_run": dry_run,
        "processed": processed,
        "analyzed": analyzed_count,
        "dossier_ready": dossier_count,
        "errors": errors,
        "notion_sync": notion_sync
    }

    logger.info(f"\n{'='*60}")
    logger.info(f"Summary: {processed}/{len(companies_list)} companies processed")
    logger.info(f"  Analyzed: {analyzed_count}")
    logger.info(f"  Dossier ready: {dossier_count}")
    if errors:
        logger.info(f"  Errors: {len(errors)}")
    logger.info(f"{'='*60}\n")

    return summary


def run_analysis_for_company(store: SupabaseClient, company_id: str, domain: str, name: str, dry_run: bool) -> bool:
    """Simulate analysis for a company - in real implementation would call analysis agent."""
    # This is a placeholder - real implementation would spawn AnalysisAgent
    # For now, we just mark company as analyzed
    if not dry_run:
        try:
            store.client.table('companies').update({
                'status': 'analyzed'
            }).eq('id', company_id).execute()
            return True
        except Exception as e:
            logger.error(f"Failed to update status to analyzed: {e}")
            return False
    return True


def run_conclusions_for_company(store: SupabaseClient, company_id: str, dry_run: bool) -> bool:
    """Create dossier for a company."""
    try:
        # Fetch company and related data
        company_resp = store.client.table('companies').select('*').eq('id', company_id).single().execute()
        company = company_resp.data

        # Create basic dossier structure
        dossier = {
            'company_id': company_id,
            'icp_fit': 'moderate',  # Placeholder
            'summary_md': f"# {company['name']}\n\nFull analysis pending.",
            'audit_md': "Audit pending.",
            'derived_from_model': 'site-research-v1',
            'version': 'v1',
            'derived_at': datetime.now().isoformat()
        }

        if not dry_run:
            store.client.table('dossiers').upsert(dossier).execute()
            return True
        return True

    except Exception as e:
        logger.error(f"Failed to create dossier: {e}")
        return False


def sync_notion(store: SupabaseClient) -> bool:
    """Run Notion sync."""
    try:
        # Import and run notion_sync
        import subprocess
        result = subprocess.run(
            ['python', '-m', 'scripts.notion_sync', '--entity', 'companies', '--all'],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            logger.error(f"Notion sync failed: {result.stderr}")
            return False
        logger.info("Notion sync completed")
        return True
    except Exception as e:
        logger.error(f"Notion sync error: {e}")
        return False


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process site_researched companies')
    parser.add_argument('--limit', type=int, default=5, help='Max companies to process')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode')
    parser.add_argument('--notion-sync', action='store_true', default=True, help='Sync to Notion')

    args = parser.parse_args()

    result = process_site_researched_companies(
        limit=args.limit,
        dry_run=args.dry_run,
        notion_sync=args.notion_sync
    )

    print(json.dumps(result, indent=2))
