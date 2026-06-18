"""Contract tests for the current database baseline schema.

The project no longer keeps test-era migration history. `sql/schema.sql` is the
single source of truth for creating the current clean Supabase schema.
"""

from __future__ import annotations

import re
from pathlib import Path

SQL_DIR = Path(__file__).parent.parent / "sql"
SCHEMA = SQL_DIR / "schema.sql"


def _schema() -> str:
    return SCHEMA.read_text(encoding="utf-8")


def _table_body(sql: str, table: str) -> str:
    match = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", sql, re.DOTALL)
    assert match is not None
    return match.group(1)


def test_schema_file_is_the_only_active_sql_contract() -> None:
    sql_files = sorted(path.name for path in SQL_DIR.glob("*.sql"))
    assert sql_files == ["schema.sql"]


def test_schema_creates_current_runtime_tables() -> None:
    sql = _schema()
    for table in (
        "companies",
        "signals",
        "run_logs",
        "contacts",
        "source_links",
        "analysis_notes",
        "dossiers",
    ):
        assert f"CREATE TABLE {table}" in sql


def test_schema_does_not_create_removed_runtime_objects() -> None:
    sql = _schema()
    removed_objects = (
        "pipeline_runs",
        "bot_users",
        "bot_dialog_state",
        "bot_presets",
        "contact_companies",
        "github_org_cache",
        "recent_leads",
        "pipeline_stats",
    )
    for name in removed_objects:
        assert name not in sql


def test_companies_status_contract_is_current() -> None:
    sql = _schema()
    companies = _table_body(sql, "companies")
    assert "status TEXT NOT NULL DEFAULT 'discovered'" in companies
    for status in (
        "discovered",
        "relevant",
        "not_relevant",
        "manual_review",
        "sources_gathered",
        "analyzed",
        "dossier_ready",
    ):
        assert f"'{status}'" in companies
    for legacy_status in ("qualified", "triaged_out", "pending_enrich", "enriched", "Researching"):
        assert f"'{legacy_status}'" not in companies


def test_removed_company_fields_are_not_in_schema() -> None:
    sql = _schema()
    companies = _table_body(sql, "companies")
    for column in (
        "score",
        "score_bucket",
        "score_version",
        "ai_direction",
        "sources JSONB",
        "latest_signal",
        "reject_reason",
        "outreach_status",
        "outreach_note",
        "source_page_url",
    ):
        assert column not in companies


def test_contacts_schema_is_compact_outreach_contract() -> None:
    sql = _schema()
    assert "CREATE TABLE contacts" in sql
    for column in (
        "company_id UUID NOT NULL REFERENCES companies(id)",
        "first_name TEXT NOT NULL",
        "last_name TEXT NOT NULL DEFAULT ''",
        "info TEXT",
        "email TEXT",
        "phone TEXT",
        "linkedin_url TEXT",
        "x_url TEXT",
        "facebook_url TEXT",
        "instagram_url TEXT",
        "other_channels JSONB NOT NULL DEFAULT '[]'::jsonb",
        "notion_page_id TEXT",
        "notion_synced_at TIMESTAMPTZ",
    ):
        assert column in sql


def test_contacts_schema_removed_legacy_fields() -> None:
    sql = _table_body(_schema(), "contacts")
    for removed in (
        "company_domain",
        "full_name",
        "title TEXT",
        "title_normalized",
        "dm_priority",
        "email_status",
        "email_source",
        "twitter_handle",
        "github_username",
        "hf_username",
        "personal_website",
        "source_vector",
        "source_url",
        "confidence TEXT",
        "raw_payload",
        "contact_type",
    ):
        assert removed not in sql


def test_contacts_schema_uses_company_name_dedup() -> None:
    sql = _schema()
    assert "CREATE UNIQUE INDEX idx_contacts_company_name" in sql
    assert "ON contacts (company_id, lower(first_name), lower(last_name))" in sql
    assert "CREATE UNIQUE INDEX idx_contacts_company_name_upsert" in sql
    assert "ON contacts (company_id, first_name, last_name)" in sql
    assert "idx_contacts_company_id" in sql
    assert "idx_contacts_email" in sql


def test_deep_analysis_tables_have_expected_unique_keys() -> None:
    sql = _schema()
    assert "UNIQUE (company_domain, kind, url)" in sql
    assert "UNIQUE (company_domain, section, version)" in sql
    assert "company_domain TEXT PRIMARY KEY" in sql
