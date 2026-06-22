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


# ---- shared fixtures -------------------------------------------------------

_COMPANY = {
    "id": "company-uuid-1",
    "name": "Acme AI",
    "description": "Builds vision models",
    "notion_page_id": "page-1",
}

_DOSSIER = {
    "company_id": "company-uuid-1",
    "product_category": "Computer Vision",
    "ai_use_case": "Object detection",
    "funding_stage": "Series B",
    "team_size_estimate": "50-100",
    "summary_md": "Great company.",
    "audit_md": None,
}

_ANALYSIS = {
    "company": {
        "section": "company",
        "facts": {
            "founded_year": "2019",
            "hq": "San Francisco",
            "offices": ["New York"],
            "market_position": "Leader in CV",
            "secondary_activities": "Data labeling",
        },
    },
    "product": {
        "section": "product",
        "facts": {
            "target_market": "Enterprise",
            "problem_solved": "Manual image review",
            "technologies": "PyTorch, ONNX",
            "features": ["Real-time detection", "Edge deployment"],
            "data_needs": "Labeled image datasets",
            "challenges": "Edge constraints",
        },
    },
    "collaboration": {
        "section": "collaboration",
        "facts": {
            "partners": [
                {"type": "Data", "company": "Scale AI", "role": "Labeling provider"}
            ],
            "note": "Open to partnerships",
        },
    },
    "financials": {
        "section": "financials",
        "facts": {
            "rounds": [
                {"year": "2023", "round": "Series B", "amount": "$30M", "investors": "a16z"}
            ],
            "valuation": "$200M",
            "public_status": "Private",
            "metrics": ["ARR: $5M"],
            "dynamics": "Strong growth",
        },
    },
    "audit": {
        "section": "audit",
        "facts": {
            "overview": "Solid company",
            "claims_vs_reality": [
                {"claim": "Market leader", "reality": "Top 3 player"}
            ],
            "risks": ["Competition from big tech"],
            "forecast": "Positive",
            "why_interesting": ["Strong team"],
            "entry_point": "CTO outreach",
            "pitch_angle": "Cost reduction",
            "next_step": "Schedule demo",
        },
    },
}

_CONTACTS = [
    {
        "id": "c1",
        "company_id": "company-uuid-1",
        "contact_type": "person",
        "name": "John Doe",
        "info": "CEO, tier 1 — data partnerships",
        "linkedin_url": "https://linkedin.com/in/johndoe",
        "notion_page_id": "contact-page-1",
    },
    {
        "id": "c2",
        "company_id": "company-uuid-1",
        "contact_type": "person",
        "name": "Jane Smith",
        "info": "CTO — technical decisions",
        "linkedin_url": None,
        "notion_page_id": None,
    },
]

_NEWS = [
    {
        "id": "n1",
        "company_id": "company-uuid-1",
        "record_type": "news",
        "title": "Acme raises Series B",
        "summary": "Raised $30M led by a16z",
        "url": "https://techcrunch.com/acme",
        "observed_at": "2023-06-15",
        "payload": {},
    }
]


# ---- О компании -----------------------------------------------------------

def test_company_section_is_callout():
    block = nr.build_company_section(_COMPANY, _DOSSIER, _ANALYSIS, _CONTACTS)
    assert block is not None
    assert block["type"] == "callout"
    assert block["callout"]["icon"]["emoji"] == "🏢"


def test_company_section_starts_with_heading2_and_divider():
    block = nr.build_company_section(_COMPANY, _DOSSIER, _ANALYSIS, _CONTACTS)
    children = block["callout"]["children"]
    assert children[0]["type"] == "heading_2"
    assert children[1]["type"] == "divider"


def test_company_section_includes_known_fields():
    block = nr.build_company_section(_COMPANY, _DOSSIER, _ANALYSIS, _CONTACTS)
    children = block["callout"]["children"]
    texts = [
        seg["text"]["content"]
        for b in children
        if b["type"] == "paragraph"
        for seg in b["paragraph"]["rich_text"]
        if seg.get("type") == "text"
    ]
    assert any("San Francisco" in t for t in texts)
    assert any("2019" in t for t in texts)


def test_company_section_leaders_paragraph_with_mention():
    block = nr.build_company_section(_COMPANY, _DOSSIER, _ANALYSIS, _CONTACTS)
    children = block["callout"]["children"]
    paragraphs = [b for b in children if b["type"] == "paragraph"]
    # find the leaders paragraph (contains mention)
    leader_paras = [
        p for p in paragraphs
        if any(seg.get("type") == "mention" for seg in p["paragraph"]["rich_text"])
    ]
    assert len(leader_paras) == 1
    rt = leader_paras[0]["paragraph"]["rich_text"]
    # contact c1 has notion_page_id -> mention; c2 does not
    mentions = [seg for seg in rt if seg.get("type") == "mention"]
    assert len(mentions) == 1
    assert mentions[0]["mention"]["page"]["id"] == "contact-page-1"


def test_company_section_returns_none_when_all_empty():
    block = nr.build_company_section(
        {"id": "x", "name": None, "description": None},
        None,
        {},
        [],
    )
    assert block is None


def test_product_section_is_callout():
    sections = nr.build_product_sections(_DOSSIER, _ANALYSIS)
    assert len(sections) >= 1
    assert sections[0]["type"] == "callout"
    assert sections[0]["callout"]["icon"]["emoji"] == "📦"


def test_product_section_starts_with_heading2_divider():
    sections = nr.build_product_sections(_DOSSIER, _ANALYSIS)
    children = sections[0]["callout"]["children"]
    assert children[0]["type"] == "heading_2"
    assert children[1]["type"] == "divider"


def test_product_section_includes_features_as_bullets():
    sections = nr.build_product_sections(_DOSSIER, _ANALYSIS)
    children = sections[0]["callout"]["children"]
    bullet_types = [b["type"] for b in children]
    assert "bulleted_list_item" in bullet_types


def test_product_section_no_dossier_returns_empty():
    sections = nr.build_product_sections(None, {})
    assert sections == []
