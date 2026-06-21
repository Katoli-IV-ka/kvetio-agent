-- Phase 1 (agent upgrade): data_partner status + new financial/source/flag record types.
-- See docs/superpowers/specs/2026-06-21-agent-upgrade-design.md §5, §6.

-- 1. Allow the data_partner status (data-provider / partner-track lead).
ALTER TABLE companies
    DROP CONSTRAINT IF EXISTS companies_status_check;
ALTER TABLE companies
    ADD CONSTRAINT companies_status_check CHECK (status IN (
        'discovered',
        'relevant',
        'not_relevant',
        'manual_review',
        'sources_gathered',
        'analyzed',
        'dossier_ready',
        'data_partner'
    ));

-- 2. New record types. Idempotent: skip codes that already exist.
INSERT INTO record_types (code, category, description) VALUES
  ('form_d',            'financials', 'SEC EDGAR Form D private-placement filing'),
  ('grant',            'financials', 'Government research grant award (SBIR/NIH/CORDIS)'),
  ('quote',            'financials', 'Direct quote signalling fundraising intent'),
  ('job_count',        'financials', 'Hiring-burst / open-roles count signal'),
  ('market_quote',     'financials', 'Public-market price quote (Stooq/Yahoo)'),
  ('arxiv_paper',      'sources',    'arXiv paper matching the company'),
  ('data_partner_flag','discovery',  'Durable marker that the company is a data provider / partner-track lead')
ON CONFLICT (code) DO NOTHING;
