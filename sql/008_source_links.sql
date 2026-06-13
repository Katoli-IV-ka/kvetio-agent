-- Migration 008: source_links — ссылки-источники, собранные на этапе 3 (Enrichment).
-- Для qualified-компании собираем «ручки» на будущий анализ. БЕЗ интерпретации —
-- только URL + провенанс.
-- Применить в Supabase SQL Editor. Идемпотентный: IF NOT EXISTS.
-- Зависит от: 001_init.sql (companies). Soft FK по company_domain (как 006_contacts).

CREATE TABLE IF NOT EXISTS source_links (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_domain  TEXT NOT NULL,
    kind            TEXT NOT NULL,
        -- github_org | hf_org | crunchbase | linkedin | sec_edgar |
        -- news_feed | wayback | grant | social | wikidata | ...
    url             TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'unknown',   -- каким резолвером найдено
    confidence      TEXT NOT NULL DEFAULT 'medium'
        CHECK (confidence IN ('high', 'medium', 'low')),
    found_via       TEXT,
    raw             JSONB NOT NULL DEFAULT '{}'::jsonb,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_domain, kind, url)
);

CREATE INDEX IF NOT EXISTS idx_source_links_company ON source_links (company_domain);
CREATE INDEX IF NOT EXISTS idx_source_links_kind ON source_links (kind);
