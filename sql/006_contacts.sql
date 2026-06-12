-- Migration 006: contacts table for DM outreach decision makers.
-- Stage 2.5 pipeline: qualified company -> specific outreach contacts.
--
-- Apply in Supabase SQL Editor.
-- Idempotent: IF NOT EXISTS / DO NOTHING.
-- Depends on: 001_init.sql (companies table, update_updated_at function).

CREATE TABLE IF NOT EXISTS contacts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    company_domain      TEXT NOT NULL,

    full_name           TEXT NOT NULL,
    first_name          TEXT,
    last_name           TEXT,

    title               TEXT,
    title_normalized    TEXT,
    dm_priority         INTEGER NOT NULL DEFAULT 2
        CHECK (dm_priority BETWEEN 1 AND 3),

    email               TEXT,
    email_status        TEXT NOT NULL DEFAULT 'unknown'
        CHECK (email_status IN ('verified', 'guessed', 'bounced', 'unknown')),
    email_source        TEXT,
    linkedin_url        TEXT,
    twitter_handle      TEXT,
    github_username     TEXT,

    source_vector       TEXT NOT NULL
        CHECK (source_vector IN (
            'github',
            'huggingface',
            'team_page',
            'apollo',
            'wellfound',
            'arxiv'
        )),
    source_url          TEXT,
    confidence          TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high', 'medium', 'low')),

    outreach_status     TEXT NOT NULL DEFAULT 'not_contacted'
        CHECK (outreach_status IN (
            'not_contacted',
            'contacted',
            'replied',
            'not_interested',
            'converted'
        )),
    outreach_note       TEXT,

    raw_payload         JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_dedup
    ON contacts (company_domain, lower(full_name));

-- Supabase upsert(on_conflict='company_domain,full_name') needs a plain
-- column unique index; the expression index above keeps case-insensitive guard.
CREATE UNIQUE INDEX IF NOT EXISTS idx_contacts_upsert_key
    ON contacts (company_domain, full_name);

CREATE INDEX IF NOT EXISTS idx_contacts_company_domain
    ON contacts (company_domain);

CREATE INDEX IF NOT EXISTS idx_contacts_priority
    ON contacts (dm_priority, company_domain);

CREATE INDEX IF NOT EXISTS idx_contacts_email_status
    ON contacts (email_status)
    WHERE email IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_contacts_outreach
    ON contacts (outreach_status)
    WHERE outreach_status = 'not_contacted';

CREATE INDEX IF NOT EXISTS idx_contacts_source_vector
    ON contacts (source_vector);

DROP TRIGGER IF EXISTS trg_contacts_updated_at ON contacts;
CREATE TRIGGER trg_contacts_updated_at
BEFORE UPDATE ON contacts
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMENT ON TABLE contacts IS
    'Decision-maker contacts for each qualified company. '
    'Filled by Stage 2.5 DM Enrichment from GitHub, HuggingFace, '
    'team pages, Apollo.io, Wellfound, and arXiv.';

COMMENT ON COLUMN contacts.company_domain IS
    'Normalized company domain; soft FK to companies.domain.';

COMMENT ON COLUMN contacts.dm_priority IS
    '1=direct data buyer, 2=influencer/champion, 3=entry point.';

COMMENT ON COLUMN contacts.email_status IS
    'verified=SMTP/API verified, guessed=pattern guess, bounced=invalid, unknown=no data.';

COMMENT ON COLUMN contacts.source_vector IS
    'Vector that discovered the contact, used for source quality analysis.';

COMMENT ON COLUMN contacts.raw_payload IS
    'Raw source payload for audit and future enrichment.';
