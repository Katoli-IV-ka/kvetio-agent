CREATE TABLE analysis_records (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    section    TEXT NOT NULL
               CONSTRAINT ar_section_check
               CHECK (section IN ('company', 'product', 'collaboration',
                                  'financials', 'news', 'audit')),
    facts      JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(3,2) NOT NULL DEFAULT 0.50
               CONSTRAINT ar_confidence_check CHECK (confidence >= 0 AND confidence <= 1),
    model      TEXT,
    version    TEXT NOT NULL DEFAULT 'v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, section, version)
);

CREATE INDEX idx_ar_company ON analysis_records (company_id);

CREATE TRIGGER trg_ar_updated_at
BEFORE UPDATE ON analysis_records
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Migrate analysis_notes -> analysis_records (preserve IDs).
INSERT INTO analysis_records (
    id, company_id, section, facts, confidence, model, version,
    created_at, updated_at
)
SELECT id, company_id, section, facts, confidence, model, version,
       created_at, NOW()
FROM analysis_notes;
