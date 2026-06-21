-- NewsAgent: needs_refresh flag for incremental dossier rebuilds.
-- needs_refresh is NOT a status. Status still only moves forward. The flag marks
-- a dossier_ready company that got a strong news signal and whose dossier should
-- be incrementally re-built (news + financials sections).

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS needs_refresh TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_companies_needs_refresh
    ON companies (needs_refresh)
    WHERE needs_refresh IS NOT NULL;
