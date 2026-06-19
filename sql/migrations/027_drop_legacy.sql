DROP TABLE IF EXISTS analysis_note_signals;
DROP TABLE IF EXISTS analysis_notes;
DROP TABLE IF EXISTS source_links;
DROP TABLE IF EXISTS dossiers_legacy;
DROP TABLE IF EXISTS signals;
DROP TABLE IF EXISTS signal_types;

-- FK constraints to signals already dropped in 026_contacts_v3.sql.
ALTER TABLE companies
    DROP COLUMN IF EXISTS last_signal_date,
    DROP COLUMN IF EXISTS last_verified,
    DROP COLUMN IF EXISTS funding_stage,
    DROP COLUMN IF EXISTS funding_amount,
    DROP COLUMN IF EXISTS funding_date,
    DROP COLUMN IF EXISTS team_size,
    DROP COLUMN IF EXISTS site_note,
    DROP COLUMN IF EXISTS website_snippet,
    DROP COLUMN IF EXISTS dm_enriched_at,
    DROP COLUMN IF EXISTS created_from_signal_id,
    DROP COLUMN IF EXISTS last_signal_id;

-- Drop the dm_enrichment partial index that referenced dm_enriched_at.
DROP INDEX IF EXISTS idx_companies_dm_enrichment;
