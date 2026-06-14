-- Migration 011: поля для перехода на БД как источник истины + Notion sync.
-- Применить в Supabase SQL Editor. Идемпотентный: IF NOT EXISTS.
-- Зависит от: 001_init.sql (companies), 006_contacts.sql, 010_dossiers.sql.

-- companies: ручные CRM-поля, ранее жившие только в Notion, теперь в БД.
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS outreach_status TEXT;          -- бывший "Статус анализа"
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS outreach_note TEXT;            -- ручная заметка оператора
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS notion_synced_at TIMESTAMPTZ;  -- метка последнего синка

COMMENT ON COLUMN companies.outreach_status IS
  'Ручной CRM-статус аутрича. Источник истины — Notion (reverse-синк). '
  'БД ставит только дефолт при создании.';
COMMENT ON COLUMN companies.outreach_note IS
  'Ручная заметка оператора. Reverse-синк из Notion.';

-- contacts: outreach_status/outreach_note уже есть (006). Нужен ключ связки со страницей.
ALTER TABLE contacts
  ADD COLUMN IF NOT EXISTS notion_page_id TEXT;

-- dossiers: ключ связки (досье пишется в тело страницы компании; колонка для трекинга).
ALTER TABLE dossiers
  ADD COLUMN IF NOT EXISTS notion_page_id TEXT;
