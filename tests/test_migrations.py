"""Contract-тесты для foundation-миграций 008–010.

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
