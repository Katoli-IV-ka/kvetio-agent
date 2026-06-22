-- sql/migrations/029_notion_profile_fields.sql
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS hq_country  text,
  ADD COLUMN IF NOT EXISTS hq_location text;

ALTER TABLE contacts
  ADD COLUMN IF NOT EXISTS source text,
  ADD COLUMN IF NOT EXISTS outreach_status text NOT NULL DEFAULT 'new'
    CONSTRAINT contacts_outreach_check
    CHECK (outreach_status IN ('new','queued','contacted','replied','bounced','skip'));

CREATE TABLE IF NOT EXISTS translations (
  source_hash     text NOT NULL,
  target_lang     text NOT NULL DEFAULT 'ru',
  source_text     text NOT NULL,
  translated_text text NOT NULL,
  model           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_hash, target_lang)
);
