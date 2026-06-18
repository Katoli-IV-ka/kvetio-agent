-- Kvetio Agent current Supabase baseline schema.
-- This is the only active SQL schema contract.
-- Historical test-era migrations were intentionally removed on 2026-06-18.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    website TEXT NOT NULL,
    linkedin_url TEXT,
    notion_page_id TEXT,
    status TEXT NOT NULL DEFAULT 'discovered'
        CHECK (status IN (
            'discovered',
            'relevant',
            'not_relevant',
            'manual_review',
            'sources_gathered',
            'analyzed',
            'dossier_ready'
        )),
    last_signal_date DATE,
    last_verified DATE,
    icp_segment TEXT,
    funding_stage TEXT,
    funding_amount TEXT,
    funding_date DATE,
    team_size TEXT,
    site_note TEXT,
    website_snippet TEXT,
    description TEXT,
    dm_enriched_at TIMESTAMPTZ,
    notion_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_companies_status ON companies (status);
CREATE INDEX idx_companies_domain ON companies (domain);
CREATE INDEX idx_companies_manual_review
    ON companies (status)
    WHERE status = 'manual_review';
CREATE INDEX idx_companies_dm_enrichment
    ON companies (status, dm_enriched_at)
    WHERE status IN ('relevant', 'sources_gathered', 'analyzed', 'dossier_ready');

DROP TRIGGER IF EXISTS trg_companies_updated_at ON companies;
CREATE TRIGGER trg_companies_updated_at
BEFORE UPDATE ON companies
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE signals (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    signal_type TEXT NOT NULL,
    company_name TEXT NOT NULL,
    domain TEXT,
    normalized_domain TEXT,
    linkedin_url TEXT,
    evidence_url TEXT UNIQUE NOT NULL,
    signal_date DATE NOT NULL,
    confidence TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high', 'medium', 'low')),
    parser_version TEXT,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_signals_normalized_domain ON signals (normalized_domain);
CREATE INDEX idx_signals_signal_date ON signals (signal_date DESC);
CREATE INDEX idx_signals_signal_type ON signals (signal_type);

CREATE TABLE run_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    companies_found INTEGER NOT NULL DEFAULT 0,
    companies_enriched INTEGER NOT NULL DEFAULT 0,
    errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes TEXT
);

CREATE INDEX idx_run_logs_task_name ON run_logs (task_name);
CREATE INDEX idx_run_logs_started_at ON run_logs (started_at DESC);

CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id),

    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL DEFAULT '',
    info TEXT,

    email TEXT,
    phone TEXT,
    linkedin_url TEXT,
    x_url TEXT,
    facebook_url TEXT,
    instagram_url TEXT,

    other_channels JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(other_channels) = 'array'),

    notion_page_id TEXT,
    notion_synced_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_contacts_company_name
    ON contacts (company_id, lower(first_name), lower(last_name));
CREATE INDEX idx_contacts_company_id
    ON contacts (company_id);
CREATE INDEX idx_contacts_email
    ON contacts (email)
    WHERE email IS NOT NULL;

DROP TRIGGER IF EXISTS trg_contacts_updated_at ON contacts;
CREATE TRIGGER trg_contacts_updated_at
BEFORE UPDATE ON contacts
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE source_links (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_domain TEXT NOT NULL,
    kind TEXT NOT NULL,
    url TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'unknown',
    confidence TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high', 'medium', 'low')),
    found_via TEXT,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_domain, kind, url)
);

CREATE INDEX idx_source_links_company ON source_links (company_domain);
CREATE INDEX idx_source_links_kind ON source_links (kind);

CREATE TABLE analysis_notes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_domain TEXT NOT NULL,
    section TEXT NOT NULL
        CHECK (section IN ('company', 'product', 'collaboration', 'financials', 'news', 'audit')),
    facts JSONB NOT NULL DEFAULT '{}'::jsonb,
    sources JSONB NOT NULL DEFAULT '[]'::jsonb,
    confidence TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high', 'medium', 'low')),
    model TEXT,
    version TEXT NOT NULL DEFAULT 'v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_domain, section, version)
);

CREATE INDEX idx_analysis_notes_company ON analysis_notes (company_domain);

CREATE TABLE dossiers (
    company_domain TEXT PRIMARY KEY,
    summary_md TEXT,
    sections JSONB NOT NULL DEFAULT '{}'::jsonb,
    audit_md TEXT,
    table_fields JSONB NOT NULL DEFAULT '{}'::jsonb,
    version TEXT NOT NULL DEFAULT 'v1',
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
