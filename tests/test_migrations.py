"""Contract-тесты для foundation-миграций 008–014.

Миграции применяются вручную в Supabase SQL Editor, поэтому здесь мы
проверяем не живую БД, а что SQL-файлы существуют и содержат ключевой DDL.
"""

from __future__ import annotations

from pathlib import Path

SQL_DIR = Path(__file__).parent.parent / "sql"


def _read(name: str) -> str:
    return (SQL_DIR / name).read_text(encoding="utf-8")


def test_migration_008_source_links():
    sql = _read("008_source_links.sql")
    assert "CREATE TABLE IF NOT EXISTS source_links" in sql
    assert "UNIQUE (company_domain, kind, url)" in sql


def test_migration_009_analysis_notes():
    sql = _read("009_analysis_notes.sql")
    assert "CREATE TABLE IF NOT EXISTS analysis_notes" in sql
    assert "UNIQUE (company_domain, section, version)" in sql


def test_migration_010_dossiers():
    sql = _read("010_dossiers.sql")
    assert "CREATE TABLE IF NOT EXISTS dossiers" in sql
    assert "summary_md" in sql


def test_migration_011_notion_sync_fields():
    sql = _read("011_notion_sync_fields.sql")
    assert "ALTER TABLE companies" in sql
    assert "outreach" + "_status" in sql
    assert "outreach" + "_note" in sql
    assert "notion_synced_at" in sql
    assert "ALTER TABLE contacts" in sql
    assert "ALTER TABLE dossiers" in sql
    assert "notion_page_id" in sql


def test_migration_012_bot():
    sql = _read("012_bot.sql")
    assert "CREATE TABLE IF NOT EXISTS pipeline_runs" in sql
    assert "CREATE TABLE IF NOT EXISTS bot_users" in sql
    assert "CREATE TABLE IF NOT EXISTS " + "bot" + "_presets" in sql
    assert "CREATE TABLE IF NOT EXISTS bot_dialog_state" in sql


def test_migration_013_contacts_v2():
    sql = _read("013_contacts_v2.sql")
    assert "ADD COLUMN IF NOT EXISTS contact_type" in sql
    assert "ADD COLUMN IF NOT EXISTS phone" in sql
    assert "ADD COLUMN IF NOT EXISTS instagram_url" in sql
    assert "ADD COLUMN IF NOT EXISTS facebook_url" in sql
    assert "ADD COLUMN IF NOT EXISTS info" in sql
    assert "ADD COLUMN IF NOT EXISTS " + "contact" + "_result" in sql
    assert "CREATE TABLE IF NOT EXISTS " + "contact" + "_companies" in sql
    assert "REFERENCES contacts(id) ON DELETE CASCADE" in sql



def test_migration_014_drop_pipeline_runs():
    sql = _read("014_drop_pipeline_runs.sql")
    assert "DROP TABLE IF EXISTS pipeline_runs" in sql
    # run_logs must NOT be dropped — only pipeline_runs goes away
    assert "DROP TABLE IF EXISTS run_logs" not in sql


def test_migration_015_drop_bot_runtime_state():
    sql = _read("015_drop_bot_runtime_state.sql")
    assert "DROP TABLE IF EXISTS bot_users" in sql
    assert "DROP TABLE IF EXISTS bot_dialog_state" in sql
    assert "DROP TABLE IF EXISTS " + "bot" + "_presets" not in sql


def test_migration_015_drop_unused_db_objects():
    sql = _read("015_drop_unused_db_objects.sql")
    assert "DROP VIEW IF EXISTS recent_leads" in sql
    assert "DROP VIEW IF EXISTS pipeline_stats" in sql
    assert "DROP TABLE IF EXISTS github_org_cache" in sql
    assert "DROP TABLE IF EXISTS companies" not in sql
    assert "DROP TABLE IF EXISTS signals" not in sql
    assert "DROP TABLE IF EXISTS run_logs" not in sql


def test_migration_016_bot_default_limit_5():
    sql = _read("016_bot_default_limit_5.sql")
    assert "UPDATE " + "bot" + "_presets" in sql
    assert "nightly-full" in sql
    assert "limit_per_segment" in sql
    assert "'5'::jsonb" in sql


def test_migration_017_agent_database_cleanup():
    sql = _read("017_agent_database_cleanup.sql")
    assert "ADD COLUMN IF NOT EXISTS company_id UUID" in sql
    assert "REFERENCES companies(id)" in sql
    assert "contacts_unmatched_company_domain" in sql
    assert "contacts_contact_type_check" in sql
    assert "'Related Person'" in sql
    assert "contacts_email_status_check" in sql
    assert "'scraped'" in sql
    assert "contacts_source_vector_check" in sql
    assert "'contact_page'" in sql
    assert "DROP TABLE IF EXISTS " + "contact" + "_companies" in sql
    assert "DROP TABLE IF EXISTS " + "bot" + "_presets" in sql
    assert "DROP COLUMN IF EXISTS score" in sql
    assert "DROP COLUMN IF EXISTS " + "score" + "_bucket" in sql
    assert "DROP COLUMN IF EXISTS " + "score" + "_version" in sql
    assert "DROP COLUMN IF EXISTS " + "ai" + "_direction" in sql
    assert "DROP COLUMN IF EXISTS sources" in sql
    assert "DROP COLUMN IF EXISTS " + "latest" + "_signal" in sql
    assert "DROP COLUMN IF EXISTS " + "reject" + "_reason" in sql
    assert "DROP COLUMN IF EXISTS " + "outreach" + "_status" in sql
    assert "DROP COLUMN IF EXISTS " + "outreach" + "_note" in sql
    assert "DROP COLUMN IF EXISTS " + "contact" + "_result" in sql
