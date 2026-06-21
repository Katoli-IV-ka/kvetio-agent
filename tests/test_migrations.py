"""Contract tests for the current database baseline schema.

`sql/schema.sql` is the single source of truth for creating the current clean
Supabase schema. Numbered migrations under `sql/migrations/` are live upgrade
history, not the clean-install contract.
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
        "run_logs",
        "record_types",
        "research_records",
        "contacts",
        "analysis_records",
        "analysis_links",
        "dossiers",
        "dossier_links",
    ):
        assert f"CREATE TABLE {table}" in sql


def test_schema_has_no_legacy_tables() -> None:
    sql = _schema()
    for legacy in (
        "signals",
        "signal_types",
        "source_links",
        "analysis_notes",
        "analysis_note_signals",
        "dossiers_legacy",
    ):
        assert f"CREATE TABLE {legacy} (" not in sql


def test_companies_status_contract_is_current() -> None:
    companies = _table_body(_schema(), "companies")
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


def test_companies_has_no_legacy_columns() -> None:
    body = _table_body(_schema(), "companies")
    for col in (
        "last_signal_date",
        "last_verified",
        "funding_stage",
        "funding_amount",
        "funding_date",
        "team_size",
        "site_note",
        "website_snippet",
        "dm_enriched_at",
        "created_from_signal_id",
        "last_signal_id",
    ):
        assert col not in body


def test_companies_status_includes_data_partner() -> None:
    """Phase 1: data-provider companies get a partner track instead of not_relevant."""
    companies = _table_body(_schema(), "companies")
    assert "'data_partner'" in companies


def test_schema_has_phase1_record_types() -> None:
    """Phase 1 adds financial-signal, source, and partner-flag record types."""
    sql = _schema()
    for code in (
        "form_d",
        "grant",
        "quote",
        "job_count",
        "market_quote",
        "arxiv_paper",
        "data_partner_flag",
    ):
        assert f"('{code}'" in sql, f"record_types missing {code}"


def test_contacts_uses_name_and_type() -> None:
    body = _table_body(_schema(), "contacts")
    assert "name TEXT NOT NULL" in body
    assert "contact_type TEXT NOT NULL DEFAULT 'person'" in body
    assert "first_name" not in body
    assert "last_name" not in body
    assert "discovered_from_research_record_id UUID REFERENCES research_records(id)" in body


def test_contacts_schema_uses_name_type_dedup() -> None:
    sql = _schema()
    assert "CREATE UNIQUE INDEX idx_contacts_dedup" in sql
    assert "ON contacts (company_id, contact_type, lower(name))" in sql
    assert "CREATE UNIQUE INDEX idx_contacts_dedup_upsert" in sql
    assert "ON contacts (company_id, contact_type, name)" in sql
    assert "idx_contacts_company_id" in sql
    assert "idx_contacts_email" in sql


def test_research_records_has_record_role() -> None:
    body = _table_body(_schema(), "research_records")
    assert "record_role TEXT NOT NULL DEFAULT 'evidence'" in body
    assert "observed_at DATE NOT NULL" in body
    assert "record_type TEXT NOT NULL REFERENCES record_types(code)" in body


def test_analysis_and_dossier_provenance_keys() -> None:
    sql = _schema()
    assert "UNIQUE (company_id, section, version)" in sql
    assert "PRIMARY KEY (analysis_record_id, research_record_id)" in sql
    assert "company_id UUID PRIMARY KEY REFERENCES companies(id)" in sql
    assert "PRIMARY KEY (company_id, analysis_record_id)" in sql
