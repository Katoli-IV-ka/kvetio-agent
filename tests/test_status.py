"""Canonical company statuses for the cleaned pipeline."""

from __future__ import annotations

from models import ALL_STATUSES


def test_all_pipeline_statuses_match_cleanup_design():
    assert ALL_STATUSES == (
        "discovered",
        "relevant",
        "not_relevant",
        "manual_review",
        "sources_gathered",
        "analyzed",
        "dossier_ready",
        "data_partner",
    )


def test_removed_monitor_statuses_are_not_pipeline_statuses():
    assert "triaged_out" not in ALL_STATUSES
    assert "qualified" not in ALL_STATUSES
    assert "needs" + "_update" not in ALL_STATUSES
    assert "pending" + "_verify" not in ALL_STATUSES


def test_all_statuses_is_tuple_of_str():
    assert isinstance(ALL_STATUSES, tuple)
    assert all(isinstance(s, str) for s in ALL_STATUSES)
