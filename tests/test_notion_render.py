"""Unit tests for notion_render: block builders and section renderers."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import notion_render as nr


def test_heading_1_block():
    b = nr.heading_1_block("Dossier")
    assert b["type"] == "heading_1"
    assert b["heading_1"]["rich_text"][0]["text"]["content"] == "Dossier"


def test_heading_2_block():
    b = nr.heading_2_block("О компании")
    assert b["type"] == "heading_2"
    assert b["heading_2"]["rich_text"][0]["text"]["content"] == "О компании"


def test_heading_3_block():
    b = nr.heading_3_block("Вывод")
    assert b["type"] == "heading_3"
    assert b["heading_3"]["rich_text"][0]["text"]["content"] == "Вывод"


def test_divider_block():
    b = nr.divider_block()
    assert b["type"] == "divider"
    assert b["divider"] == {}


def test_empty_block():
    b = nr.empty_block()
    assert b["type"] == "paragraph"
    assert b["paragraph"]["rich_text"] == []


def test_quote_block():
    b = nr.quote_block("text here")
    assert b["type"] == "quote"
    assert b["quote"]["rich_text"][0]["text"]["content"] == "text here"


def test_label_segment_format():
    seg = nr.label_segment("Название:")
    assert seg["type"] == "text"
    assert seg["text"]["content"] == "Название:"
    ann = seg["annotations"]
    assert ann["bold"] is True
    assert ann["code"] is True
    assert ann["color"] == "yellow"


def test_field_block_returns_none_for_none_value():
    assert nr.field_block("Поле:", None) is None


def test_field_block_returns_none_for_empty_string():
    assert nr.field_block("Поле:", "") is None
    assert nr.field_block("Поле:", "   ") is None


def test_field_block_structure():
    b = nr.field_block("Название:", "Acme")
    assert b["type"] == "paragraph"
    rt = b["paragraph"]["rich_text"]
    assert len(rt) == 2
    assert rt[0]["annotations"]["bold"] is True
    assert rt[0]["annotations"]["code"] is True
    assert rt[0]["annotations"]["color"] == "yellow"
    assert rt[0]["text"]["content"] == "Название:"
    assert rt[1]["text"]["content"] == " Acme"


def test_callout_block_structure():
    children = [nr.heading_2_block("Test"), nr.divider_block()]
    b = nr.callout_block("🏢", children)
    assert b["type"] == "callout"
    co = b["callout"]
    assert co["rich_text"] == []
    assert co["icon"] == {"type": "emoji", "emoji": "🏢"}
    assert co["color"] == "default"
    assert co["children"] == children
