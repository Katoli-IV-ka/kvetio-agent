-- Kvetio — canonical Supabase runtime schema (research + collect).
-- IMPORTANT: this file is intended for destructive environment reset / bootstrap.
-- It does not provide backward-compatible migrations for old SQLite/legacy states.
-- Apply in Supabase SQL Editor or migration runner on clean/dev environments.
-- Version: 2026-05-04

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ─── companies ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS companies (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain            TEXT UNIQUE NOT NULL,
    name              TEXT NOT NULL,
    website           TEXT NOT NULL,
    linkedin_url      TEXT,
    notion_page_id    TEXT,
    status            TEXT NOT NULL DEFAULT 'Researching',
    latest_signal     TEXT,
    last_signal_date  DATE,
    last_verified     DATE,
    score             INTEGER,
    score_bucket      TEXT,
    score_version     TEXT,
    icp_segment       TEXT,
    funding_stage     TEXT,
    funding_amount    TEXT,
    funding_date      DATE,
    team_size         TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_companies_status ON companies (status);
CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies (domain);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_companies_updated_at ON companies;
CREATE TRIGGER trg_companies_updated_at
BEFORE UPDATE ON companies
FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ─── signals ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS signals (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source              TEXT NOT NULL,
    signal_type         TEXT NOT NULL,
    company_name        TEXT NOT NULL,
    domain              TEXT,
    normalized_domain   TEXT,
    linkedin_url        TEXT,
    evidence_url        TEXT UNIQUE NOT NULL,
    signal_date         DATE NOT NULL,
    confidence          TEXT NOT NULL DEFAULT 'medium',
    parser_version      TEXT,
    raw_data            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_signals_normalized_domain ON signals (normalized_domain);
CREATE INDEX IF NOT EXISTS idx_signals_signal_date ON signals (signal_date DESC);
CREATE INDEX IF NOT EXISTS idx_signals_signal_type ON signals (signal_type);

-- ─── run_logs ───────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS run_logs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_name           TEXT NOT NULL,
    started_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at         TIMESTAMPTZ,
    companies_found     INTEGER NOT NULL DEFAULT 0,
    companies_enriched  INTEGER NOT NULL DEFAULT 0,
    errors              JSONB NOT NULL DEFAULT '[]'::jsonb,
    notes               TEXT
);

CREATE INDEX IF NOT EXISTS idx_run_logs_task_name ON run_logs (task_name);
CREATE INDEX IF NOT EXISTS idx_run_logs_started_at ON run_logs (started_at DESC);
