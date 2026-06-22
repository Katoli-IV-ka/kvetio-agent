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
