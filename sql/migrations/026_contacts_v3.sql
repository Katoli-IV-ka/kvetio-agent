-- 1. Drop companies -> signals FK constraints (signals dropped in Phase 5).
ALTER TABLE companies
    DROP CONSTRAINT IF EXISTS companies_created_from_signal_id_fkey,
    DROP CONSTRAINT IF EXISTS companies_last_signal_id_fkey;

-- 2. Add new contact columns (nullable for backfill).
ALTER TABLE contacts
    ADD COLUMN contact_type TEXT,
    ADD COLUMN name TEXT,
    ADD COLUMN discovered_from_research_record_id UUID
        REFERENCES research_records(id) ON DELETE SET NULL;

-- 3. Backfill from existing person rows.
--    discovered_from_signal_id values are valid research_records IDs (IDs preserved).
UPDATE contacts SET
    name = trim(first_name || ' ' || last_name),
    contact_type = 'person',
    discovered_from_research_record_id = discovered_from_signal_id;

-- 4. Enforce NOT NULL.
ALTER TABLE contacts
    ALTER COLUMN name SET NOT NULL,
    ALTER COLUMN contact_type SET NOT NULL;

-- 5. New dedup index.
CREATE UNIQUE INDEX idx_contacts_dedup
    ON contacts (company_id, contact_type, lower(name));
CREATE UNIQUE INDEX idx_contacts_dedup_upsert
    ON contacts (company_id, contact_type, name);

-- 6. Drop old indexes and legacy columns.
DROP INDEX IF EXISTS idx_contacts_company_name;
DROP INDEX IF EXISTS idx_contacts_company_name_upsert;
ALTER TABLE contacts
    DROP COLUMN first_name,
    DROP COLUMN last_name,
    DROP COLUMN discovered_from_signal_id;
