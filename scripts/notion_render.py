"""Notion page body renderer.

Builds block payloads from Supabase data. Zero network I/O — all functions
are pure builders that return Notion block dicts.
"""

from __future__ import annotations

from datetime import date


# ---------------------------------------------------------------------------
# Primitive block builders
# ---------------------------------------------------------------------------

def heading_1_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_1",
        "heading_1": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def heading_2_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def heading_3_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def divider_block() -> dict:
    return {"object": "block", "type": "divider", "divider": {}}


def empty_block() -> dict:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": []},
    }


def quote_block(text: str) -> dict:
    return {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


# ---------------------------------------------------------------------------
# Rich-text segments
# ---------------------------------------------------------------------------

def label_segment(text: str) -> dict:
    return {
        "type": "text",
        "text": {"content": text},
        "annotations": {"bold": True, "code": True, "color": "yellow"},
    }


def _value_segment(text: str) -> dict:
    return {"type": "text", "text": {"content": text}, "annotations": {}}


def field_block(label: str, value) -> dict | None:
    """Paragraph with bold+code+yellow label + plain value. Returns None if value is empty."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [
                label_segment(label),
                _value_segment(f" {text}"),
            ]
        },
    }


def callout_block(emoji: str, children: list[dict]) -> dict:
    return {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [],
            "icon": {"type": "emoji", "emoji": emoji},
            "color": "default",
            "children": children,
        },
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_LEADER_KEYWORDS = ("CEO", "CTO", "CPO", "VP", "Head", "Founder",
                    "Co-Founder", "President", "Director")


def _bulleted_text_block(items: list[str]) -> list[dict]:
    """Each item becomes a bulleted_list_item block."""
    blocks = []
    for item in items:
        if item:
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": str(item)}}]
                },
            })
    return blocks


def _table_block(columns: list[str], rows: list[list]) -> dict:
    """Build a simple Notion table block."""
    def _cell(value) -> list:
        if isinstance(value, dict) and value.get("_mention_page_id"):
            return [{"type": "mention", "mention": {"type": "page",
                     "page": {"id": value["_mention_page_id"]}}}]
        return [{"type": "text", "text": {"content": str(value or "")}}]

    header_row = {
        "object": "block",
        "type": "table_row",
        "table_row": {"cells": [_cell(c) for c in columns]},
    }
    data_rows = [
        {
            "object": "block",
            "type": "table_row",
            "table_row": {"cells": [_cell(v) for v in row]},
        }
        for row in rows
    ]
    return {
        "object": "block",
        "type": "table",
        "table": {
            "table_width": len(columns),
            "has_column_header": True,
            "has_row_header": False,
            "children": [header_row, *data_rows],
        },
    }


def _leaders_paragraph(contacts: list[dict]) -> dict | None:
    """Paragraph with hard_break lines for leadership contacts."""
    leaders = [
        c for c in contacts
        if c.get("contact_type") == "person"
        and any(kw.lower() in (c.get("info") or "").lower() for kw in _LEADER_KEYWORDS)
    ]
    if not leaders:
        return None

    rich_text: list[dict] = [label_segment("Руководство:")]
    for c in leaders:
        name = c.get("name") or ""
        info = c.get("info") or ""
        rich_text += [
            {"type": "text", "text": {"content": "\n- "}, "annotations": {}},
            {"type": "text", "text": {"content": f"{info} — {name}" if info else name},
             "annotations": {"bold": True}},
        ]
        if c.get("notion_page_id"):
            rich_text.append({
                "type": "mention",
                "mention": {"type": "page", "page": {"id": c["notion_page_id"]}},
            })
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": rich_text},
    }


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def build_company_section(
    company: dict,
    dossier: dict | None,
    analysis: dict[str, dict],
    contacts: list[dict],
) -> dict | None:
    """Build О компании callout. Returns None if all fields are empty."""
    facts = (analysis.get("company") or {}).get("facts") or {}
    d = dossier or {}

    fields: list[dict] = []

    if f := field_block("Полное название:", company.get("name")):
        fields.append(f)
    if f := field_block("Год основания:", facts.get("founded_year")):
        fields.append(f)
    if f := field_block("Штаб-квартира:", facts.get("hq")):
        fields.append(f)

    offices = facts.get("offices")
    if offices:
        office_text = ", ".join(str(o) for o in offices) if isinstance(offices, list) else str(offices)
        if b := field_block("Дополнительные офисы:", office_text):
            fields.append(b)

    if f := field_block("Размер компании:", d.get("team_size_estimate")):
        fields.append(f)

    if leaders_block := _leaders_paragraph(contacts):
        fields.append(leaders_block)

    if f := field_block("Основное направление:", company.get("description")):
        fields.append(f)
    if f := field_block("Второстепенные направления:", facts.get("secondary_activities")):
        fields.append(f)
    if f := field_block("Положение на рынке:", facts.get("market_position")):
        fields.append(f)

    if not fields:
        return None

    children = [heading_2_block("О компании"), divider_block(), *fields]
    return callout_block("🏢", children)
