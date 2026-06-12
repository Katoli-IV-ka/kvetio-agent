-- Migration 007: dm_enriched_at on companies.
-- Tracks when dm_enrich_task last ran for a company.
-- Idempotent: IF NOT EXISTS.

ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS dm_enriched_at TIMESTAMPTZ;

COMMENT ON COLUMN companies.dm_enriched_at IS
  'Timestamp of the last dm_enrich_task run for this company. '
  'NULL means not enriched yet. Used for dm_enrich_task queue selection.';

CREATE INDEX IF NOT EXISTS idx_companies_dm_enrichment
  ON companies (status, dm_enriched_at)
  WHERE status = 'enriched';
