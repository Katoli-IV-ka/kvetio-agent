-- 031_contacts_sales_fields.sql
-- Backfill contacts sales-classification fields that are present in schema.sql
-- but were not included in 029_sales_fields_p0p1.sql.

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS tier          SMALLINT,
    ADD COLUMN IF NOT EXISTS role_title    TEXT,
    ADD COLUMN IF NOT EXISTS seniority     TEXT,
    ADD COLUMN IF NOT EXISTS decision_area TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'contacts_tier_check'
          AND conrelid = 'contacts'::regclass
    ) THEN
        ALTER TABLE contacts
            ADD CONSTRAINT contacts_tier_check CHECK (tier BETWEEN 1 AND 3);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'contacts_seniority_check'
          AND conrelid = 'contacts'::regclass
    ) THEN
        ALTER TABLE contacts
            ADD CONSTRAINT contacts_seniority_check CHECK (
                seniority IN ('C-level', 'VP', 'Director', 'Manager', 'IC', 'Unknown')
            );
    END IF;
END $$;

ALTER TABLE contacts
    DROP CONSTRAINT IF EXISTS contacts_outreach_check,
    DROP CONSTRAINT IF EXISTS contacts_outreach_status_check;

ALTER TABLE contacts
    ADD CONSTRAINT contacts_outreach_check CHECK (
        outreach_status IN (
            'new', 'queued', 'cold', 'contacted', 'replied', 'meeting_set',
            'bounced', 'skip', 'not_relevant', 'do_not_contact'
        )
    );

CREATE INDEX IF NOT EXISTS idx_contacts_tier
    ON contacts (tier)
    WHERE tier IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_contacts_outreach_status
    ON contacts (outreach_status)
    WHERE outreach_status IS NOT NULL;
