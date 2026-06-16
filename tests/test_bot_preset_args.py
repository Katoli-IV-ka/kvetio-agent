"""Tests for parsing /presets save command arguments."""

from __future__ import annotations

import pytest

from bot.preset_args import parse_preset_save_args


def test_parse_preset_save_args_builds_config() -> None:
    name, config, is_default = parse_preset_save_args(
        [
            "save",
            "smoke",
            "segments=medical-imaging,generative-ai",
            "limit=10",
            "stages=discovery,relevance",
            "dry_run=true",
            "notion_sync=false",
            "default=true",
        ]
    )

    assert name == "smoke"
    assert config == {
        "segments": ["medical-imaging", "generative-ai"],
        "limit_per_segment": 10,
        "stages": ["discovery", "relevance"],
        "dry_run": True,
        "notion_sync": False,
    }
    assert is_default is True


def test_parse_preset_save_args_accepts_full_stages() -> None:
    _, config, _ = parse_preset_save_args(
        [
            "save",
            "full",
            "segments=medical-imaging",
            "limit=30",
            "stages=full",
        ]
    )

    assert config["stages"] == "full"
    assert config["dry_run"] is False
    assert config["notion_sync"] is True


def test_parse_preset_save_args_defaults_to_five_companies_per_segment() -> None:
    _, config, _ = parse_preset_save_args(
        [
            "save",
            "default-limit",
            "segments=medical-imaging",
            "stages=full",
        ]
    )

    assert config["limit_per_segment"] == 5


def test_parse_preset_save_args_rejects_invalid_config() -> None:
    with pytest.raises(ValueError, match="unknown segments"):
        parse_preset_save_args(
            [
                "save",
                "bad",
                "segments=unknown",
                "limit=30",
                "stages=full",
            ]
        )


def test_parse_preset_save_args_requires_name() -> None:
    with pytest.raises(ValueError, match="Usage"):
        parse_preset_save_args(["save"])
