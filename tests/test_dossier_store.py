"""dossier_store tests — company_id keyed, numeric confidence, junction table."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dossier_store import (
    get_analysis_notes,
    get_dossier,
    get_source_links,
    link_note_to_signals,
    upsert_analysis_note,
    upsert_dossier,
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


def test_upsert_source_link_keyed_by_company_id(mock_store):
    link = {
        "company_id": "cid-1",
        "kind": "github_org",
        "url": "https://github.com/acme",
        "source": "github_resolver",
        "confidence": "high",
    }
    upsert_source_link(mock_store, link)
    mock_store._client.table.assert_called_with("source_links")
    call_args = mock_store._client.table.return_value.upsert.call_args
    row = call_args[0][0]
    assert row["company_id"] == "cid-1"
    assert row["kind"] == "github_org"
    assert row["url"] == "https://github.com/acme"
    assert call_args[1]["on_conflict"] == "company_id,kind,url"


def test_upsert_source_link_numeric_confidence(mock_store):
    upsert_source_link(mock_store, {
        "company_id": "cid-1",
        "kind": "wayback",
        "url": "https://web.archive.org/web/2025/https://acme.com",
        "confidence": "high",
    })
    row = mock_store._client.table.return_value.upsert.call_args[0][0]
    assert row["confidence"] == 0.9


def test_upsert_source_link_defaults(mock_store):
    upsert_source_link(mock_store, {
        "company_id": "cid-1",
        "kind": "wayback",
        "url": "https://web.archive.org/",
    })
    row = mock_store._client.table.return_value.upsert.call_args[0][0]
    assert row["source"] == "unknown"
    assert row["confidence"] == 0.5   # "medium" -> 0.5
    assert row["raw"] == {}
    assert row["source_signal_id"] is None


def test_get_source_links_queries_by_company_id(mock_store):
    get_source_links(mock_store, "cid-xyz")
    mock_store._client.table.assert_called_with("source_links")
    mock_store._client.table.return_value.eq.assert_called_with("company_id", "cid-xyz")


def test_upsert_analysis_note_keyed_by_company_id(mock_store):
    note = {
        "company_id": "cid-1",
        "section": "product",
        "facts": {"start_date": "2021"},
        "confidence": "high",
        "model": "claude",
        "version": "v1",
    }
    upsert_analysis_note(mock_store, note)
    mock_store._client.table.assert_called_with("analysis_notes")
    call_args = mock_store._client.table.return_value.upsert.call_args
    row = call_args[0][0]
    assert row["company_id"] == "cid-1"
    assert row["section"] == "product"
    assert row["facts"] == {"start_date": "2021"}
    assert call_args[1]["on_conflict"] == "company_id,section,version"
    assert "sources" not in row   # removed: replaced by junction table


def test_upsert_analysis_note_numeric_confidence(mock_store):
    upsert_analysis_note(mock_store, {"company_id": "cid-1", "section": "company"})
    row = mock_store._client.table.return_value.upsert.call_args[0][0]
    assert row["confidence"] == 0.5   # "medium" -> 0.5
    assert row["version"] == "v1"


def test_get_analysis_notes_queries_by_company_id(mock_store):
    get_analysis_notes(mock_store, "cid-xyz")
    mock_store._client.table.assert_called_with("analysis_notes")
    mock_store._client.table.return_value.eq.assert_called_with("company_id", "cid-xyz")


def test_link_note_to_signals_inserts_rows(mock_store):
    link_note_to_signals(mock_store, "note-1", ["sig-1", "sig-2"], role="supports")
    mock_store._client.table.assert_called_with("analysis_note_signals")
    call_args = mock_store._client.table.return_value.upsert.call_args
    rows = call_args[0][0]
    assert len(rows) == 2
    assert rows[0] == {"analysis_note_id": "note-1", "signal_id": "sig-1", "role": "supports"}
    assert rows[1] == {"analysis_note_id": "note-1", "signal_id": "sig-2", "role": "supports"}
    assert call_args[1]["on_conflict"] == "analysis_note_id,signal_id"


def test_link_note_to_signals_noop_for_empty(mock_store):
    link_note_to_signals(mock_store, "note-1", [])
    mock_store._client.table.assert_not_called()


def test_upsert_dossier_keyed_by_company_id(mock_store):
    dossier = {
        "company_id": "cid-1",
        "summary_md": "## О компании\n...",
        "sections": {"company": "..."},
        "audit_md": "## Аудит\n...",
        "table_fields": {"segment": "medical-imaging"},
        "version": "v1",
    }
    upsert_dossier(mock_store, dossier)
    mock_store._client.table.assert_called_with("dossiers")
    call_args = mock_store._client.table.return_value.upsert.call_args
    row = call_args[0][0]
    assert row["company_id"] == "cid-1"
    assert row["summary_md"].startswith("## О компании")
    assert call_args[1]["on_conflict"] == "company_id"


def test_get_dossier_returns_single_or_none(mock_store):
    mock_store._client.table.return_value.execute.return_value = MagicMock(data=[])
    assert get_dossier(mock_store, "cid-1") is None

    mock_store._client.table.return_value.execute.return_value = MagicMock(
        data=[{"company_id": "cid-1"}]
    )
    result = get_dossier(mock_store, "cid-1")
    assert result["company_id"] == "cid-1"


def test_cli_run_upsert_analysis_note(mock_store, monkeypatch):
    import io
    import json as _json

    from dossier_store import _build_parser, _run

    payload = {"company_id": "cid-1", "section": "product", "facts": {"x": 1}}
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(payload)))
    args = _build_parser().parse_args(["--upsert-analysis-note"])
    _run(args, mock_store)
    mock_store._client.table.assert_called_with("analysis_notes")


def test_cli_run_list_analysis_notes(mock_store, capsys):
    from dossier_store import _build_parser, _run

    args = _build_parser().parse_args(["--list-analysis-notes", "cid-1"])
    _run(args, mock_store)
    mock_store._client.table.assert_called_with("analysis_notes")


def test_cli_run_upsert_dossier(mock_store, monkeypatch):
    import io
    import json as _json

    from dossier_store import _build_parser, _run

    payload = {"company_id": "cid-1", "summary_md": "## О компании\n..."}
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(payload)))
    args = _build_parser().parse_args(["--upsert-dossier"])
    _run(args, mock_store)
    mock_store._client.table.assert_called_with("dossiers")


def test_cli_run_get_dossier(mock_store):
    from dossier_store import _build_parser, _run

    args = _build_parser().parse_args(["--get-dossier", "cid-1"])
    _run(args, mock_store)
    mock_store._client.table.assert_called_with("dossiers")
