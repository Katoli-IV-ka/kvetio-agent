# Agent Upgrade — Phase 2 & 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Land Phase 2 (analysis depth + a Verification gate) and the remaining Phase 3 work (market_data, Monitor section re-analysis, Notion mapping) from the agent-upgrade spec. Source resolvers (arXiv/PWC/Wikidata/OpenCorporates) and the detailed analysis_section product checklist already shipped in `e6b3c81`.

**Architecture:** Deterministic checks (freshness, link-liveness) live in a new `scripts/verification.py` with thresholds in `config/verification.yaml`; the Verification agent stage runs them between Analysis and Conclusions and marks each `research_record` `verified/unverified/stale` in its `payload`. Prompts (audit synthesis, conclusions, monitor) are edited additively, preserving existing contract-test tokens. A `MarketDataResolver` (Stooq CSV) and a `GdeltNewsResolver` extend `enrichment.py`.

**Tech Stack:** Python 3.11, httpx + respx, pytest, free public APIs (stooq.com CSV, GDELT DOC), YAML config.

---

## Phase 2

### Task 1: Freshness config + `scripts/verification.py` (deterministic core)
**Files:** Create `config/verification.yaml`, `scripts/verification.py`, `tests/test_verification.py`; Modify `scripts/supabase_store.py`.

- [ ] Test (pure fns): `classify_freshness` — funding/financial record > 18mo → `stale`, ≤18mo → `fresh`; news > 12mo → `stale`. `link_status` — 404 / redirect-to-root / web.archive.org-only → `dead`, else `live`. `verify_record` combines them → `verified|unverified|stale`. Run → FAIL.
- [ ] Implement `load_thresholds()` (reads `config/verification.yaml`), `classify_freshness`, `link_status(url, client)`, `verify_record(record, client, thresholds, today)`, `run_verification(records, store, client, today)` returning `[(id, status)]` and calling `store.set_record_verification`.
- [ ] Add `SupabaseStore.set_record_verification(record_id, status)` (updates `payload->>verification`).
- [ ] Run `pytest tests/test_verification.py -q` → PASS. Commit.

### Task 2: Verification stage prompt + wiring
**Files:** Create `agents/prompts/verification_task.md`; Modify `bot/config.py`, `agents/prompts/pipeline_main_task.md`, `tests/test_routine_fire.py`, `tests/test_pipeline_prompts.py`.
- [ ] Add `"verification"` to `VALID_STAGES`; assert in a test. Run → FAIL → add → PASS.
- [ ] Write `verification_task.md` (gate before dossier: run `scripts/verification.py`, mark facts, only `verified` becomes a dossier fact). Add a contract test asserting it exists + key tokens. Insert a Verification step in `pipeline_main_task.md` between analysis and conclusions; add `verification` to the ordered stage list.
- [ ] Run `pytest tests/test_pipeline_prompts.py tests/test_routine_fire.py -q` (ignore pre-existing legacy `retroactive` failure). Commit.

### Task 3: Audit synthesis rewrite (`analysis_audit_task.md`)
- [ ] Rewrite to synthesise **money + moment + need** → narrative verdict + concrete offer angle + which ЛПР tiers to approach (reference `contacts`); for `data_partner`, a partner angle instead of a direct sale. Keep tokens `list-analysis-records`, `audit`, `продаж`. Run prompt tests. Commit.

### Task 4: Conclusions — verified-only + funding signal
- [ ] Edit `conclusions_task.md`: only `verified` facts become dossier facts; `unverified`/`stale` go into a separate "требует проверки" list; set `funding_date` (last funding/grant event) and `extra_facts.last_funding_source_url`; `data_partner` → partner angle. Keep existing tokens. Run prompt tests. Commit.

### Task 5: News dedup — `GdeltNewsResolver`
**Files:** Modify `scripts/enrichment.py`, `config/sources.yaml`, `tests/test_enrichment.py`.
- [ ] respx test: parses GDELT DOC articles into `news` records (one per article, title+url+seendate). Run → FAIL → implement `GdeltNewsResolver` (record_type `news`) + register + sources.yaml entry → PASS. Commit.

## Phase 3 (remaining)

### Task 6: `MarketDataResolver` (Stooq CSV, public companies only)
**Files:** Modify `scripts/enrichment.py`, `config/sources.yaml`, `tests/test_enrichment.py`.
- [ ] respx test: given a ticker in the company's research_records payload, fetches Stooq CSV and emits one `market_quote` record (last close + date); no ticker → `[]`. Run → FAIL → implement (reads ticker from stored records; guarded so it no-ops without a ticker) → PASS. Commit.

### Task 7: Monitor — targeted section re-analysis
- [ ] Edit `agents/prompts/monitor_task.md`: on a new funding/grant/hiring-burst signal, trigger re-analysis of only the affected sections (financials/news), not the whole company. Keep existing tokens. Run prompt tests. Commit.

### Task 8: Notion mapping of new outputs
**Files:** Modify `config/notion_mapping.yaml`; check `tests/test_notion_sync.py`.
- [ ] Add `data_partner` to the companies sync filter; add `funding_date` to the dossiers field map. Run `pytest tests/test_notion_sync.py -q`. Commit.

### Task 9: Docs
- [ ] Update `ARCHITECTURE.md`: Verification stage + status-flow position, freshness config, new resolvers, Monitor re-analysis, Notion fields. Commit.

---

## Out of scope (YAGNI / open questions)
- Paid sources (LinkedIn/Crunchbase/SimilarWeb/Apollo/Hunter).
- Wayback-diff pivot detection beyond the existing analysis_section checklist item #9.
- `company_profiles` migration.
