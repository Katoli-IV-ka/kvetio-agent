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
    "company_size": "50-100",
    "notion_page_id": "page-1",
}

_DOSSIER = {
    "company_id": "company-uuid-1",
    "product_category": "Computer Vision",
    "ai_use_case": "Object detection",
    "funding_stage": "Series B",
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


def test_collaboration_section_is_callout():
    block = nr.build_collaboration_section(_CONTACTS, _ANALYSIS)
    assert block is not None
    assert block["type"] == "callout"
    assert block["callout"]["icon"]["emoji"] == "🤝"


def test_collaboration_section_has_team_table():
    block = nr.build_collaboration_section(_CONTACTS, _ANALYSIS)
    children = block["callout"]["children"]
    table_blocks = [b for b in children if b["type"] == "table"]
    assert len(table_blocks) >= 1  # at least team table


def test_contacts_table_mention():
    """Contact cell contains mention when notion_page_id is present."""
    block = nr.build_collaboration_section(_CONTACTS, _ANALYSIS)
    children = block["callout"]["children"]
    tables = [b for b in children if b["type"] == "table"]
    # Find the team table (4 columns: Имя | Должность | LinkedIn | Контакт)
    team_table = next((t for t in tables if t["table"]["table_width"] == 4), None)
    assert team_table is not None
    # First data row corresponds to c1 which has notion_page_id
    data_row = team_table["table"]["children"][1]  # index 0 = header
    contact_cell = data_row["table_row"]["cells"][3]  # last column = Контакт
    types = [seg["type"] for seg in contact_cell]
    assert "mention" in types


def test_collaboration_section_no_contacts():
    block = nr.build_collaboration_section([], _ANALYSIS)
    assert block is not None  # section still renders with partners from analysis


def test_collaboration_section_returns_none_when_all_empty():
    block = nr.build_collaboration_section([], {})
    assert block is None


def test_financials_section_is_callout():
    block = nr.build_financials_section(_DOSSIER, _ANALYSIS)
    assert block is not None
    assert block["type"] == "callout"
    assert block["callout"]["icon"]["emoji"] == "💰"


def test_financials_section_has_rounds_table():
    block = nr.build_financials_section(_DOSSIER, _ANALYSIS)
    children = block["callout"]["children"]
    tables = [b for b in children if b["type"] == "table"]
    assert len(tables) == 1
    assert tables[0]["table"]["table_width"] == 4


def test_financials_section_no_dossier_returns_none():
    block = nr.build_financials_section(None, {})
    assert block is None


def test_news_section_is_callout():
    block = nr.build_news_section(_NEWS)
    assert block is not None
    assert block["type"] == "callout"
    assert block["callout"]["icon"]["emoji"] == "📰"


def test_news_bullet_has_children():
    """Each news bullet must have child paragraphs for summary and link."""
    block = nr.build_news_section(_NEWS)
    children = block["callout"]["children"]
    bullets = [b for b in children if b["type"] == "bulleted_list_item"]
    assert len(bullets) == 1
    bullet_children = bullets[0]["bulleted_list_item"]["children"]
    assert len(bullet_children) >= 2  # summary + link


def test_news_section_no_news_returns_none():
    block = nr.build_news_section([])
    assert block is None
    block2 = nr.build_news_section(None)
    assert block2 is None


def test_audit_section_is_callout():
    block = nr.build_audit_section(_DOSSIER, _ANALYSIS)
    assert block is not None
    assert block["type"] == "callout"
    assert block["callout"]["icon"]["emoji"] == "🔍"


def test_audit_section_has_claims_table():
    block = nr.build_audit_section(_DOSSIER, _ANALYSIS)
    children = block["callout"]["children"]
    tables = [b for b in children if b["type"] == "table"]
    assert len(tables) == 1
    assert tables[0]["table"]["table_width"] == 2  # Заявление | Реальная оценка


def test_audit_section_no_analysis_falls_back_to_audit_md():
    block = nr.build_audit_section(
        {**_DOSSIER, "audit_md": "Some plain text.\n\nAnother paragraph."},
        {},
    )
    assert block is not None
    children = block["callout"]["children"]
    paragraphs = [b for b in children if b["type"] == "paragraph"]
    assert len(paragraphs) >= 2


def test_conclusion_section_uses_heading3():
    block = nr.build_conclusion_section(_DOSSIER, _ANALYSIS)
    assert block is not None
    children = block["callout"]["children"]
    assert children[0]["type"] == "heading_3"


def test_conclusion_section_icon():
    block = nr.build_conclusion_section(_DOSSIER, _ANALYSIS)
    assert block["callout"]["icon"]["emoji"] == "🎯"


def test_disclaimer_block_is_heading4():
    b = nr.disclaimer_block()
    assert b["type"] == "heading_4"
    rt = b["heading_4"]["rich_text"]
    assert rt[0]["annotations"]["italic"] is True
    assert rt[0]["annotations"]["color"] == "gray"


# ---- build_page_blocks ----------------------------------------------------

def test_build_page_blocks_full():
    blocks = nr.build_page_blocks(_COMPANY, _DOSSIER, _ANALYSIS, _CONTACTS, _NEWS)
    block_types = [b["type"] for b in blocks]
    assert "heading_1" in block_types
    assert "divider" in block_types
    callouts = [b for b in blocks if b["type"] == "callout"]
    assert len(callouts) >= 7  # О компании, Продукт x1+, Сотрудничество, Финансы, Новости, Анализ, Вывод


def test_build_page_blocks_first_block_is_heading1():
    blocks = nr.build_page_blocks(_COMPANY, _DOSSIER, _ANALYSIS, _CONTACTS, _NEWS)
    assert blocks[0]["type"] == "heading_1"
    assert blocks[0]["heading_1"]["rich_text"][0]["text"]["content"] == "Dossier"


def test_build_page_blocks_no_dossier():
    blocks = nr.build_page_blocks(_COMPANY, None, {}, [], [])
    callouts = [b for b in blocks if b["type"] == "callout"]
    emojis = [b["callout"]["icon"]["emoji"] for b in callouts]
    assert "🏢" in emojis          # О компании present
    assert "📦" not in emojis      # no product
    assert "💰" not in emojis      # no financials
    assert "🔍" not in emojis      # no audit
    assert "🎯" not in emojis      # no conclusion


def test_build_page_blocks_no_contacts():
    blocks = nr.build_page_blocks(_COMPANY, _DOSSIER, _ANALYSIS, [], _NEWS)
    # All callouts still render (contacts optional inside them)
    assert len(blocks) > 0
    # No mentions in any block (no contacts with notion_page_id)
    def _has_mention(block):
        for rt in (block.get("paragraph") or {}).get("rich_text", []):
            if rt.get("type") == "mention":
                return True
        return False
    paragraphs = [b for b in blocks if b["type"] == "paragraph"]
    assert not any(_has_mention(p) for p in paragraphs)


def test_build_page_blocks_no_news():
    blocks = nr.build_page_blocks(_COMPANY, _DOSSIER, _ANALYSIS, _CONTACTS, [])
    callouts = [b for b in blocks if b["type"] == "callout"]
    emojis = [b["callout"]["icon"]["emoji"] for b in callouts]
    assert "📰" not in emojis


def test_build_page_blocks_has_disclaimer():
    blocks = nr.build_page_blocks(_COMPANY, _DOSSIER, _ANALYSIS, _CONTACTS, _NEWS)
    h4_blocks = [b for b in blocks if b["type"] == "heading_4"]
    assert len(h4_blocks) == 1
    rt = h4_blocks[0]["heading_4"]["rich_text"]
    assert "аналитический" in rt[0]["text"]["content"]


# ---- Gateway extensions ---------------------------------------------------

import notion_sync as ns  # noqa: E402


def _make_fake_inner(blocks_data):
    inner = type("_Inner", (), {})()
    inner.deleted = []

    class _Blocks:
        class children:
            @staticmethod
            def list(block_id, start_cursor=None):
                return {"results": blocks_data.get(block_id, []), "has_more": False}

        @staticmethod
        def delete(block_id):
            inner.deleted.append(block_id)

    inner.blocks = _Blocks
    return inner


def test_notion_gateway_list_block_children():
    fake = _make_fake_inner({"pg-1": [{"id": "blk-1"}, {"id": "blk-2"}]})
    gw = ns.NotionGateway(fake)
    result = gw.list_block_children("pg-1")
    assert result == [{"id": "blk-1"}, {"id": "blk-2"}]


def test_notion_gateway_delete_block():
    fake = _make_fake_inner({})
    gw = ns.NotionGateway(fake)
    gw.delete_block("blk-99")
    assert "blk-99" in fake.deleted


# ---- render_and_write_body ------------------------------------------------

class _FakeDbForRender:
    """Fake DB for render_and_write_body tests."""
    def __init__(self, company, dossier, analysis_records, contacts, news):
        self._company = company
        self._dossier = dossier
        self._analysis = analysis_records  # list of dicts
        self._contacts = contacts
        self._news = news

    def fetch_one_by_id(self, table, id_value):
        if table == "companies":
            return self._company if self._company and self._company.get("id") == id_value else None
        return None

    def fetch_for_company(self, table, company_id):
        if table == "dossiers":
            return [self._dossier] if self._dossier else []
        if table == "analysis_records":
            return self._analysis
        if table == "contacts":
            return self._contacts
        return []

    def fetch_news_for_company(self, company_id, limit=10):
        return self._news[:limit]


class _FakeNotionForRender:
    def __init__(self, existing_blocks=None):
        self.appended = {}  # page_id -> list of blocks
        self._existing = existing_blocks or {}
        self.deleted = []

    def list_block_children(self, page_id):
        return self._existing.get(page_id, [])

    def delete_block(self, block_id):
        self.deleted.append(block_id)

    def append_children(self, page_id, children):
        self.appended.setdefault(page_id, []).extend(children)


class _FakeSync:
    def __init__(self, db, notion):
        self.db = db
        self.notion = notion


def test_render_and_write_body_appends_blocks():
    db = _FakeDbForRender(
        _COMPANY, _DOSSIER,
        list(_ANALYSIS.values()),
        _CONTACTS, _NEWS,
    )
    notion = _FakeNotionForRender()
    sync = _FakeSync(db, notion)
    nr.render_and_write_body(sync, _COMPANY["id"], "page-99", refresh=False)
    assert "page-99" in notion.appended
    assert len(notion.appended["page-99"]) > 0


def test_refresh_deletes_existing_blocks():
    existing = [{"id": "old-blk-1"}, {"id": "old-blk-2"}]
    db = _FakeDbForRender(
        _COMPANY, _DOSSIER,
        list(_ANALYSIS.values()),
        _CONTACTS, _NEWS,
    )
    notion = _FakeNotionForRender(existing_blocks={"page-99": existing})
    sync = _FakeSync(db, notion)
    nr.render_and_write_body(sync, _COMPANY["id"], "page-99", refresh=True)
    assert "old-blk-1" in notion.deleted
    assert "old-blk-2" in notion.deleted
    assert "page-99" in notion.appended  # new blocks written after deletion


def test_render_and_write_body_no_refresh_does_not_delete():
    existing = [{"id": "keep-blk"}]
    db = _FakeDbForRender(
        _COMPANY, _DOSSIER,
        list(_ANALYSIS.values()),
        _CONTACTS, _NEWS,
    )
    notion = _FakeNotionForRender(existing_blocks={"page-99": existing})
    sync = _FakeSync(db, notion)
    nr.render_and_write_body(sync, _COMPANY["id"], "page-99", refresh=False)
    assert "keep-blk" not in notion.deleted


def test_render_and_write_body_translates_via_sync_translator():
    """render_and_write_body uses sync.translator to translate prose before rendering."""
    from unittest.mock import MagicMock

    translated_calls = []

    def fake_translate(text):
        if text:
            translated_calls.append(text)
            return f"[RU]{text}"
        return text

    translator = MagicMock()
    translator.translate.side_effect = fake_translate

    # Dossier with no analysis facts — forces fallback to audit_md and summary_md
    dossier_with_prose = {
        "company_id": _COMPANY["id"],
        "product_category": "Computer Vision",
        "ai_use_case": "Object detection",
        "funding_stage": "Series B",
        "summary_md": "English summary prose",
        "audit_md": "English audit prose",
    }

    db = _FakeDbForRender(
        _COMPANY,
        dossier_with_prose,
        [],  # no analysis records — forces fallback to summary_md and audit_md
        [],
        [],
    )
    notion = _FakeNotionForRender()

    class _FakeSyncWithTranslator:
        def __init__(self):
            self.db = db
            self.notion = notion
            self.translator = translator

    sync = _FakeSyncWithTranslator()
    nr.render_and_write_body(sync, _COMPANY["id"], "page-99", refresh=False)

    # translator.translate must have been called with the prose fields
    translator.translate.assert_any_call("English summary prose")
    translator.translate.assert_any_call("English audit prose")

    # The translated text should appear in the rendered blocks
    all_text = []
    for block in notion.appended.get("page-99", []):
        def _collect_text(b):
            for section in ("paragraph", "heading_1", "heading_2", "heading_3",
                            "heading_4", "quote", "bulleted_list_item"):
                rt = (b.get(section) or {}).get("rich_text", [])
                for seg in rt:
                    all_text.append((seg.get("text") or {}).get("content", ""))
            for child in (b.get("callout") or {}).get("children", []):
                _collect_text(child)
        _collect_text(block)

    assert any("[RU]English summary prose" in t for t in all_text), \
        "Translated summary_md not found in rendered blocks"
    assert any("[RU]English audit prose" in t for t in all_text), \
        "Translated audit_md not found in rendered blocks"
