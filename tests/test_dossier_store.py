"""dossier_store tests с замоканным Supabase-клиентом (по образцу test_contacts_store)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dossier_store import (
    get_analysis_notes,
    get_source_links,
    upsert_analysis_note,
    upsert_source_link,
)


@pytest.fixture
def mock_store():
    store = MagicMock()
    table_mock = MagicMock()
    store._client.table.return_value = table_mock
    table_mock.upsert.return_value = table_mock
    table_mock.update.return_value = table_mock
    table_mock.select.return_value = table_mock
    table_mock.eq.return_value = table_mock
    table_mock.order.return_value = table_mock
    table_mock.execute.return_value = MagicMock(data=[])
    return store


def test_upsert_source_link_sets_fields(mock_store):
    link = {
        "company_domain": "radai.com",
        "kind": "github_org",
        "url": "https://github.com/radai",
        "source": "github_resolver",
        "confidence": "high",
    }
    upsert_source_link(mock_store, link)
    mock_store._client.table.assert_called_with("source_links")
    call = mock_store._client.table.return_value.upsert.call_args
    row = call[0][0]
    assert row["company_domain"] == "radai.com"
    assert row["kind"] == "github_org"
    assert row["url"] == "https://github.com/radai"
    assert call[1]["on_conflict"] == "company_domain,kind,url"


def test_upsert_source_link_defaults(mock_store):
    upsert_source_link(mock_store, {
        "company_domain": "radai.com",
        "kind": "wayback",
        "url": "https://web.archive.org/web/2025/https://radai.com",
    })
    row = mock_store._client.table.return_value.upsert.call_args[0][0]
    assert row["source"] == "unknown"
    assert row["confidence"] == "medium"
    assert row["raw"] == {}


def test_get_source_links_queries_by_domain(mock_store):
    get_source_links(mock_store, "radai.com")
    mock_store._client.table.assert_called_with("source_links")
    mock_store._client.table.return_value.eq.assert_called_with(
        "company_domain", "radai.com"
    )


def test_upsert_analysis_note_sets_fields(mock_store):
    note = {
        "company_domain": "radai.com",
        "section": "product",
        "facts": {"start_date": "2021"},
        "sources": [{"url": "https://radai.com/about", "note": "about page"}],
        "confidence": "high",
        "model": "claude",
        "version": "v1",
    }
    upsert_analysis_note(mock_store, note)
    mock_store._client.table.assert_called_with("analysis_notes")
    call = mock_store._client.table.return_value.upsert.call_args
    row = call[0][0]
    assert row["section"] == "product"
    assert row["facts"] == {"start_date": "2021"}
    assert call[1]["on_conflict"] == "company_domain,section,version"


def test_upsert_analysis_note_defaults(mock_store):
    upsert_analysis_note(mock_store, {
        "company_domain": "radai.com",
        "section": "company",
    })
    row = mock_store._client.table.return_value.upsert.call_args[0][0]
    assert row["facts"] == {}
    assert row["sources"] == []
    assert row["confidence"] == "medium"
    assert row["version"] == "v1"


def test_get_analysis_notes_queries_by_domain(mock_store):
    get_analysis_notes(mock_store, "radai.com")
    mock_store._client.table.assert_called_with("analysis_notes")
    mock_store._client.table.return_value.eq.assert_called_with(
        "company_domain", "radai.com"
    )
