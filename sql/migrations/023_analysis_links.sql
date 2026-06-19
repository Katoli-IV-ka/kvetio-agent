CREATE TABLE analysis_links (
    analysis_record_id UUID NOT NULL REFERENCES analysis_records(id)  ON DELETE CASCADE,
    research_record_id UUID NOT NULL REFERENCES research_records(id)  ON DELETE CASCADE,
    role               TEXT NOT NULL DEFAULT 'supports'
                       CONSTRAINT al_role_check
                       CHECK (role IN ('supports', 'contradicts', 'context')),
    note               TEXT,
    PRIMARY KEY (analysis_record_id, research_record_id)
);

CREATE INDEX idx_al_research_record ON analysis_links (research_record_id);

-- Migrate analysis_note_signals -> analysis_links.
-- analysis_note_id and signal_id map directly because IDs were preserved.
INSERT INTO analysis_links (
    analysis_record_id, research_record_id, role, note
)
SELECT analysis_note_id, signal_id, role, note
FROM analysis_note_signals;
