"""Tests for the Telegram /run wizard state transitions."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.config import DEFAULT_LIMIT_PER_SEGMENT
from bot.dialog import (
    apply_callback,
    apply_encoded_callback,
    build_enrich_step_message,
    build_step_message,
    decode_callback,
)


def test_toggling_stage_from_full_starts_new_subset() -> None:
    _, draft = apply_callback("stages", {"stages": "full"}, "stages_toggle:discovery")

    assert draft["stages"] == ["discovery"]


def test_run_buttons_include_compact_state_in_callback_data() -> None:
    _, keyboard = build_step_message(
        "segments",
        {
            "segments": ["medical-imaging"],
            "limit_per_segment": DEFAULT_LIMIT_PER_SEGMENT,
            "stages": "full",
            "dry_run": False,
            "notion_sync": True,
        },
    )

    callback_data = keyboard[0][0]["callback_data"]

    assert callback_data.startswith("r1:")
    assert len(callback_data.encode("utf-8")) <= 64
    decoded_draft, action = decode_callback(callback_data)
    assert decoded_draft["segments"] == ["medical-imaging"]
    assert decoded_draft["limit_per_segment"] == DEFAULT_LIMIT_PER_SEGMENT
    assert decoded_draft["stages"] == "full"
    assert decoded_draft["dry_run"] is False
    assert decoded_draft["notion_sync"] is True
    assert action == "st0"


def test_apply_encoded_callback_toggles_segment_without_store() -> None:
    _, keyboard = build_step_message(
        "segments",
        {
            "segments": [],
            "limit_per_segment": DEFAULT_LIMIT_PER_SEGMENT,
            "stages": "full",
            "dry_run": False,
            "notion_sync": True,
        },
    )

    next_step, draft = apply_encoded_callback(keyboard[0][0]["callback_data"])

    assert next_step == "segments"
    assert draft["segments"] == ["medical-imaging"]


def test_apply_encoded_callback_can_confirm_run_without_store() -> None:
    _, keyboard = build_step_message(
        "confirm",
        {
            "segments": ["medical-imaging"],
            "limit_per_segment": 10,
            "stages": ["discovery", "relevance"],
            "dry_run": True,
            "notion_sync": False,
        },
    )

    next_step, draft = apply_encoded_callback(keyboard[0][0]["callback_data"])

    assert next_step == "done"
    assert draft == {
        "segments": ["medical-imaging"],
        "limit_per_segment": 10,
        "stages": ["discovery", "relevance"],
        "dry_run": True,
        "notion_sync": False,
    }


def test_enrich_segments_step_allows_empty_selection_and_marks_mode() -> None:
    text, keyboard = build_enrich_step_message(
        "segments",
        {
            "run_mode": "enrich_existing",
            "segments": [],
            "limit_per_segment": 30,
            "stages": ["relevance", "scoring", "enrichment", "analysis", "conclusions"],
            "dry_run": False,
            "notion_sync": True,
        },
    )

    assert "Пустой выбор = все компании в БД" in text
    callback_data = keyboard[-1][1]["callback_data"]
    decoded_draft, action = decode_callback(callback_data)
    assert decoded_draft["run_mode"] == "enrich_existing"
    assert decoded_draft["segments"] == []
    assert action == "sn"


def test_enrich_stages_step_excludes_discovery_and_defaults_to_all_enrich_stages() -> None:
    text, keyboard = build_enrich_step_message(
        "stages",
        {
            "run_mode": "enrich_existing",
            "segments": [],
            "limit_per_segment": 30,
            "stages": ["relevance", "scoring", "enrichment", "analysis", "conclusions"],
            "dry_run": False,
            "notion_sync": True,
        },
    )

    assert "`discovery` пропускается" in text
    button_texts = [button["text"] for row in keyboard for button in row]
    assert all("discovery" not in button for button in button_texts)
    assert "✅ relevance" in button_texts
    assert "✅ conclusions" in button_texts


def test_enrich_confirm_shows_all_segments_label() -> None:
    text, _ = build_enrich_step_message(
        "confirm",
        {
            "run_mode": "enrich_existing",
            "segments": [],
            "limit_per_segment": 30,
            "stages": ["enrichment", "analysis", "conclusions"],
            "dry_run": False,
            "notion_sync": True,
        },
    )

    assert "Дозаполнение существующих компаний" in text
    assert "Сегменты: <b>все сегменты</b>" in text


def test_apply_encoded_callback_preserves_enrich_mode() -> None:
    _, keyboard = build_enrich_step_message(
        "confirm",
        {
            "run_mode": "enrich_existing",
            "segments": [],
            "limit_per_segment": 30,
            "stages": ["enrichment", "analysis", "conclusions"],
            "dry_run": False,
            "notion_sync": True,
        },
    )

    next_step, draft = apply_encoded_callback(keyboard[0][0]["callback_data"])

    assert next_step == "done"
    assert draft["run_mode"] == "enrich_existing"
