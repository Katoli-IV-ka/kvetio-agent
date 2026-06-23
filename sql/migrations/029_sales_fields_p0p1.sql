-- 029_sales_fields_p0p1.sql
-- Sales-pipeline fields: P0 and P1 additions derived from the dossier blueprint
-- (docs/PIPELINE-SPEC-2026-06-23.md).
-- Safe to run repeatedly — all ADD COLUMN / CREATE INDEX use IF NOT EXISTS.

-- ─── dossiers: sales-brief fields ───────────────────────────────────────────
-- pain_summary     : free-text narrative of the company's data pain / specificity,
--                    derived from product description. Richer than a tag list.
-- outreach_hook    : one specific, fresh, personal event to open the first message
--                    (e.g. "spoke at CVPR 2025 about annotation bottlenecks").
-- pitch_angle      : the single most resonant angle for our pitch to THIS company.
-- why_interesting  : internal note — why we think they're a strong lead.
-- next_step        : last agreed / planned next action (free text).
-- entry_point_contact_id : FK to the best contact to reach out to first.

ALTER TABLE dossiers
    ADD COLUMN IF NOT EXISTS pain_summary           TEXT,
    ADD COLUMN IF NOT EXISTS outreach_hook          TEXT,
    ADD COLUMN IF NOT EXISTS pitch_angle            TEXT,
    ADD COLUMN IF NOT EXISTS why_interesting        TEXT,
    ADD COLUMN IF NOT EXISTS next_step              TEXT,
    ADD COLUMN IF NOT EXISTS entry_point_contact_id UUID
        REFERENCES contacts(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_dossiers_entry_contact
    ON dossiers (entry_point_contact_id)
    WHERE entry_point_contact_id IS NOT NULL;

-- ─── companies: firmographic fields ─────────────────────────────────────────
-- company_size  : approximate headcount range as a label, e.g. "1-10", "11-50",
--                "51-200", "201-500", "501-1000", "1000+". TEXT, not INT —
--                LinkedIn/sources give ranges, not exact numbers.
-- country       : ISO country code or full name (e.g. "US", "Germany")
-- hq_location   : city / region (e.g. "San Francisco, CA")
-- founded_year  : approximate year of founding
-- legal_name    : registered legal entity name if different from trading name

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS legal_name    TEXT,
    ADD COLUMN IF NOT EXISTS country       TEXT,
    ADD COLUMN IF NOT EXISTS hq_location   TEXT,
    ADD COLUMN IF NOT EXISTS founded_year  SMALLINT,
    ADD COLUMN IF NOT EXISTS company_size  TEXT;  -- e.g. "11-50", "51-200"

CREATE INDEX IF NOT EXISTS idx_companies_country
    ON companies (country)
    WHERE country IS NOT NULL;
