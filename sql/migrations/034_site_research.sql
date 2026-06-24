-- 034_site_research.sql
-- Pipeline "site research": new statuses, category select, and research_notes.
-- Existing research_records stay unchanged.

BEGIN;

ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_status_check;
ALTER TABLE companies ADD CONSTRAINT companies_status_check CHECK (status IN (
    'discovered',
    'relevant',
    'not_relevant',
    'manual_review',
    'sources_gathered',
    'analyzed',
    'dossier_ready',
    'data_partner',
    'new',
    'site_researched'
));

CREATE TABLE IF NOT EXISTS category_options (
    value      TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO category_options (value, label) VALUES
    ('data_provider',     'Data provider'),
    ('product_builder',   'Builds product'),
    ('llm_wrapper',       'LLM wrapper'),
    ('big_tech_ai',       'Big tech with AI product'),
    ('non_tech_product',  'Non-tech, builds own product'),
    ('startup_own_model', 'Startup building own model'),
    ('closed_project',    'Closed project')
ON CONFLICT (value) DO NOTHING;

ALTER TABLE companies ADD COLUMN IF NOT EXISTS category TEXT
    REFERENCES category_options(value);

CREATE TABLE IF NOT EXISTS research_notes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id   UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    note_type    TEXT NOT NULL CONSTRAINT research_notes_type_check CHECK (
                     note_type IN ('product', 'press_release', 'cooperative', 'finance')),
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_url   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, note_type, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_research_notes_company ON research_notes (company_id);

COMMIT;
