CREATE TABLE research_records (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id  UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    record_type TEXT NOT NULL REFERENCES record_types(code),
    agent       TEXT,
    source      TEXT NOT NULL,
    title       TEXT,
    url         TEXT,
    summary     TEXT,
    confidence  NUMERIC(3,2) NOT NULL DEFAULT 0.50
                CONSTRAINT rr_confidence_range CHECK (confidence >= 0 AND confidence <= 1),
    observed_at DATE NOT NULL,
    record_role TEXT NOT NULL DEFAULT 'evidence'
                CONSTRAINT rr_record_role_check
                CHECK (record_role IN ('primary', 'verification', 'source', 'monitor', 'evidence')),
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_data    JSONB          DEFAULT '{}'::jsonb,
    run_id      UUID REFERENCES run_logs(id),
    dedupe_key  TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rr_company_id    ON research_records (company_id);
CREATE INDEX idx_rr_company_type  ON research_records (company_id, record_type);
CREATE INDEX idx_rr_observed_at   ON research_records (observed_at DESC);
CREATE INDEX idx_rr_type          ON research_records (record_type);
CREATE INDEX idx_rr_role          ON research_records (record_role);
CREATE INDEX idx_rr_company_role  ON research_records (company_id, record_role);

CREATE TRIGGER trg_rr_updated_at
BEFORE UPDATE ON research_records
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- Migrate signals -> research_records (preserve all rows and IDs).
INSERT INTO research_records (
    id, company_id, record_type, agent, source, title, url, summary,
    confidence, observed_at, record_role, payload, raw_data,
    run_id, dedupe_key, created_at, updated_at
)
SELECT
    id, company_id,
    signal_type,
    agent, source, title, url, summary, confidence,
    signal_date,
    CASE
        WHEN signal_type LIKE 'primary_%'      THEN 'primary'
        WHEN signal_type LIKE 'verification_%' THEN 'verification'
        WHEN signal_type LIKE 'monitor_%'      THEN 'monitor'
        WHEN signal_type = 'source_link'       THEN 'source'
        ELSE 'evidence'
    END,
    payload, raw_data, run_id, dedupe_key, created_at, updated_at
FROM signals;
