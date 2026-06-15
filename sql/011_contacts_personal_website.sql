-- Migration 011: personal_website + hf_username для contacts
-- Contact Search Extension: enricher заполняет личный сайт и HF-username.
--
-- Применить в Supabase SQL Editor.
-- Идемпотентный: IF NOT EXISTS.
-- Зависит от: 006_contacts.sql (таблица contacts)

ALTER TABLE contacts ADD COLUMN IF NOT EXISTS personal_website TEXT;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS hf_username TEXT;
