"""Tests for the Telegram /run wizard state transitions."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.dialog import apply_callback


def test_toggling_stage_from_full_starts_new_subset() -> None:
    _, draft = apply_callback("stages", {"stages": "full"}, "stages_toggle:discovery")

    assert draft["stages"] == ["discovery"]
