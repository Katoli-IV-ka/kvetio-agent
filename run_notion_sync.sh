#!/bin/bash
# Notion synchronization for 5 analyzed companies

set -e

echo "🔄 Notion Synchronization"
echo "=========================="
echo ""
echo "Syncing 5 companies to Notion..."

# Sync companies
echo "1. Syncing companies..."
python -m scripts.notion_sync --entity companies --all

echo ""
echo "2. Syncing dossiers..."
python -m scripts.notion_sync --entity dossiers

echo ""
echo "✓ Notion synchronization complete!"
echo ""
echo "Companies synced:"
echo "  - Poolside (poolside.ai)"
echo "  - Safe Superintelligence (ssi.inc)"
echo "  - Bioptimus (bioptimus.com)"
echo "  - Sarvam AI (sarvam.ai)"
echo "  - Thinking Machines Lab (thinkingmachines.ai)"
