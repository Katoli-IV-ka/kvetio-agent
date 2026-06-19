CREATE TABLE dossier_links (
    company_id          UUID NOT NULL REFERENCES dossiers(company_id) ON DELETE CASCADE,
    analysis_record_id  UUID NOT NULL REFERENCES analysis_records(id) ON DELETE CASCADE,
    contributed_to      TEXT,
    PRIMARY KEY (company_id, analysis_record_id)
);

CREATE INDEX idx_dl_analysis_record ON dossier_links (analysis_record_id);
