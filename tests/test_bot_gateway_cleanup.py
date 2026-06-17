from __future__ import annotations

from bot.gateway import _help_text, _start_text


def test_start_text_exposes_run_without_presets_or_quickrun() -> None:
    text = _start_text()
    assert "/run" in text
    assert "/pre" + "sets" not in text
    assert "/quick" + "run" not in text


def test_help_text_exposes_run_without_presets_or_quickrun() -> None:
    text = _help_text()
    assert "/run" in text
    assert "/pre" + "sets" not in text
    assert "/quick" + "run" not in text
