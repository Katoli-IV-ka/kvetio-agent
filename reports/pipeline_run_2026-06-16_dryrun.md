# Pipeline Dry-Run Report
**2026-06-16 | agriculture-ai segment**

## Run Parameters
```json
{
  "segments": ["agriculture-ai"],
  "limit": 5,
  "stages": ["discovery", "relevance", "enrichment", "analysis"],
  "dry_run": true,
  "notion_sync": false
}
```

## Configuration Analysis

### Requested Segment: agriculture-ai
- Status: ✓ Valid (defined in `config/icp.yaml`)
- ICP Definition: Компании, применяющие ML/CV для точного земледелия, анализа растений
- Min team size: 3
- Funding stages: Seed, Series A, Series B, Series C
- Geographies: US, EU, UK, IL, AU, IN, BR

### Source Coverage for agriculture-ai
**Critical Finding: NO SOURCE MAPPINGS EXIST**

| Source | Enabled | Supported for agriculture-ai | Action |
|---|---|---|---|
| huggingface | ✓ Yes | ✗ NO - pipeline_tag_map missing | Would skip or use generic search |
| github | ✓ Yes | ✗ NO - not in supported_segments | SKIP |
| yc_browser | ✓ Yes | ✗ NO - not in supported_segments | SKIP |
| greenhouse | ✓ Yes | ✗ NO - not in supported_segments | SKIP |
| contact_page | ✓ Yes | ✓ No segment restrictions | AVAILABLE |
| contact_enricher | ✓ Yes | ✓ No segment restrictions | AVAILABLE |

## Dry-Run Execution Simulation

### Stage 1: DISCOVERY
**Status: BLOCKED** — agriculture-ai has no configured sources.

To proceed, the following changes would be needed:

**Option 1: Add agriculture-ai to huggingface tags**
```yaml
huggingface:
  pipeline_tag_map:
    agriculture-ai:
      - image-segmentation          # crop disease detection
      - object-detection             # plant health monitoring
      - image-classification         # soil/plant analysis
      - depth-estimation            # drone imagery processing
```

**Option 2: Add agriculture-ai to yc_browser/github supported_segments**
```yaml
github:
  supported_segments:
    - agriculture-ai
yc_browser:
  supported_segments:
    - agriculture-ai
```

**Current Behavior (without fixes):**
- huggingface: No tags to search → 0 companies found
- github: Skipped (unsupported segment)
- yc_browser: Skipped (unsupported segment)  
- greenhouse: Skipped (unsupported segment)
- Result: 0 companies discovered

### Stage 2: RELEVANCE (Simulated)
**Status: SKIPPED** — No companies discovered in Stage 1

**What would happen if companies existed:**
- Query: `SELECT ... FROM companies WHERE status='discovered' AND icp_segment='agriculture-ai' LIMIT 5`
- For each company: Fetch website, verify AI/ML model training, check for hiring signals
- Decisions: relevant | not_relevant | manual_review
- Dry-run mode: Would show decisions without updating status

### Stage 3: ENRICHMENT (Simulated)
**Status: SKIPPED** — No companies passed relevance filter

**What would happen if companies existed:**
- Query: `SELECT ... FROM companies WHERE status='qualified' AND icp_segment='agriculture-ai' LIMIT 5`
- For each company: Run enrichment resolvers (GitHub org, Wayback, HuggingFace)
- Collect source links for analysis
- Dry-run mode: Would show which sources would be queried, not write to DB

### Stage 4: ANALYSIS (Simulated)
**Status: SKIPPED** — No companies had sources gathered

**What would happen if companies existed:**
- Query: `SELECT ... FROM companies WHERE status='sources_gathered' AND icp_segment='agriculture-ai' LIMIT 5`
- For each company: Spawn 5 parallel sub-agents (company, product, collaboration, financials, news)
- Collect analysis notes and audit
- Dry-run mode: Would show what sub-agents would be created, not write analysis notes

## Database Changes Summary
**Dry-run mode: NO CHANGES TO DATABASE**

### Would-Be Changes (if sources were configured):
```
companies table:
  - 0 new rows inserted (discovery stage blocked)
  
signals table:
  - 0 new rows (depends on discovery)
  
source_links table:
  - 0 new rows (depends on enrichment)

run_logs table:
  - 1 entry for pipeline execution attempt
```

## Issues & Recommendations

### 🔴 Critical Issue
**agriculture-ai segment defined but not integrated with discovery sources**

Recommendation:
1. Update `config/sources.yaml` to add agriculture-ai pipeline tags to huggingface
2. Or add agriculture-ai to supported_segments for github/yc_browser if these sources have relevant data
3. Re-run pipeline with updated configuration

### ✅ Suggestions for agriculture-ai sources
Based on ICP keywords (precision agriculture, crop disease, yield prediction, satellite imagery):

**Huggingface tags to add:**
- `image-segmentation` (crop field segmentation)
- `object-detection` (plant/pest/disease detection)
- `image-classification` (crop/soil classification)
- `depth-estimation` (elevation maps from drone imagery)

**GitHub search keywords:**
- `precision agriculture`, `crop disease`, `yield prediction`, `agronomy`

**Y Combinator batch:** Check agriculture-related startups in YC directories

## Final Statistics
```json
{
  "task": "pipeline",
  "segments": ["agriculture-ai"],
  "stages": ["discovery", "relevance", "enrichment", "analysis"],
  "limit": 5,
  "dry_run": true,
  "notion_sync": false,
  "found": 0,
  "relevant": 0,
  "qualified": 0,
  "sources_gathered": 0,
  "analyzed": 0,
  "dossier_ready": 0,
  "skipped": 4,
  "errors": 1,
  "error_type": "missing_source_mappings",
  "execution_time": "~2s",
  "status": "BLOCKED"
}
```

## Conclusion
The pipeline executed successfully in dry-run mode but discovered a configuration issue:
**agriculture-ai requires source mappings before discovery can begin.**

Update config/sources.yaml and retry.

---
*Report generated: 2026-06-16 13:58 UTC*
*Environment: Dry-run mode (read-only, no DB writes)*
