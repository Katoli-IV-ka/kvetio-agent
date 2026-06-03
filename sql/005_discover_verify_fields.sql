-- Migration 005: поля для discover_verify_task
-- Применить в Supabase SQL Editor.
-- Идемпотентный: использует IF NOT EXISTS / DO NOTHING.

-- reject_reason: причина отклонения на этапе верификации
-- (dead_website / no_ai_dev / api_wrapper / competitor / too_large)
-- Заменяет двойное использование ai_direction для rejection.
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS reject_reason TEXT;

-- site_note: техническая пометка по сайту (behind_protection, no_website_found)
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS site_note TEXT;

-- sources: JSON-массив источников, из которых найдена компания
-- Пример: '["huggingface","yc_browser"]'
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS sources JSONB DEFAULT '[]'::jsonb;

-- website_snippet: первые ~200 символов контента главной страницы
-- Используется для аудита quick filter decision
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS website_snippet TEXT;

-- description: краткое описание компании (2-3 предложения)
-- Уже может быть в схеме через другие миграции — IF NOT EXISTS безопасен
ALTER TABLE companies
  ADD COLUMN IF NOT EXISTS description TEXT;

-- Индекс для быстрой фильтрации по reject_reason
CREATE INDEX IF NOT EXISTS idx_companies_reject_reason
  ON companies (reject_reason)
  WHERE reject_reason IS NOT NULL;

-- Индекс для manual_review очереди
CREATE INDEX IF NOT EXISTS idx_companies_manual_review
  ON companies (status)
  WHERE status = 'manual_review';
