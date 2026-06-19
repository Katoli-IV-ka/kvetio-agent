-- Move the old markdown dossiers table out of the way.
ALTER TABLE dossiers RENAME TO dossiers_legacy;

CREATE TABLE dossiers (
    company_id UUID PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,

    -- Typed structured fields
    funding_stage       TEXT,
    funding_amount_usd  BIGINT,
    funding_date        DATE,
    team_size_estimate  TEXT,
    product_category    TEXT,
    ai_use_case         TEXT,
    icp_fit             TEXT
                        CONSTRAINT dossiers_icp_fit_check
                        CHECK (icp_fit IN ('strong', 'moderate', 'weak', 'unknown')),
    last_news_date      DATE,
    extra_facts         JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Section text summaries
    section_summaries   JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Narrative
    summary_md          TEXT,
    audit_md            TEXT,

    -- Notion binding
    notion_page_id      TEXT,
    notion_synced_at    TIMESTAMPTZ,

    -- Meta
    derived_from_model  TEXT,
    version             TEXT NOT NULL DEFAULT 'v1',
    derived_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_dossiers_icp_fit       ON dossiers (icp_fit);
CREATE INDEX idx_dossiers_funding_stage ON dossiers (funding_stage);
CREATE INDEX idx_dossiers_derived_at    ON dossiers (derived_at DESC);

CREATE TRIGGER trg_dossiers_updated_at
BEFORE UPDATE ON dossiers
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Migrate dossiers_legacy -> dossiers.
-- Typed fields stay NULL; populated on next ConclusionAgent run.
INSERT INTO dossiers (
    company_id, section_summaries, summary_md, audit_md,
    notion_page_id, version, derived_at, updated_at
)
SELECT
    company_id,
    sections,
    summary_md,
    audit_md,
    notion_page_id,
    version,
    generated_at,
    NOW()
FROM dossiers_legacy;
