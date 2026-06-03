-- Migration 003: добавить source_page_url в таблицу companies
-- Описание: поле хранит ссылку на страницу компании в первичном источнике обнаружения
--   - HuggingFace: https://huggingface.co/<org-name>
--   - YC:          https://www.ycombinator.com/companies/<slug>
--   - Greenhouse:  https://boards.greenhouse.io/<slug>
-- Используется этапом Source Expansion для WebFetch без знания специфики источника.
-- Применить в Supabase SQL Editor.

ALTER TABLE companies
    ADD COLUMN IF NOT EXISTS source_page_url TEXT;

COMMENT ON COLUMN companies.source_page_url IS
    'URL страницы компании в первичном источнике обнаружения (HuggingFace, YC, Greenhouse и др.). '
    'Используется Source Expansion агентом для дозаполнения website и других полей через WebFetch.';
