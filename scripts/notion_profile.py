"""Company Notion profile builder.

Pure functions — zero I/O. Takes DB rows, returns flat profile dicts
ready for to_notion_property mapping.
"""
from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).parent.parent
POTENTIAL_DATA_PATH = _REPO_ROOT / "config" / "potential_data.yaml"


def load_potential_cfg(path: Path = POTENTIAL_DATA_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _format_amount(usd: float | int) -> str:
    """Format USD amount as compact string: $12M, $3.5M, $750K, $1B."""
    if usd >= 1_000_000_000:
        v = round(usd / 1_000_000_000, 1)
        return f"${v:g}B"
    if usd >= 1_000_000:
        v = round(usd / 1_000_000, 1)
        return f"${v:g}M"
    if usd >= 1_000:
        v = round(usd / 1_000, 1)
        return f"${v:g}K"
    return f"${int(usd)}"


def _compute_funding_info(stage: str | None, amount_usd: float | None) -> str | None:
    amount_str = _format_amount(amount_usd) if amount_usd is not None else None
    if stage and amount_str:
        return f"{stage} · {amount_str}"
    if stage:
        return stage
    if amount_str:
        return amount_str
    return None
