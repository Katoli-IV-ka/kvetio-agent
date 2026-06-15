"""Tests for RunConfig validation and status machine."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "bot"))

from bot.runs import RunConfig, RunsStore, VALID_SEGMENTS


# ── RunConfig validation ──────────────────────────────────────────────────────

class TestRunConfigValidation:
    def _valid(self, **kwargs) -> RunConfig:
        defaults = {
            "segments": ["medical-imaging"],
            "limit_per_segment": 30,
            "stages": "full",
        }
        defaults.update(kwargs)
        return RunConfig(**defaults)

    def test_valid_full_config(self) -> None:
        cfg = self._valid()
        cfg.validate()  # no error

    def test_valid_partial_stages(self) -> None:
        cfg = self._valid(stages=["discovery", "relevance"])
        cfg.validate()

    def test_all_segments_valid(self) -> None:
        cfg = self._valid(segments=list(VALID_SEGMENTS))
        cfg.validate()

    def test_empty_segments_raises(self) -> None:
        cfg = self._valid(segments=[])
        with pytest.raises(ValueError, match="segments"):
            cfg.validate()

    def test_unknown_segment_raises(self) -> None:
        cfg = self._valid(segments=["unknown-segment"])
        with pytest.raises(ValueError, match="unknown segments"):
            cfg.validate()

    def test_limit_zero_raises(self) -> None:
        cfg = self._valid(limit_per_segment=0)
        with pytest.raises(ValueError, match="limit_per_segment"):
            cfg.validate()

    def test_limit_over_200_raises(self) -> None:
        cfg = self._valid(limit_per_segment=201)
        with pytest.raises(ValueError, match="limit_per_segment"):
            cfg.validate()

    def test_unknown_stage_raises(self) -> None:
        cfg = self._valid(stages=["discovery", "nonexistent"])
        with pytest.raises(ValueError, match="unknown stages"):
            cfg.validate()

    def test_invalid_trigger_type_raises(self) -> None:
        cfg = self._valid(trigger_type="webhook")  # type: ignore
        with pytest.raises(ValueError, match="trigger_type"):
            cfg.validate()

    def test_to_dict_roundtrip(self) -> None:
        cfg = RunConfig(
            segments=["robotics-ai", "generative-ai"],
            limit_per_segment=50,
            stages=["discovery", "relevance"],
            dry_run=True,
            notion_sync=False,
            triggered_by="chat:123",
            trigger_type="manual",
        )
        d = cfg.to_dict()
        restored = RunConfig.from_dict(d)
        assert restored.segments == cfg.segments
        assert restored.limit_per_segment == cfg.limit_per_segment
        assert restored.stages == cfg.stages
        assert restored.dry_run is True
        assert restored.notion_sync is False


# ── Status machine ────────────────────────────────────────────────────────────

def _make_store() -> tuple[RunsStore, MagicMock]:
    client = MagicMock()
    store = RunsStore(client)
    return store, client


class TestRunsStoreStatusMachine:
    def test_enqueue_inserts_queued(self) -> None:
        store, client = _make_store()
        client.table.return_value.insert.return_value.execute.return_value.data = [
            {"id": "abc-123"}
        ]
        cfg = RunConfig(
            segments=["medical-imaging"], limit_per_segment=10, stages="full"
        )
        run_id = store.enqueue(cfg, trigger_type="manual", triggered_by="chat:1")
        assert run_id == "abc-123"
        insert_call = client.table.return_value.insert
        row = insert_call.call_args[0][0]
        assert row["status"] == "queued"
        assert row["trigger_type"] == "manual"

    def test_try_start_returns_none_when_running_exists(self) -> None:
        store, client = _make_store()
        # Simulate active running run
        client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"id": "run-1"}
        ]
        result = store.try_start_next()
        assert result is None

    def test_try_start_returns_none_when_no_queued(self) -> None:
        store, client = _make_store()
        mock_table = client.table.return_value
        # No running
        mock_table.select.return_value.eq.return_value.execute.return_value.data = []
        # No queued
        mock_table.select.return_value.eq.return_value.order.return_value.limit.return_value.execute.return_value.data = []
        # _expire_stale_runs also uses table
        mock_table.update.return_value.eq.return_value.eq.return_value.lt.return_value.execute.return_value.data = []
        result = store.try_start_next()
        assert result is None

    def test_cancel_queued(self) -> None:
        store, client = _make_store()
        mock_chain = (
            client.table.return_value.update.return_value.eq.return_value.in_.return_value.execute
        )
        mock_chain.return_value.data = [{"id": "run-1"}]
        assert store.cancel("run-1") is True

    def test_cancel_returns_false_when_not_cancellable(self) -> None:
        store, client = _make_store()
        mock_chain = (
            client.table.return_value.update.return_value.eq.return_value.in_.return_value.execute
        )
        mock_chain.return_value.data = []
        assert store.cancel("run-done") is False

    def test_finish_updates_status(self) -> None:
        store, client = _make_store()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []
        store.finish("run-1", {"found": 5})
        update_call = client.table.return_value.update
        row = update_call.call_args[0][0]
        assert row["status"] == "succeeded"
        assert row["summary"] == {"found": 5}

    def test_fail_updates_status(self) -> None:
        store, client = _make_store()
        client.table.return_value.update.return_value.eq.return_value.execute.return_value.data = []
        store.fail("run-1", "something broke")
        update_call = client.table.return_value.update
        row = update_call.call_args[0][0]
        assert row["status"] == "failed"
        assert "something broke" in row["error"]
