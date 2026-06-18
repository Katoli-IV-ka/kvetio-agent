-- Migration 017: agent database cleanup.
--
-- Implements docs/superpowers/specs/2026-06-17-agent-database-cleanup-design.md.
-- Apply only after runtime code no longer reads the dropped objects.

ALTER TABLE contacts
  ADD COLUMN IF NOT EXISTS company_id UUID;

UPDATE contacts AS c
SET company_id = co.id
FROM companies AS co
WHERE c.company_id IS NULL
  AND c.company_domain = co.domain;

DO $$
DECLARE
  contacts_unmatched_company_domain INTEGER;
BEGIN
  SELECT COUNT(*)
  INTO contacts_unmatched_company_domain
  FROM contacts
  WHERE company_id IS NULL;

  IF contacts_unmatched_company_domain > 0 THEN
    RAISE EXCEPTION
      'Cannot set contacts.company_id NOT NULL: % contacts have no matching companies.domain',
      contacts_unmatched_company_domain;
  END IF;
END $$;

ALTER TABLE contacts
  ADD CONSTRAINT contacts_company_id_fk
  FOREIGN KEY (company_id) REFERENCES companies(id)
  NOT VALID;

ALTER TABLE contacts
  VALIDATE CONSTRAINT contacts_company_id_fk;

ALTER TABLE contacts
  ADD CONSTRAINT contacts_company_id_not_null
  CHECK (company_id IS NOT NULL)
  NOT VALID;

ALTER TABLE contacts
  VALIDATE CONSTRAINT contacts_company_id_not_null;

ALTER TABLE contacts
  ALTER COLUMN company_id SET NOT NULL;

ALTER TABLE contacts
  DROP CONSTRAINT contacts_company_id_not_null;

CREATE INDEX IF NOT EXISTS idx_contacts_company_id
  ON contacts (company_id);

ALTER TABLE contacts
  DROP CONSTRAINT IF EXISTS contacts_contact_type_check;
ALTER TABLE contacts
  ADD CONSTRAINT contacts_contact_type_check
  CHECK (contact_type IN ('Person', 'Company', 'Related Person', 'Other'))
  NOT VALID;
ALTER TABLE contacts
  VALIDATE CONSTRAINT contacts_contact_type_check;

ALTER TABLE contacts
  DROP CONSTRAINT IF EXISTS contacts_email_status_check;
ALTER TABLE contacts
  ADD CONSTRAINT contacts_email_status_check
  CHECK (email_status IN ('verified', 'guessed', 'bounced', 'unknown', 'scraped'))
  NOT VALID;
ALTER TABLE contacts
  VALIDATE CONSTRAINT contacts_email_status_check;

ALTER TABLE contacts
  DROP CONSTRAINT IF EXISTS contacts_source_vector_check;
ALTER TABLE contacts
  ADD CONSTRAINT contacts_source_vector_check
  CHECK (source_vector IN (
    'github',
    'huggingface',
    'team_page',
    'apollo',
    'wellfound',
    'arxiv',
    'contact_page'
  ))
  NOT VALID;
ALTER TABLE contacts
  VALIDATE CONSTRAINT contacts_source_vector_check;

UPDATE companies
SET status = CASE status
  WHEN 'qualified' THEN 'relevant'
  WHEN 'pending_enrich' THEN 'relevant'
  WHEN 'enriched' THEN 'relevant'
  WHEN 'triaged_out' THEN 'not_relevant'
  ELSE status
END
WHERE status IN ('qualified', 'pending_enrich', 'enriched', 'triaged_out');

DROP TABLE IF EXISTS contact_companies;
DROP TABLE IF EXISTS bot_presets;

ALTER TABLE companies
  DROP COLUMN IF EXISTS score,
  DROP COLUMN IF EXISTS score_bucket,
  DROP COLUMN IF EXISTS score_version,
  DROP COLUMN IF EXISTS ai_direction,
  DROP COLUMN IF EXISTS sources,
  DROP COLUMN IF EXISTS latest_signal,
  DROP COLUMN IF EXISTS reject_reason,
  DROP COLUMN IF EXISTS outreach_status,
  DROP COLUMN IF EXISTS outreach_note;

ALTER TABLE contacts
  DROP COLUMN IF EXISTS outreach_status,
  DROP COLUMN IF EXISTS outreach_note,
  DROP COLUMN IF EXISTS contact_result;
