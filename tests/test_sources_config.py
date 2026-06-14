"""Sources registry: free включены, платные стабы выключены."""

from __future__ import annotations

from pathlib import Path

import yaml

CONFIG = Path(__file__).parent.parent / "config" / "sources.yaml"


def _sources() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["sources"]


def test_paid_stubs_disabled_tier_c():
    sources = _sources()
    for name in ("linkedin", "crunchbase", "similarweb"):
        assert sources[name]["enabled"] is False
        assert sources[name]["tier"] == "C"


def test_wayback_present():
    assert "wayback" in _sources()
