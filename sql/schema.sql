-- Kvetio Agent current Supabase clean-install schema.
-- This is the only active SQL schema contract for fresh environments.
-- Historical numbered migrations live under sql/migrations/ for live upgrades.
-- Last updated: 2026-06-23 (029 sales fields P0/P1; 030 P2 tables).
--
-- Table taxonomy:
--   Data: companies, contacts, dossiers
--   Process: research_records, analysis_records
--   Technical: analysis_links, dossier_links, record_types, run_logs
--
-- FK order:
--   companies -> run_logs -> record_types -> research_records -> contacts
--   -> analysis_records -> analysis_links -> dossiers -> dossier_links

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ─── companies ──────────────────────────────────────────────────────────────

CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    website TEXT NOT NULL,
    linkedin_url TEXT,
    notion_page_id TEXT,
    notion_synced_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'discovered'
        CONSTRAINT companies_status_check CHECK (status IN (
            'discovered',
            'relevant',
            'not_relevant',
            'manual_review',
            'sources_gathered',
            'analyzed',
            'dossier_ready',
            'data_partner'
        )),
    icp_segment TEXT,
    description TEXT,
    -- NewsAgent: strong news signal on a dossier_ready company flags an
    -- incremental dossier rebuild. Not a status — status still only moves forward.
    needs_refresh TIMESTAMPTZ,
    -- Firmographic fields (029)
    legal_name     TEXT,
    country        TEXT,
    hq_location    TEXT,
    founded_year   SMALLINT,
    employee_count INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_companies_status ON companies (status);
CREATE INDEX idx_companies_domain ON companies (domain);
CREATE INDEX idx_companies_segment ON companies (icp_segment);
CREATE INDEX idx_companies_manual_review
    ON companies (status)
    WHERE status = 'manual_review';
CREATE INDEX idx_companies_needs_refresh
    ON companies (needs_refresh)
    WHERE needs_refresh IS NOT NULL;
CREATE INDEX idx_companies_country
    ON companies (country)
    WHERE country IS NOT NULL;

CREATE TRIGGER trg_companies_updated_at
BEFORE UPDATE ON companies
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── run_logs ───────────────────────────────────────────────────────────────

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

CREATE INDEX idx_run_logs_task ON run_logs (task_name);
CREATE INDEX idx_run_logs_date ON run_logs (started_at DESC);

-- ─── record_types ──────────────────────────────────────────────────────────

CREATE TABLE record_types (
    code        TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    -- discovery | people | sources | monitoring | financials | crypto
    description TEXT
);

INSERT INTO record_types (code, category, description) VALUES
  ('github_repo',           'discovery',  'Company GitHub repo/org found'),
  ('hf_org',                'discovery',  'HuggingFace organization found'),
  ('hf_model',              'discovery',  'HuggingFace model found'),
  ('job_posting',           'discovery',  'Job posting referencing the company'),
  ('papers_with_code',      'discovery',  'PapersWithCode reference'),
  ('funding_announcement',  'financials', 'Funding/round announcement'),
  ('kaggle_sponsor',        'discovery',  'Kaggle competition sponsor'),
  ('scale_customer',        'discovery',  'Listed as customer of a known vendor'),
  ('wandb_run',             'discovery',  'Weights & Biases public run'),
  ('directory_listing',     'discovery',  'Found in a directory listing'),
  ('contact_found',         'people',     'A person/contact discovered for the company'),
  ('source_link',           'sources',    'A curated source URL for analysis'),
  ('news',                  'monitoring', 'News article about the company'),
  ('product_update',        'monitoring', 'Product/release update detected'),
  ('foundation_model',      'discovery',  'Company uses or develops a foundation model'),
  ('proprietary_ai',        'discovery',  'Company has proprietary AI capability'),
  ('proprietary_models',    'discovery',  'Company has proprietary model(s)'),
  -- Phase 1 (agent upgrade): financial signals, source links, partner flag.
  ('form_d',                'financials', 'SEC EDGAR Form D private-placement filing'),
  ('grant',                 'financials', 'Government research grant award (SBIR/NIH/CORDIS)'),
  ('quote',                 'financials', 'Direct quote signalling fundraising intent'),
  ('job_count',             'financials', 'Hiring-burst / open-roles count signal'),
  ('market_quote',          'financials', 'Public-market price quote (Stooq/Yahoo)'),
  ('arxiv_paper',           'sources',    'arXiv paper matching the company'),
  ('data_partner_flag',     'discovery',  'Durable marker that the company is a data provider / partner-track lead');

-- ─── research_records ──────────────────────────────────────────────────────

CREATE TABLE research_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    record_type TEXT NOT NULL REFERENCES record_types(code),
    agent TEXT,
    source TEXT NOT NULL,
    title TEXT,
    url TEXT,
    summary TEXT,
    confidence NUMERIC(3,2) NOT NULL DEFAULT 0.50
        CONSTRAINT rr_confidence_range CHECK (confidence >= 0 AND confidence <= 1),
    observed_at DATE NOT NULL,
    record_role TEXT NOT NULL DEFAULT 'evidence'
        CONSTRAINT rr_record_role_check
        CHECK (record_role IN ('primary', 'verification', 'source', 'monitor', 'evidence')),
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    raw_data JSONB DEFAULT '{}'::jsonb,
    run_id UUID REFERENCES run_logs(id),
    dedupe_key TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_rr_company_id ON research_records (company_id);
CREATE INDEX idx_rr_company_type ON research_records (company_id, record_type);
CREATE INDEX idx_rr_observed_at ON research_records (observed_at DESC);
CREATE INDEX idx_rr_type ON research_records (record_type);
CREATE INDEX idx_rr_role ON research_records (record_role);
CREATE INDEX idx_rr_company_role ON research_records (company_id, record_role);

CREATE TRIGGER trg_rr_updated_at
BEFORE UPDATE ON research_records
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── contacts ───────────────────────────────────────────────────────────────

CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id),
    contact_type TEXT NOT NULL DEFAULT 'person'
        CONSTRAINT contacts_type_check CHECK (contact_type IN ('person', 'organization')),
    name TEXT NOT NULL,
    info TEXT,
    email TEXT,
    phone TEXT,
    linkedin_url TEXT,
    x_url TEXT,
    facebook_url TEXT,
    instagram_url TEXT,
    other_channels JSONB NOT NULL DEFAULT '[]'::jsonb
        CONSTRAINT contacts_channels_array CHECK (jsonb_typeof(other_channels) = 'array'),
    discovered_from_research_record_id UUID REFERENCES research_records(id) ON DELETE SET NULL,
    -- Sales classification (029)
    tier            SMALLINT CONSTRAINT contacts_tier_check CHECK (tier BETWEEN 1 AND 3),
    role_title      TEXT,
    seniority       TEXT CONSTRAINT contacts_seniority_check CHECK (seniority IN (
                        'C-level', 'VP', 'Director', 'Manager', 'IC', 'Unknown')),
    decision_area   TEXT,
    outreach_status TEXT CONSTRAINT contacts_outreach_status_check CHECK (outreach_status IN (
                        'cold', 'contacted', 'replied', 'meeting_set',
                        'not_relevant', 'do_not_contact')),
    notion_page_id TEXT,
    notion_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_contacts_dedup
    ON contacts (company_id, contact_type, lower(name));
CREATE UNIQUE INDEX idx_contacts_dedup_upsert
    ON contacts (company_id, contact_type, name);
CREATE INDEX idx_contacts_company_id ON contacts (company_id);
CREATE INDEX idx_contacts_email ON contacts (email) WHERE email IS NOT NULL;
CREATE INDEX idx_contacts_tier ON contacts (tier) WHERE tier IS NOT NULL;
CREATE INDEX idx_contacts_outreach_status ON contacts (outreach_status) WHERE outreach_status IS NOT NULL;

CREATE TRIGGER trg_contacts_updated_at
BEFORE UPDATE ON contacts
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── analysis_records ──────────────────────────────────────────────────────

CREATE TABLE analysis_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    section TEXT NOT NULL
        CONSTRAINT ar_section_check
        CHECK (section IN ('company', 'product', 'collaboration', 'financials', 'news', 'audit')),
    facts JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(3,2) NOT NULL DEFAULT 0.50
        CONSTRAINT ar_confidence_check CHECK (confidence >= 0 AND confidence <= 1),
    model TEXT,
    version TEXT NOT NULL DEFAULT 'v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, section, version)
);

CREATE INDEX idx_ar_company ON analysis_records (company_id);

CREATE TRIGGER trg_ar_updated_at
BEFORE UPDATE ON analysis_records
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── analysis_links ────────────────────────────────────────────────────────

CREATE TABLE analysis_links (
    analysis_record_id UUID NOT NULL REFERENCES analysis_records(id) ON DELETE CASCADE,
    research_record_id UUID NOT NULL REFERENCES research_records(id) ON DELETE CASCADE,
    role TEXT NOT NULL DEFAULT 'supports'
        CONSTRAINT al_role_check CHECK (role IN ('supports', 'contradicts', 'context')),
    note TEXT,
    PRIMARY KEY (analysis_record_id, research_record_id)
);

CREATE INDEX idx_al_research_record ON analysis_links (research_record_id);

-- ─── dossiers ──────────────────────────────────────────────────────────────

CREATE TABLE dossiers (
    company_id UUID PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    funding_stage TEXT,
    funding_amount_usd BIGINT,
    funding_date DATE,
    team_size_estimate TEXT,
    product_category TEXT,
    ai_use_case TEXT,
    icp_fit TEXT
        CONSTRAINT dossiers_icp_fit_check CHECK (icp_fit IN ('strong', 'moderate', 'weak', 'unknown')),
    last_news_date DATE,
    extra_facts JSONB NOT NULL DEFAULT '{}'::jsonb,
    section_summaries JSONB NOT NULL DEFAULT '{}'::jsonb,
    -- Sales-brief fields (029)
    pain_summary            TEXT,
    outreach_hook           TEXT,
    pitch_angle             TEXT,
    why_interesting         TEXT,
    next_step               TEXT,
    entry_point_contact_id  UUID REFERENCES contacts(id) ON DELETE SET NULL,
    summary_md TEXT,
    audit_md TEXT,
    notion_page_id TEXT,
    notion_synced_at TIMESTAMPTZ,
    derived_from_model TEXT,
    version TEXT NOT NULL DEFAULT 'v1',
    derived_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_dossiers_icp_fit ON dossiers (icp_fit);
CREATE INDEX idx_dossiers_entry_contact ON dossiers (entry_point_contact_id) WHERE entry_point_contact_id IS NOT NULL;
CREATE INDEX idx_dossiers_funding_stage ON dossiers (funding_stage);
CREATE INDEX idx_dossiers_derived_at ON dossiers (derived_at DESC);

CREATE TRIGGER trg_dossiers_updated_at
BEFORE UPDATE ON dossiers
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── dossier_links ─────────────────────────────────────────────────────────

CREATE TABLE dossier_links (
    company_id UUID NOT NULL REFERENCES dossiers(company_id) ON DELETE CASCADE,
    analysis_record_id UUID NOT NULL REFERENCES analysis_records(id) ON DELETE CASCADE,
    contributed_to TEXT,
    PRIMARY KEY (company_id, analysis_record_id)
);

CREATE INDEX idx_dl_analysis_record ON dossier_links (analysis_record_id);

-- ─── funding_rounds (P2) ────────────────────────────────────────────────────
-- 1:N funding events per company. Supersedes flat dossiers.funding_* columns
-- in the long run; keep both until a future cleanup migration.

CREATE TABLE funding_rounds (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id      UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    stage           TEXT NOT NULL,
    amount_usd      BIGINT,
    announced_date  DATE,
    source_url      TEXT,
    investors       TEXT[],
    notes           TEXT,
    research_record_id UUID REFERENCES research_records(id) ON DELETE SET NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, stage, COALESCE(announced_date, '1970-01-01'))
);

CREATE INDEX idx_fr_company ON funding_rounds (company_id);
CREATE INDEX idx_fr_date    ON funding_rounds (announced_date DESC);

CREATE TRIGGER trg_fr_updated_at
BEFORE UPDATE ON funding_rounds
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── company_relations (P2) ─────────────────────────────────────────────────
-- Directional 1:N relationship between two known companies.
-- Primary use: data_partner track and vendor/customer chains.

CREATE TABLE company_relations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    from_company_id     UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    to_company_id       UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    relation_type       TEXT NOT NULL
        CONSTRAINT cr_type_check CHECK (relation_type IN (
            'data_partner', 'customer', 'supplier', 'investor', 'competitor', 'other'
        )),
    confidence          NUMERIC(3,2) NOT NULL DEFAULT 0.70
        CONSTRAINT cr_confidence_check CHECK (confidence >= 0 AND confidence <= 1),
    source_url          TEXT,
    notes               TEXT,
    research_record_id  UUID REFERENCES research_records(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (from_company_id, to_company_id, relation_type)
);

CREATE INDEX idx_cr_from ON company_relations (from_company_id);
CREATE INDEX idx_cr_to   ON company_relations (to_company_id);
CREATE INDEX idx_cr_type ON company_relations (relation_type);
