"""Канонический список статусов 5-этапного пайплайна."""

from __future__ import annotations

from models import ALL_STATUSES


def test_all_pipeline_statuses_present():
    expected = (
        "discovered",
        "relevant",
        "not_relevant",
        "manual_review",
        "triaged_out",
        "qualified",
        "sources_gathered",
        "analyzed",
        "dossier_ready",
        "needs_update",
        "pending_verify",
    )
    for status in expected:
        assert status in ALL_STATUSES


def test_all_statuses_is_tuple_of_str():
    assert isinstance(ALL_STATUSES, tuple)
    assert all(isinstance(s, str) for s in ALL_STATUSES)
