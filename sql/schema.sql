-- Kvetio Agent current Supabase baseline schema.
-- This is the only active SQL schema contract.
-- Historical test-era migrations were intentionally removed on 2026-06-18.
-- Last updated: 2026-06-19 (migration 018 — constraints + index cleanup).
--
-- Table order matters for FK resolution:
--   companies → run_logs → signal_types → signals
--   → [provenance FKs on companies] → contacts → source_links
--   → analysis_notes → analysis_note_signals → dossiers

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ─── companies ──────────────────────────────────────────────────────────────
-- Provenance FKs (created_from_signal_id, last_signal_id) added via
-- ALTER TABLE below, after signals is created.

CREATE TABLE companies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    website TEXT NOT NULL,
    linkedin_url TEXT,
    notion_page_id TEXT,
    status TEXT NOT NULL DEFAULT 'discovered'
        CONSTRAINT companies_status_check CHECK (status IN (
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
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_from_signal_id UUID,
    last_signal_id         UUID
);

CREATE INDEX idx_companies_status ON companies (status);
CREATE INDEX idx_companies_domain ON companies (domain);
CREATE INDEX idx_companies_segment ON companies (icp_segment);
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

-- ─── run_logs ───────────────────────────────────────────────────────────────
-- Defined before signals so signals.run_id FK resolves correctly.

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

-- ─── signal_types ───────────────────────────────────────────────────────────
-- Governed vocabulary; add new signal categories here, not via ad-hoc migration.

CREATE TABLE signal_types (
    code        TEXT PRIMARY KEY,
    category    TEXT NOT NULL,          -- discovery | people | sources | monitoring | financials
    description TEXT
);

INSERT INTO signal_types (code, category, description) VALUES
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
  ('proprietary_models',    'discovery',  'Company has proprietary model(s)');

-- ─── signals ────────────────────────────────────────────────────────────────

CREATE TABLE signals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id  UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    signal_type TEXT NOT NULL REFERENCES signal_types(code),
    agent       TEXT,                                -- producer: discovery, source_expansion, dm_enrich...
    source      TEXT NOT NULL,                       -- github, huggingface, web, apollo...
    title       TEXT,                                -- short human-readable label
    url         TEXT,                                -- evidence link, NOT unique
    summary     TEXT,                                -- short description of the finding
    confidence  NUMERIC(3,2) NOT NULL DEFAULT 0.50
                CONSTRAINT signals_confidence_range CHECK (confidence >= 0 AND confidence <= 1),
    signal_date DATE NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,  -- structured extracted fields
    raw_data    JSONB DEFAULT '{}'::jsonb,           -- optional raw snapshot
    run_id      UUID REFERENCES run_logs(id),
    dedupe_key  TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_signals_company_id   ON signals (company_id);
CREATE INDEX idx_signals_company_type ON signals (company_id, signal_type);
CREATE INDEX idx_signals_signal_date  ON signals (signal_date DESC);
CREATE INDEX idx_signals_type         ON signals (signal_type);

DROP TRIGGER IF EXISTS trg_signals_updated_at ON signals;
CREATE TRIGGER trg_signals_updated_at
BEFORE UPDATE ON signals
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── provenance FKs on companies (deferred — signals must exist first) ──────

ALTER TABLE companies
    ADD CONSTRAINT companies_created_from_signal_id_fkey
        FOREIGN KEY (created_from_signal_id) REFERENCES signals(id) ON DELETE SET NULL,
    ADD CONSTRAINT companies_last_signal_id_fkey
        FOREIGN KEY (last_signal_id) REFERENCES signals(id) ON DELETE SET NULL;

-- ─── contacts ───────────────────────────────────────────────────────────────

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
        CONSTRAINT contacts_other_channels_is_array CHECK (jsonb_typeof(other_channels) = 'array'),

    notion_page_id TEXT,
    notion_synced_at TIMESTAMPTZ,

    discovered_from_signal_id UUID REFERENCES signals(id) ON DELETE SET NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_contacts_company_name
    ON contacts (company_id, lower(first_name), lower(last_name));
CREATE UNIQUE INDEX idx_contacts_company_name_upsert
    ON contacts (company_id, first_name, last_name);
CREATE INDEX idx_contacts_company_id
    ON contacts (company_id);
CREATE INDEX idx_contacts_email
    ON contacts (email)
    WHERE email IS NOT NULL;

DROP TRIGGER IF EXISTS trg_contacts_updated_at ON contacts;
CREATE TRIGGER trg_contacts_updated_at
BEFORE UPDATE ON contacts
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── source_links ───────────────────────────────────────────────────────────

CREATE TABLE source_links (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id       UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    kind             TEXT NOT NULL,
    url              TEXT NOT NULL,
    source           TEXT NOT NULL DEFAULT 'unknown',
    confidence       NUMERIC(3,2) NOT NULL DEFAULT 0.50
                     CONSTRAINT source_links_confidence_check CHECK (confidence >= 0 AND confidence <= 1),
    found_via        TEXT,
    source_signal_id UUID REFERENCES signals(id) ON DELETE SET NULL,
    raw              JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, kind, url)
);

CREATE INDEX idx_source_links_company ON source_links (company_id);
CREATE INDEX idx_source_links_kind ON source_links (kind);

-- ─── analysis_notes ─────────────────────────────────────────────────────────

CREATE TABLE analysis_notes (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    section    TEXT NOT NULL
               CONSTRAINT analysis_notes_section_check
               CHECK (section IN ('company', 'product', 'collaboration', 'financials', 'news', 'audit')),
    facts      JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence NUMERIC(3,2) NOT NULL DEFAULT 0.50
               CONSTRAINT analysis_notes_confidence_check CHECK (confidence >= 0 AND confidence <= 1),
    model      TEXT,
    version    TEXT NOT NULL DEFAULT 'v1',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, section, version)
);

CREATE INDEX idx_analysis_notes_company ON analysis_notes (company_id);

-- ─── analysis_note_signals ──────────────────────────────────────────────────
-- Junction: analysis_notes ↔ signals (many-to-many with role).

CREATE TABLE analysis_note_signals (
    analysis_note_id UUID NOT NULL REFERENCES analysis_notes(id) ON DELETE CASCADE,
    signal_id        UUID NOT NULL REFERENCES signals(id)        ON DELETE CASCADE,
    role             TEXT NOT NULL DEFAULT 'supports'
                     CONSTRAINT analysis_note_signals_role_check
                     CHECK (role IN ('supports', 'contradicts', 'context')),
    note             TEXT,
    PRIMARY KEY (analysis_note_id, signal_id)
);

CREATE INDEX idx_ans_signal ON analysis_note_signals (signal_id);

-- ─── dossiers ───────────────────────────────────────────────────────────────

CREATE TABLE dossiers (
    company_id     UUID PRIMARY KEY REFERENCES companies(id) ON DELETE CASCADE,
    summary_md     TEXT,
    sections       JSONB NOT NULL DEFAULT '{}'::jsonb,
    audit_md       TEXT,
    table_fields   JSONB NOT NULL DEFAULT '{}'::jsonb,
    version        TEXT NOT NULL DEFAULT 'v1',
    generated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    notion_page_id TEXT
);
