# Agent Upgrade — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land Phase 1 of the agent-upgrade design spec — the `data_partner` status, new `record_types`, financial-signal resolvers (SEC EDGAR Form D, SBIR grants, GDELT funding), a GitHub commit-email contact resolver, and the wiring to promote a `contacts` stage — all free/public sources, all deterministic resolvers test-covered with mocked HTTP.

**Architecture:** Extends the existing `scripts/enrichment.py` resolver framework (Protocol-based resolvers returning link dicts; `run_enrichment` writes them as `research_records`). DB changes follow the established pattern: update `sql/schema.sql` (clean-install contract) **and** add a numbered `sql/migrations/NNN_*.sql` (live upgrade), keep `scripts/models.py` Literals in sync, and update contract tests. No new tables. No paid sources.

**Tech Stack:** Python 3.11, httpx + respx (HTTP mocking), pytest, Supabase/Postgres SQL, free public APIs (efts.sec.gov, api.www.sbir.gov, api.gdeltproject.org, api.github.com).

**Source of truth:** `docs/superpowers/specs/2026-06-21-agent-upgrade-design.md` (§5, §6, §9 Phase 1). Update `ARCHITECTURE.md` after.

---

## File Structure

- `sql/schema.sql` — add `data_partner` to companies status CHECK; add 7 `record_types` rows.
- `sql/migrations/028_phase1_data_partner_record_types.sql` — live upgrade for the above.
- `scripts/models.py` — add `data_partner` to `Status`/`ALL_STATUSES`; add new codes to `SignalType`.
- `scripts/enrichment.py` — `SecEdgarResolver`, `SbirGrantsResolver`, `GdeltFundingResolver`; `run_enrichment` honours per-link `record_type`.
- `scripts/dm_github.py` — `commit_emails_for_org` helper (GitHub commit author emails).
- `config/sources.yaml` — enable `sec_edgar`, `gov_grants`, `gdelt` financial resolvers.
- `bot/config.py` — add `contacts` to `VALID_STAGES` + `ENRICH_DEFAULT_STAGES`.
- Tests: `tests/test_enrichment.py`, `tests/test_migrations.py`, `tests/test_models_signals.py`, `tests/test_dm_github.py`, `tests/test_sources_config.py`.
- Prompts (additive): `agents/prompts/relevance_task.md` (data_partner tagging + durable flag), `agents/prompts/dm_enrich_task.md` (tier + reasoning in `contacts.info`).

---

## Task 1: DB — `data_partner` status + new `record_types`

**Files:**
- Modify: `sql/schema.sql`
- Create: `sql/migrations/028_phase1_data_partner_record_types.sql`
- Modify: `scripts/models.py`
- Test: `tests/test_migrations.py`, `tests/test_models_signals.py`

- [ ] **Step 1:** Add a contract test to `tests/test_migrations.py` asserting `'data_partner'` appears in the companies status CHECK and the 7 new record_type codes appear in schema.sql. Run it — expect FAIL.
- [ ] **Step 2:** Add `'data_partner'` to the `companies_status_check` list in `sql/schema.sql`, and add the 7 `record_types` INSERT rows: `form_d`/`grant`/`quote`/`job_count`/`market_quote` (category `financials`), `arxiv_paper` (`sources`), `data_partner_flag` (`discovery`).
- [ ] **Step 3:** Update `scripts/models.py`: append `"data_partner"` to `Status` Literal and `ALL_STATUSES`; append the 7 codes to `SignalType`.
- [ ] **Step 4:** Create `sql/migrations/028_*.sql`: `ALTER TABLE companies DROP CONSTRAINT companies_status_check, ADD CONSTRAINT ... CHECK (...'data_partner')`; `INSERT INTO record_types ... ON CONFLICT (code) DO NOTHING`.
- [ ] **Step 5:** Run `pytest tests/test_migrations.py tests/test_models_signals.py -q` — expect PASS. Commit.

## Task 2: `run_enrichment` honours per-link `record_type`

**Files:** Modify `scripts/enrichment.py`; Test `tests/test_enrichment.py`

- [ ] **Step 1:** Add test: a fake resolver returns a link with `record_type="form_d"`; assert the written `ResearchRecord.record_type == "form_d"` and `record_type` is not duplicated into payload. Run — expect FAIL.
- [ ] **Step 2:** In `run_enrichment`, change the hardcoded `record_type="source_link"` to `record_type=link.get("record_type", "source_link")`, and add `"record_type"` to the payload-exclusion set.
- [ ] **Step 3:** Run `pytest tests/test_enrichment.py -q` — expect PASS. Commit.

## Task 3: Financial resolvers (SEC EDGAR Form D, SBIR grants, GDELT funding)

**Files:** Modify `scripts/enrichment.py`, `config/sources.yaml`; Test `tests/test_enrichment.py`

Each resolver follows the existing pattern (kind, enabled, `resolve()` returning dict|list|None; name search via `_company_query_name`; low/medium confidence; raw fields in payload). Each emits its own `record_type` (`form_d`, `grant`, `funding_announcement`). Register in `RESOLVERS`. Add respx tests mirroring the arXiv/PWC tests. Add `sec_edgar`/`gov_grants`/`gdelt` entries to `config/sources.yaml`.

- [ ] **Step 1:** Write respx tests for all three (hit + empty cases). Run — expect FAIL (resolvers undefined).
- [ ] **Step 2:** Implement the three resolver classes + register them. Add sources.yaml entries.
- [ ] **Step 3:** Run `pytest tests/test_enrichment.py tests/test_sources_config.py -q` — expect PASS. Commit.

## Task 4: GitHub commit-email contact resolver

**Files:** Modify `scripts/dm_github.py`; Test `tests/test_dm_github.py`

- [ ] **Step 1:** Write test: given a mocked GitHub commits API response, `commit_emails_for_org(org, client)` returns deduped `(name, email)` pairs, skipping `noreply.github.com` addresses. Run — expect FAIL.
- [ ] **Step 2:** Implement the helper using the org's public repos → recent commits → `commit.author.{name,email}`.
- [ ] **Step 3:** Run `pytest tests/test_dm_github.py -q` — expect PASS. Commit.

## Task 5: Promote `contacts` stage + Relevance `data_partner` + tier-in-info

**Files:** Modify `bot/config.py`, `agents/prompts/relevance_task.md`, `agents/prompts/dm_enrich_task.md`

- [ ] **Step 1:** Add `"contacts"` to `VALID_STAGES` and after `enrichment` in `ENRICH_DEFAULT_STAGES`. Run bot config tests — expect PASS.
- [ ] **Step 2:** Edit `relevance_task.md`: add the `data_partner` outcome (data-provider/“competitor” → `data_partner`, not `not_relevant`) and the durable `data_partner_flag` research_record; downstream selects `relevant` AND `data_partner`.
- [ ] **Step 3:** Edit `dm_enrich_task.md`: instruct writing tier (1–3) + one-line “why a dataset DM” reasoning into `contacts.info`; process `relevant` AND `data_partner`.
- [ ] **Step 4:** Run `pytest tests/test_pipeline_prompts.py -q` (ignore the pre-existing legacy `retroactive_pipeline_task.md` failure). Commit.

## Task 6: Docs

- [ ] Update `ARCHITECTURE.md`: `data_partner` status, new record_types, new resolvers, `contacts` stage. Commit.

---

## Out of scope (later phases)

- Phase 2: Verification stage, freshness config, full `analysis_section_task.md` rewrite, news dedup.
- Phase 3: already-landed company/product resolvers (committed `e6b3c81`); `market_data`; Monitor section re-analysis; Notion mapping of new outputs.
- arXiv author-email contact resolver (flaky; deferred).
