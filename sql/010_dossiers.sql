-- Migration 010: dossiers — финальное досье этапа 5 (Conclusions), одно на компанию.
-- 6-секционное саммари + аудит + поля таблицы. Синкается в Notion.
-- Применить в Supabase SQL Editor. Идемпотентный. Soft FK по company_domain.

CREATE TABLE IF NOT EXISTS dossiers (
    company_domain  TEXT PRIMARY KEY,
    summary_md      TEXT,
    sections        JSONB NOT NULL DEFAULT '{}'::jsonb,
    audit_md        TEXT,
    table_fields    JSONB NOT NULL DEFAULT '{}'::jsonb,
    version         TEXT NOT NULL DEFAULT 'v1',
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
