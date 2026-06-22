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


def _compute_potential_data(
    icp_segment: str | None,
    status: str | None,
    potential_cfg: dict,
) -> list[str]:
    segments = potential_cfg.get("segments", {})
    status_overrides = potential_cfg.get("status_overrides", {})
    base = list(segments.get(icp_segment or "", []))
    overrides = list(status_overrides.get(status or "", []))
    seen: set[str] = set()
    result: list[str] = []
    for item in base + overrides:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _compute_last_info_update(
    company: dict,
    dossier: dict | None,
    aggregates: dict,
) -> str | None:
    candidates: list[str] = []
    if company.get("updated_at"):
        candidates.append(str(company["updated_at"])[:10])
    if dossier and dossier.get("updated_at"):
        candidates.append(str(dossier["updated_at"])[:10])
    if aggregates.get("last_research_created_at"):
        candidates.append(str(aggregates["last_research_created_at"])[:10])
    if aggregates.get("last_contact_updated_at"):
        candidates.append(str(aggregates["last_contact_updated_at"])[:10])
    return max(candidates) if candidates else None


def build_company_notion_profile(
    company: dict,
    dossier: dict | None,
    aggregates: dict,
    potential_cfg: dict,
    translator=None,
) -> dict:
    """Pure function. Returns flat profile dict for forward mapping.

    Includes both presentation keys (matching db_column from YAML) and
    service keys required for writeback (id, domain, notion_page_id, notion_synced_at).
    """
    d = dossier or {}

    description = company.get("description")
    if translator and description:
        description = translator.translate(description)

    return {
        # db_column keys (match notion_mapping.yaml fields)
        "name": company.get("name"),
        "website": company.get("website"),
        "linkedin_url": company.get("linkedin_url"),
        "icp_segment": company.get("icp_segment"),
        "status": company.get("status"),
        "description": description,
        "hq_country": company.get("hq_country"),
        "team_size_estimate": d.get("team_size_estimate"),
        "funding_info": _compute_funding_info(d.get("funding_stage"), d.get("funding_amount_usd")),
        "potential_data": _compute_potential_data(
            company.get("icp_segment"), company.get("status"), potential_cfg
        ),
        "last_info_update": _compute_last_info_update(company, dossier, aggregates),
        # service keys — required for writeback and body render
        "id": company.get("id"),
        "domain": company.get("domain"),
        "notion_page_id": company.get("notion_page_id"),
        "notion_synced_at": company.get("notion_synced_at"),
    }
