"""Unit-тесты notion_sync: чистые функции + движок с фейковыми клиентами."""

from __future__ import annotations

from pathlib import Path

import pytest

import notion_sync as ns


def test_load_mapping_reads_entities():
    mapping = ns.load_mapping()
    assert "companies" in mapping
    assert "contacts" in mapping
    fields = mapping["companies"]["fields"]
    names = {f["db_column"] for f in fields}
    assert "name" in names
    assert "outreach_status" in names


def test_validate_mapping_flags_bad_type():
    mapping = {
        "companies": {
            "notion_database_id_env": "NOTION_COMPANIES_DB_ID",
            "fields": [
                {"db_column": "name", "notion_property": "Name",
                 "notion_type": "title", "direction": "forward"},
                {"db_column": "score", "notion_property": "Score",
                 "notion_type": "bogus", "direction": "forward"},
            ],
        }
    }
    errors = ns.validate_mapping(mapping)
    assert any("bogus" in e for e in errors)


def test_validate_mapping_flags_bad_direction():
    mapping = {
        "companies": {
            "notion_database_id_env": "NOTION_COMPANIES_DB_ID",
            "fields": [
                {"db_column": "name", "notion_property": "Name",
                 "notion_type": "title", "direction": "sideways"},
            ],
        }
    }
    errors = ns.validate_mapping(mapping)
    assert any("sideways" in e for e in errors)
