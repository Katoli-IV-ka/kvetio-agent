-- 033_remove_hq_country_and_team_size_estimate.sql
-- Canonicalize geography and size fields on companies.
-- - companies.country replaces companies.hq_country
-- - companies.company_size replaces dossiers.team_size_estimate

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'companies'
          AND column_name = 'hq_country'
    ) THEN
        EXECUTE $sql$
            UPDATE companies
            SET country = hq_country
            WHERE country IS NULL
              AND hq_country IS NOT NULL
        $sql$;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'dossiers'
          AND column_name = 'team_size_estimate'
    ) THEN
        EXECUTE $sql$
            UPDATE companies AS c
            SET company_size = d.team_size_estimate
            FROM dossiers AS d
            WHERE d.company_id = c.id
              AND c.company_size IS NULL
              AND d.team_size_estimate IS NOT NULL
        $sql$;
    END IF;
END $$;

ALTER TABLE companies
    DROP COLUMN IF EXISTS hq_country;

ALTER TABLE dossiers
    DROP COLUMN IF EXISTS team_size_estimate;
