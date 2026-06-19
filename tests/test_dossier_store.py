"""dossier_store tests for analysis_records and typed dossiers."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dossier_store import (
    get_dossier,
    get_research_records,
    link_analysis_to_research,
    link_dossier_to_analysis,
    upsert_analysis_record,
    upsert_dossier,
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
    table_mock.limit.return_value = table_mock
    table_mock.execute.return_value = MagicMock(data=[])
    return store


def test_upsert_analysis_record_keyed_by_company_id(mock_store):
    note = {
        "company_id": "cid-1",
        "section": "product",
        "facts": {"start_date": "2021"},
        "confidence": "high",
        "model": "claude",
        "version": "v1",
    }
    upsert_analysis_record(mock_store, note)
    mock_store._client.table.assert_called_with("analysis_records")
    call_args = mock_store._client.table.return_value.upsert.call_args
    row = call_args[0][0]
    assert row["company_id"] == "cid-1"
    assert row["section"] == "product"
    assert row["facts"] == {"start_date": "2021"}
    assert call_args[1]["on_conflict"] == "company_id,section,version"


def test_link_analysis_to_research_inserts_rows(mock_store):
    link_analysis_to_research(mock_store, "ar-1", ["rr-1", "rr-2"], role="supports")
    mock_store._client.table.assert_called_with("analysis_links")
    call_args = mock_store._client.table.return_value.upsert.call_args
    rows = call_args[0][0]
    assert len(rows) == 2
    assert rows[0] == {
        "analysis_record_id": "ar-1",
        "research_record_id": "rr-1",
        "role": "supports",
        "note": None,
    }
    assert call_args[1]["on_conflict"] == "analysis_record_id,research_record_id"


def test_upsert_dossier_writes_typed_and_narrative(mock_store):
    upsert_dossier(
        mock_store,
        {
            "company_id": "cid",
            "funding_stage": "seed",
            "icp_fit": "strong",
            "section_summaries": {"financials": "Raised seed."},
            "summary_md": "# Rad AI\nSeed-stage.",
        },
    )
    row = mock_store._client.table.return_value.upsert.call_args[0][0]
    assert row["funding_stage"] == "seed"
    assert row["icp_fit"] == "strong"
    assert row["summary_md"].startswith("# Rad AI")
    assert "sections" not in row
    assert "table_fields" not in row


def test_get_dossier_returns_single_or_none(mock_store):
    mock_store._client.table.return_value.execute.return_value = MagicMock(data=[])
    assert get_dossier(mock_store, "cid-1") is None

    mock_store._client.table.return_value.execute.return_value = MagicMock(
        data=[{"company_id": "cid-1"}]
    )
    result = get_dossier(mock_store, "cid-1")
    assert result["company_id"] == "cid-1"


def test_link_dossier_to_analysis_one_row_per_record(mock_store):
    link_dossier_to_analysis(
        mock_store,
        "cid",
        ["ar1", "ar2"],
        {"ar1": "funding_stage", "ar2": "financials"},
    )
    rows = mock_store._client.table.return_value.upsert.call_args[0][0]
    assert {r["analysis_record_id"] for r in rows} == {"ar1", "ar2"}
    assert {r["contributed_to"] for r in rows} == {"funding_stage", "financials"}


def test_get_research_records_delegates_to_store(mock_store):
    mock_store.get_research_records_for_analysis.return_value = [{"id": "rr-1"}]
    assert get_research_records(mock_store, "cid") == [{"id": "rr-1"}]


def test_cli_run_upsert_analysis_record(mock_store, monkeypatch):
    import io
    import json as _json

    from dossier_store import _build_parser, _run

    payload = {"company_id": "cid-1", "section": "product", "facts": {"x": 1}}
    monkeypatch.setattr("sys.stdin", io.StringIO(_json.dumps(payload)))
    args = _build_parser().parse_args(["--upsert-analysis-record"])
    _run(args, mock_store)
    mock_store._client.table.assert_called_with("analysis_records")


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
