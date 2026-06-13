-- Migration 009: analysis_notes — промежуточные факты этапа 4 (Analysis), по секциям.
-- Одна запись на секцию досье; версионируется. Факты + источники + confidence.
-- Применить в Supabase SQL Editor. Идемпотентный. Soft FK по company_domain.

CREATE TABLE IF NOT EXISTS analysis_notes (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_domain  TEXT NOT NULL,
    section         TEXT NOT NULL
        CHECK (section IN ('company', 'product', 'collaboration', 'financials', 'news', 'audit')),
    facts           JSONB NOT NULL DEFAULT '{}'::jsonb,
    sources         JSONB NOT NULL DEFAULT '[]'::jsonb,   -- список {url, note}
    confidence      TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high', 'medium', 'low')),
    model           TEXT,
    version         TEXT NOT NULL DEFAULT 'v1',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_domain, section, version)
);

CREATE INDEX IF NOT EXISTS idx_analysis_notes_company ON analysis_notes (company_domain);
