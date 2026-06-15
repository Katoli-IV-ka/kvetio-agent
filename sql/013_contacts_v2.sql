-- Migration 013: contacts V2 — новые поля + join-таблица contact_companies
--
-- Применить в Supabase SQL Editor.
-- Идемпотентный: ADD COLUMN IF NOT EXISTS, CREATE TABLE IF NOT EXISTS.
-- Зависит от: 006_contacts.sql, 001_init.sql

-- ─── Новые колонки contacts ──────────────────────────────────────────────────

ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS contact_type TEXT NOT NULL DEFAULT 'Person'
        CHECK (contact_type IN ('Person', 'Company', 'Other')),
    ADD COLUMN IF NOT EXISTS phone TEXT,
    ADD COLUMN IF NOT EXISTS instagram_url TEXT,
    ADD COLUMN IF NOT EXISTS facebook_url TEXT,
    ADD COLUMN IF NOT EXISTS info TEXT,
    ADD COLUMN IF NOT EXISTS contact_result TEXT DEFAULT NULL
        CHECK (contact_result IN (
            'Не связывались',
            'Не удалось связаться',
            'Не релевантный контакт',
            'Начат диалог',
            'В процессе',
            'Другое'
        ));

-- ─── Join-таблица many-to-many ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS contact_companies (
    contact_id     UUID NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    company_domain TEXT NOT NULL,
    PRIMARY KEY (contact_id, company_domain)
);

CREATE INDEX IF NOT EXISTS idx_contact_companies_contact_id
    ON contact_companies (contact_id);

CREATE INDEX IF NOT EXISTS idx_contact_companies_domain
    ON contact_companies (company_domain);

-- ─── Комментарии ─────────────────────────────────────────────────────────────

COMMENT ON COLUMN contacts.contact_type IS
    'Тип контакта: Person (физлицо), Company (корп. email / аккаунт), Other.';

COMMENT ON COLUMN contacts.contact_result IS
    'Результат связи — заполняется вручную через Notion: '
    'Не связывались / Не удалось связаться / Не релевантный контакт / '
    'Начат диалог / В процессе / Другое.';

COMMENT ON TABLE contact_companies IS
    'Many-to-many: один контакт может быть связан с несколькими компаниями. '
    'company_domain — soft FK на companies.domain.';
