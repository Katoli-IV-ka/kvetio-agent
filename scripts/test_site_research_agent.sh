#!/bin/bash
# Test script for SiteResearchAgent (Relevant Track)
# This script validates the pipeline without writing to the database

set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo "=========================================="
echo "SiteResearchAgent (Relevant Track) Test"
echo "=========================================="

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Check Python
echo -e "${YELLOW}[1/5]${NC} Checking Python environment..."
if ! command -v python &> /dev/null; then
    echo -e "${RED}ERROR: Python not found${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Python available${NC}"

# Check required Python packages
echo -e "${YELLOW}[2/5]${NC} Checking Python packages..."
python -c "import supabase, httpx" 2>/dev/null && echo -e "${GREEN}✓ Dependencies available${NC}" || {
    echo -e "${YELLOW}Installing dependencies...${NC}"
    pip install -q supabase httpx python-dotenv beautifulsoup4
    echo -e "${GREEN}✓ Dependencies installed${NC}"
}

# Check scripts exist
echo -e "${YELLOW}[3/5]${NC} Checking required scripts..."
for script in scripts/site_fetch.py scripts/site_research_agent_relevant_track.py scripts/contacts_store.py scripts/research_notes_store.py; do
    if [ ! -f "$script" ]; then
        echo -e "${RED}ERROR: $script not found${NC}"
        exit 1
    fi
done
echo -e "${GREEN}✓ All scripts present${NC}"

# Test dry-run with 3 companies
echo -e "${YELLOW}[4/5]${NC} Running dry-run test (3 companies)..."
if python scripts/site_research_agent_relevant_track.py --limit 3 --dry-run > /tmp/test_output.log 2>&1; then
    echo -e "${GREEN}✓ Dry-run completed successfully${NC}"
    
    # Check output
    if grep -q "Founded years updated:" /tmp/test_output.log; then
        echo -e "${GREEN}✓ Data extraction verified${NC}"
    fi
else
    echo -e "${RED}ERROR: Dry-run failed${NC}"
    cat /tmp/test_output.log
    exit 1
fi

# Show test results
echo -e "${YELLOW}[5/5]${NC} Test Results Summary"
echo "---"
grep -E "^Companies processed:|^Total contacts|^Total product|^Founded years|^Countries" /tmp/test_output.log || true
echo "---"

echo ""
echo -e "${GREEN}========== TEST PASSED ==========${NC}"
echo ""
echo "Next steps to execute the full task:"
echo "1. Get the service_role key from Supabase Dashboard"
echo "2. Set: export SUPABASE_KEY='eyJ...'"
echo "3. Run: python scripts/site_research_agent_relevant_track.py --limit 20"
echo ""
