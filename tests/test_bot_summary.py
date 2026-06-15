"""Tests for pipeline summary collection and formatting."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.worker import _collect_summary, _format_summary_message


def _make_client(run_logs: list[dict], hot_leads: list[dict]) -> MagicMock:
    client = MagicMock()

    # run_logs query
    logs_chain = (
        client.table.return_value
        .select.return_value
        .gte.return_value
        .execute
    )
    logs_chain.return_value.data = run_logs

    # companies hot leads query
    hot_chain = (
        client.table.return_value
        .select.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute
    )
    hot_chain.return_value.data = hot_leads

    return client


SAMPLE_LOGS = [
    {"stage": "discovery", "segment": "medical-imaging", "status": "ok",
     "companies_found": 20, "companies_qualified": 8, "error": None},
    {"stage": "relevance", "segment": "medical-imaging", "status": "ok",
     "companies_found": 8, "companies_qualified": 5, "error": None},
    {"stage": "relevance", "segment": "robotics-ai", "status": "error",
     "companies_found": 0, "companies_qualified": 0, "error": "timeout"},
]

SAMPLE_HOT = [
    {"name": "Acme", "domain": "acme.ai", "score": 85, "score_bucket": "Hot",
     "icp_segment": "medical-imaging"},
    {"name": "BetaRobot", "domain": "betarobot.io", "score": 76, "score_bucket": "Hot",
     "icp_segment": "robotics-ai"},
]


class TestCollectSummary:
    def test_counts_found_and_qualified(self) -> None:
        client = _make_client(SAMPLE_LOGS, SAMPLE_HOT)
        config = {"segments": ["medical-imaging", "robotics-ai"], "limit_per_segment": 30}
        summary = _collect_summary(client, "run-abc", config, "2026-06-15T10:00:00+00:00")
        assert summary["found"] == 28
        assert summary["qualified"] == 13

    def test_counts_errors(self) -> None:
        client = _make_client(SAMPLE_LOGS, SAMPLE_HOT)
        config = {"segments": ["medical-imaging", "robotics-ai"], "limit_per_segment": 30}
        summary = _collect_summary(client, "run-abc", config, "2026-06-15T10:00:00+00:00")
        assert summary["errors"] == 1
        assert summary["error_details"][0]["stage"] == "relevance"
        assert summary["error_details"][0]["segment"] == "robotics-ai"

    def test_hot_leads_included(self) -> None:
        client = _make_client(SAMPLE_LOGS, SAMPLE_HOT)
        config = {"segments": ["medical-imaging"], "limit_per_segment": 30}
        summary = _collect_summary(client, "run-abc", config, "2026-06-15T10:00:00+00:00")
        assert len(summary["hot_leads"]) == 2
        assert summary["hot_leads"][0]["domain"] == "acme.ai"

    def test_no_logs_gives_zero_counts(self) -> None:
        client = _make_client([], [])
        config = {"segments": ["medical-imaging"], "limit_per_segment": 10}
        summary = _collect_summary(client, "run-empty", config, "2026-06-15T10:00:00+00:00")
        assert summary["found"] == 0
        assert summary["qualified"] == 0
        assert summary["errors"] == 0

    def test_invalid_started_at_doesnt_crash(self) -> None:
        client = _make_client([], [])
        config = {"segments": [], "limit_per_segment": 30}
        summary = _collect_summary(client, "run-x", config, "not-a-date")
        assert summary["found"] == 0


class TestFormatSummaryMessage:
    def _run(self, **kwargs) -> dict:
        defaults = {
            "id": "abc12345-1234-1234-1234-123456789012",
            "status": "succeeded",
            "trigger_type": "manual",
            "triggered_by": "chat:123",
            "started_at": "2026-06-15T10:00:00+00:00",
            "finished_at": "2026-06-15T10:14:22+00:00",
            "tg_chat_id": "123",
            "tg_message_id": None,
        }
        defaults.update(kwargs)
        return defaults

    def _summary(self, **kwargs) -> dict:
        defaults = {
            "run_id": "abc12345",
            "found": 47,
            "qualified": 12,
            "errors": 1,
            "error_details": [{"stage": "relevance", "segment": "robotics-ai", "error": "timeout"}],
            "hot_leads": [
                {"domain": "acme.ai", "score": 78, "icp_segment": "medical-imaging"},
                {"domain": "neuro.io", "score": 71, "icp_segment": "robotics-ai"},
            ],
            "segments": ["medical-imaging", "robotics-ai"],
        }
        defaults.update(kwargs)
        return defaults

    def test_contains_run_id_short(self) -> None:
        msg = _format_summary_message(self._run(), self._summary())
        assert "abc12345" in msg

    def test_contains_found_counts(self) -> None:
        msg = _format_summary_message(self._run(), self._summary())
        assert "47" in msg
        assert "12" in msg

    def test_warning_icon_when_errors(self) -> None:
        msg = _format_summary_message(self._run(), self._summary(errors=1))
        assert "⚠️" in msg

    def test_success_icon_when_no_errors(self) -> None:
        msg = _format_summary_message(self._run(), self._summary(errors=0, error_details=[]))
        assert "✅" in msg

    def test_hot_leads_section(self) -> None:
        msg = _format_summary_message(self._run(), self._summary())
        assert "acme.ai" in msg
        assert "neuro.io" in msg

    def test_error_details_section(self) -> None:
        msg = _format_summary_message(self._run(), self._summary())
        assert "relevance" in msg
        assert "timeout" in msg

    def test_duration_computed(self) -> None:
        msg = _format_summary_message(self._run(), self._summary())
        assert "14m 22s" in msg

    def test_no_hot_leads_section_when_empty(self) -> None:
        msg = _format_summary_message(self._run(), self._summary(hot_leads=[]))
        assert "Топ Hot" not in msg
