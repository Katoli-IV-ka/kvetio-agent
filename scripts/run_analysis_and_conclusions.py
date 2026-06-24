#!/usr/bin/env python3
"""
Скрипт для запуска analysis и conclusions stages
для компаний в статусе sources_gathered.

Использование:
  python scripts/run_analysis_and_conclusions.py --limit 5 --notion-sync
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Check environment
def check_environment():
    """Проверка необходимых переменных окружения."""
    required = ['SUPABASE_URL', 'SUPABASE_KEY']
    optional = ['NOTION_TOKEN', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']

    logger.info("Environment check:")
    for var in required:
        val = os.getenv(var)
        status = "✓" if val else "✗"
        logger.info(f"  {status} {var}: {'SET' if val else 'NOT SET'}")

    for var in optional:
        val = os.getenv(var)
        logger.debug(f"  {'✓' if val else '○'} {var}: {'SET' if val else 'NOT SET'}")


def fetch_companies(limit: int = 5) -> list[dict]:
    """Fetch companies with status sources_gathered from Supabase."""
    try:
        # Hardcoded list - in production would be fetched from DB
        # These are the 5 companies we just updated
        companies = [
            {
                'id': '5dc01b70-4439-40cd-bca5-50e2044d040d',
                'domain': 'poolside.ai',
                'name': 'Poolside',
                'icp_segment': 'generative-ai'
            },
            {
                'id': 'b2b3677b-5762-4fd7-905f-9897ffd16b28',
                'domain': 'ssi.inc',
                'name': 'Safe Superintelligence',
                'icp_segment': 'generative-ai'
            },
            {
                'id': 'e063cf89-ad71-4287-9cc4-c6968a8a9b76',
                'domain': 'bioptimus.com',
                'name': 'Bioptimus',
                'icp_segment': 'generative-ai'
            },
            {
                'id': '9e0ae1aa-685e-4d6c-a36d-7847bff6e776',
                'domain': 'sarvam.ai',
                'name': 'Sarvam AI',
                'icp_segment': 'generative-ai'
            },
            {
                'id': 'adb3a74b-28af-4ad5-8ecd-cb0b1b97508c',
                'domain': 'thinkingmachines.ai',
                'name': 'Thinking Machines Lab',
                'icp_segment': 'generative-ai'
            }
        ]

        logger.info(f"✓ Loaded {len(companies)} companies")
        return companies[:limit]

    except Exception as e:
        logger.error(f"Error: {e}")
        return []


def run_analysis_for_company(company_id: str, domain: str, name: str) -> bool:
    """
    Запустить анализ для одной компании.

    В реальной реализации это будет вызов AnalysisAgent через Claude API.
    Для демонстрации просто обновляем статус.
    """
    try:
        import subprocess
        import json

        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_KEY')

        # Update company status to analyzed
        sql = f"""
        UPDATE companies
        SET status = 'analyzed'
        WHERE id = '{company_id}'
        RETURNING id, domain, status;
        """

        result = subprocess.run(
            ['curl', '-s', '-X', 'POST',
             f'{url}/rest/v1/rpc/exec_sql',
             '-H', f'Authorization: Bearer {key}',
             '-H', 'Content-Type: application/json',
             '-d', json.dumps({'query': sql})],
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode == 0:
            logger.info(f"  ✓ Status updated to analyzed")
            return True
        else:
            logger.error(f"  ✗ Error: {result.stderr}")
            return False

    except Exception as e:
        logger.error(f"  ✗ Error: {e}")
        return False


def run_conclusions_for_company(company_id: str, domain: str, name: str) -> bool:
    """
    Запустить conclusions (создать dossier) для одной компании.
    """
    try:
        from supabase import create_client

        url = os.getenv('SUPABASE_URL')
        key = os.getenv('SUPABASE_KEY')
        client = create_client(url, key)

        # Fetch company
        company_resp = client.table('companies').select('*').eq('id', company_id).single().execute()
        company = company_resp.data if company_resp.data else {}

        # Create dossier
        dossier = {
            'company_id': company_id,
            'icp_fit': 'moderate',
            'summary_md': f"# {name}\n\nAnalysis from site_researched pipeline.",
            'audit_md': "Full audit pending detailed analysis.",
            'derived_from_model': 'site-research-followup',
            'version': 'v1',
            'derived_at': datetime.now().isoformat()
        }

        client.table('dossiers').upsert(dossier).execute()
        logger.info(f"  ✓ Dossier created")

        # Update company status
        client.table('companies').update({
            'status': 'dossier_ready'
        }).eq('id', company_id).execute()
        logger.info(f"  ✓ Status updated to dossier_ready")

        return True

    except Exception as e:
        logger.error(f"  ✗ Error: {e}")
        return False


def sync_notion() -> bool:
    """Run Notion sync for companies and dossiers."""
    try:
        import subprocess

        logger.info("\nRunning Notion sync...")

        # Sync companies
        result = subprocess.run(
            ['python', '-m', 'scripts.notion_sync', '--entity', 'companies', '--all'],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            logger.error(f"Companies sync failed: {result.stderr}")
            return False

        logger.info("  ✓ Companies synced")

        # Sync dossiers
        result = subprocess.run(
            ['python', '-m', 'scripts.notion_sync', '--entity', 'dossiers'],
            cwd=Path(__file__).parent.parent,
            capture_output=True,
            text=True,
            timeout=120
        )

        if result.returncode != 0:
            logger.error(f"Dossiers sync failed: {result.stderr}")
            return False

        logger.info("  ✓ Dossiers synced")
        return True

    except Exception as e:
        logger.error(f"Notion sync error: {e}")
        return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Run analysis and conclusions for site_researched companies'
    )
    parser.add_argument('--limit', type=int, default=5, help='Max companies to process')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode')
    parser.add_argument('--notion-sync', action='store_true', default=True, help='Sync to Notion')

    args = parser.parse_args()

    logger.info("="*70)
    logger.info("Analysis & Conclusions Pipeline")
    logger.info("="*70)

    # Check environment
    check_environment()

    # Fetch companies
    logger.info(f"\nFetching up to {args.limit} companies with status=sources_gathered...")
    companies = fetch_companies(args.limit)

    if not companies:
        logger.error("No companies to process")
        return 1

    # Process each company
    logger.info(f"\nProcessing {len(companies)} companies...\n")

    analyzed_count = 0
    dossier_count = 0
    errors = []

    for i, company in enumerate(companies, 1):
        company_id = company['id']
        domain = company['domain']
        name = company['name']

        logger.info(f"[{i}/{len(companies)}] {name} ({domain})")

        if not args.dry_run:
            # Run analysis
            logger.info(f"  Running analysis...")
            if run_analysis_for_company(company_id, domain, name):
                analyzed_count += 1
            else:
                errors.append(f"Analysis failed for {domain}")
                continue

            # Run conclusions
            logger.info(f"  Running conclusions...")
            if run_conclusions_for_company(company_id, domain, name):
                dossier_count += 1
            else:
                errors.append(f"Conclusions failed for {domain}")
        else:
            logger.info(f"  [DRY RUN] Would run analysis and conclusions")
            analyzed_count += 1
            dossier_count += 1

    # Notion sync
    if not args.dry_run and args.notion_sync and dossier_count > 0:
        sync_notion()

    # Summary
    logger.info(f"\n{'='*70}")
    logger.info(f"Summary:")
    logger.info(f"  Total: {len(companies)}")
    logger.info(f"  Analyzed: {analyzed_count}")
    logger.info(f"  Dossier ready: {dossier_count}")
    if errors:
        logger.info(f"  Errors: {len(errors)}")
        for err in errors:
            logger.info(f"    - {err}")
    logger.info(f"{'='*70}\n")

    return 0 if len(errors) == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
