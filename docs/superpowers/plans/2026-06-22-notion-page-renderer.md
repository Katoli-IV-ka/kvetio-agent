# Notion Page Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `scripts/notion_render.py` that renders rich, structured Notion page bodies from Supabase data, and wire it into `notion_sync.py` so bodies are written on first create or explicit refresh.

**Architecture:** Pure renderer `notion_render.py` takes structured dicts (company, dossier, analysis, contacts, news) and returns Notion block payloads — zero network I/O. `NotionGateway` gets two new methods (`list_block_children`, `delete_block`). `DbGateway` gets two new methods (`fetch_for_company`, `fetch_news_for_company`). `NotionSync.sync_forward` calls `render_and_write_body` immediately after `create_page` for `companies`. `--refresh-body` CLI flag re-renders all pages that already have a `notion_page_id`.

**Tech Stack:** Python 3.11, pytest — no new dependencies.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `scripts/notion_render.py` | Create | All block-building logic, section builders, `build_page_blocks`, `render_and_write_body` |
| `scripts/notion_sync.py` | Modify | Add `list_block_children` + `delete_block` to `NotionGateway`; add `fetch_for_company` + `fetch_news_for_company` to `DbGateway`; call `render_and_write_body` after `create_page` in `sync_forward`; add `--refresh-body` CLI flag |
| `tests/test_notion_render.py` | Create | Unit tests for all renderers. No network. |

---

### Task 1: Primitive block builders

**Files:**
- Create: `scripts/notion_render.py`
- Create: `tests/test_notion_render.py`

- [ ] **Step 1: Create test file with tests for primitive builders**

```python
# tests/test_notion_render.py
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -v 2>&1 | head -30
```
Expected: ImportError or ModuleNotFoundError (notion_render doesn't exist yet).

- [ ] **Step 3: Create `scripts/notion_render.py` with primitive builders**

```python
# scripts/notion_render.py
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
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py::test_heading_1_block tests/test_notion_render.py::test_heading_2_block tests/test_notion_render.py::test_heading_3_block tests/test_notion_render.py::test_divider_block tests/test_notion_render.py::test_empty_block tests/test_notion_render.py::test_quote_block -v
```
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add scripts/notion_render.py tests/test_notion_render.py
git commit -m "feat: add notion_render.py with primitive block builders"
```

---

### Task 2: Field helpers — label_segment, field_block, callout_block

**Files:**
- Modify: `scripts/notion_render.py`
- Modify: `tests/test_notion_render.py`

- [ ] **Step 1: Add tests for label/field helpers**

Add to `tests/test_notion_render.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py::test_label_segment_format tests/test_notion_render.py::test_field_block_returns_none_for_none_value tests/test_notion_render.py::test_field_block_structure tests/test_notion_render.py::test_callout_block_structure -v
```
Expected: AttributeError (functions don't exist yet).

- [ ] **Step 3: Add helpers to `scripts/notion_render.py`**

Append after the primitive builders:

```python

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
```

- [ ] **Step 4: Run to verify they pass**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -v -k "label_segment or field_block or callout_block"
```
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add scripts/notion_render.py tests/test_notion_render.py
git commit -m "feat: add label_segment, field_block, callout_block helpers"
```

---

### Task 3: О компании section

**Files:**
- Modify: `scripts/notion_render.py`
- Modify: `tests/test_notion_render.py`

The section emits a callout (🏢) with heading_2 + divider + field paragraphs + an optional leaders paragraph with hard_break.

Leaders are contacts where `contact_type == 'person'` and `info` contains a leadership keyword.

- [ ] **Step 1: Add tests for О компании section**

Add to `tests/test_notion_render.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "company_section" -v
```
Expected: AttributeError (build_company_section doesn't exist).

- [ ] **Step 3: Add О компании builder to `scripts/notion_render.py`**

Append:

```python

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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "company_section" -v
```
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add scripts/notion_render.py tests/test_notion_render.py
git commit -m "feat: add build_company_section with leaders paragraph"
```

---

### Task 4: Продукт section (основной + второстепенный)

**Files:**
- Modify: `scripts/notion_render.py`
- Modify: `tests/test_notion_render.py`

- [ ] **Step 1: Add tests**

Add to `tests/test_notion_render.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "product_section" -v
```
Expected: AttributeError.

- [ ] **Step 3: Add product section builder to `scripts/notion_render.py`**

Append:

```python

def build_product_sections(
    dossier: dict | None,
    analysis: dict[str, dict],
) -> list[dict]:
    """Return list of 1 or 2 callout blocks for Продукт (основной + второстепенный)."""
    if not dossier:
        return []

    facts = (analysis.get("product") or {}).get("facts") or {}
    d = dossier

    def _product_children(title: str, what: str | None, f: dict) -> list[dict] | None:
        fields: list[dict] = []
        if b := field_block("Что это:", what):
            fields.append(b)
        if b := field_block("Целевой рынок:", f.get("target_market")):
            fields.append(b)
        if b := field_block("Проблема, которую решает:", f.get("problem_solved")):
            fields.append(b)
        if b := field_block("Технологии:", f.get("technologies")):
            fields.append(b)
        features = f.get("features")
        if features:
            items = features if isinstance(features, list) else [features]
            if bullets := _bulleted_text_block([str(i) for i in items]):
                fields.append(field_block("Функционал:", "↓") or empty_block())
                fields.extend(bullets)
        if b := field_block("Данные, необходимые продукту:", f.get("data_needs")):
            fields.append(b)
        if b := field_block("Трудности в разработке:", f.get("challenges")):
            fields.append(b)
        if not fields:
            return None
        return [heading_2_block(title), divider_block(), *fields]

    what_primary = None
    parts = []
    if d.get("product_category"):
        parts.append(d["product_category"])
    if d.get("ai_use_case"):
        parts.append(d["ai_use_case"])
    what_primary = " / ".join(parts) if parts else None

    sections: list[dict] = []

    primary_children = _product_children("Продукт [основной]", what_primary, facts)
    if primary_children:
        sections.append(callout_block("📦", primary_children))

    secondary_facts = facts.get("secondary_product") or {}
    if secondary_facts:
        sec_children = _product_children(
            "Продукт [второстепенный]",
            secondary_facts.get("what"),
            secondary_facts,
        )
        if sec_children:
            sections.append(callout_block("📦", sec_children))

    return sections
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "product_section" -v
```
Expected: 4 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add scripts/notion_render.py tests/test_notion_render.py
git commit -m "feat: add build_product_sections with features bullets"
```

---

### Task 5: Сотрудничество section

**Files:**
- Modify: `scripts/notion_render.py`
- Modify: `tests/test_notion_render.py`

Contains: partners table + team table + ЛПР paragraph + note.

- [ ] **Step 1: Add tests**

Add to `tests/test_notion_render.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "collaboration_section or contacts_table" -v
```
Expected: AttributeError.

- [ ] **Step 3: Add collaboration section builder to `scripts/notion_render.py`**

Append:

```python

def build_collaboration_section(
    contacts: list[dict],
    analysis: dict[str, dict],
) -> dict | None:
    """Build Сотрудничество callout. Returns None if all content is empty."""
    facts = (analysis.get("collaboration") or {}).get("facts") or {}
    fields: list[dict] = []

    # Partners table
    partners = facts.get("partners") or []
    if partners:
        rows = [
            [p.get("type", ""), p.get("company", ""), p.get("role", "")]
            for p in partners
        ]
        fields.append(field_block("Партнёры и поставщики данных:", "↓") or empty_block())
        fields.append(_table_block(["Тип", "Компания", "Роль"], rows))

    # Team table from contacts (persons only)
    persons = [c for c in contacts if c.get("contact_type") == "person"]
    if persons:
        rows = []
        for c in persons:
            contact_cell = (
                {"_mention_page_id": c["notion_page_id"]}
                if c.get("notion_page_id")
                else c.get("name", "")
            )
            rows.append([
                c.get("name", ""),
                c.get("info", ""),
                c.get("linkedin_url", ""),
                contact_cell,
            ])
        fields.append(field_block("Команда:", "↓") or empty_block())
        fields.append(_table_block(["Имя", "Должность", "LinkedIn / Источник", "Контакт"], rows))

    # ЛПР paragraph (tier-1 contacts)
    ldm_contacts = [
        c for c in contacts
        if c.get("contact_type") == "person"
        and any(kw.lower() in (c.get("info") or "").lower() for kw in _LEADER_KEYWORDS)
    ]
    if ldm_contacts:
        rt = [label_segment("ЛПР:")]
        for c in ldm_contacts:
            name = c.get("name") or ""
            info = c.get("info") or ""
            rt += [
                {"type": "text", "text": {"content": "\n- "}, "annotations": {}},
                {"type": "text", "text": {"content": f"{name} ({info})" if info else name},
                 "annotations": {"bold": True}},
            ]
        fields.append({
            "object": "block",
            "type": "paragraph",
            "paragraph": {"rich_text": rt},
        })

    if note := facts.get("note"):
        if b := field_block("Примечание:", note):
            fields.append(b)

    if not fields:
        return None

    children = [heading_2_block("Сотрудничество"), divider_block(), *fields]
    return callout_block("🤝", children)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "collaboration_section or contacts_table" -v
```
Expected: 5 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add scripts/notion_render.py tests/test_notion_render.py
git commit -m "feat: add build_collaboration_section with team table and mentions"
```

---

### Task 6: Финансы section

**Files:**
- Modify: `scripts/notion_render.py`
- Modify: `tests/test_notion_render.py`

Contains: funding source, rounds table, valuation, public status, metrics bullets, dynamics.

- [ ] **Step 1: Add tests**

Add to `tests/test_notion_render.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "financials_section" -v
```
Expected: AttributeError.

- [ ] **Step 3: Add financials section builder to `scripts/notion_render.py`**

Append:

```python

def build_financials_section(
    dossier: dict | None,
    analysis: dict[str, dict],
) -> dict | None:
    """Build Финансы callout. Returns None if all content is empty."""
    if not dossier:
        return None

    facts = (analysis.get("financials") or {}).get("facts") or {}
    d = dossier
    fields: list[dict] = []

    if b := field_block("Источники финансирования:", d.get("funding_stage")):
        fields.append(b)

    rounds = facts.get("rounds") or []
    if rounds:
        rows = [
            [
                r.get("year", ""),
                r.get("round", ""),
                r.get("amount", ""),
                r.get("investors", ""),
            ]
            for r in rounds
        ]
        fields.append(field_block("История раундов:", "↓") or empty_block())
        fields.append(_table_block(["Год", "Раунд", "Сумма", "Инвесторы"], rows))

    if b := field_block("Оценка компании:", facts.get("valuation")):
        fields.append(b)
    if b := field_block("Акции / Биржа:", facts.get("public_status")):
        fields.append(b)

    metrics = facts.get("metrics") or []
    if metrics:
        items = metrics if isinstance(metrics, list) else [metrics]
        fields.append(field_block("Финансовые показатели:", "↓") or empty_block())
        fields.extend(_bulleted_text_block([str(i) for i in items]))

    if b := field_block("Анализ динамики:", facts.get("dynamics")):
        fields.append(b)

    if not fields:
        return None

    children = [heading_2_block("Финансы"), divider_block(), *fields]
    return callout_block("💰", children)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "financials_section" -v
```
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add scripts/notion_render.py tests/test_notion_render.py
git commit -m "feat: add build_financials_section with rounds table"
```

---

### Task 7: Новости section

**Files:**
- Modify: `scripts/notion_render.py`
- Modify: `tests/test_notion_render.py`

Each news item = bulleted_list_item with children (summary paragraph + link paragraph).

- [ ] **Step 1: Add tests**

Add to `tests/test_notion_render.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "news_section or news_bullet" -v
```
Expected: AttributeError.

- [ ] **Step 3: Add news section builder to `scripts/notion_render.py`**

Append:

```python

def _paragraph_block(text: str, link: str | None = None) -> dict:
    if link:
        rt = [
            {"type": "text", "text": {"content": "🔗 "}},
            {"type": "text", "text": {"content": text, "link": {"url": link}}},
        ]
    else:
        rt = [{"type": "text", "text": {"content": text}}]
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt}}


def build_news_section(news: list[dict] | None) -> dict | None:
    """Build Новости callout. Returns None if no news items."""
    if not news:
        return None

    items: list[dict] = []
    for item in news:
        observed = item.get("observed_at") or ""
        try:
            d = date.fromisoformat(str(observed))
            month_year = d.strftime("%B %Y")
        except (ValueError, TypeError):
            month_year = str(observed)

        title = item.get("title") or ""
        summary = item.get("summary") or ""
        url = item.get("url") or ""

        bullet_text = f"[{month_year}] {title}"
        children: list[dict] = []
        if summary:
            children.append(_paragraph_block(summary))
        if url:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc or url
            children.append(_paragraph_block(domain, link=url))

        items.append({
            "object": "block",
            "type": "bulleted_list_item",
            "bulleted_list_item": {
                "rich_text": [
                    {"type": "text", "text": {"content": bullet_text},
                     "annotations": {"bold": True}}
                ],
                "children": children,
            },
        })

    if not items:
        return None

    children_blocks = [heading_2_block("Новости"), divider_block(), *items]
    return callout_block("📰", children_blocks)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "news_section or news_bullet" -v
```
Expected: 3 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add scripts/notion_render.py tests/test_notion_render.py
git commit -m "feat: add build_news_section with nested bullet children"
```

---

### Task 8: Комплексный анализ and Вывод sections

**Files:**
- Modify: `scripts/notion_render.py`
- Modify: `tests/test_notion_render.py`

Audit uses heading_2 inside callout. Вывод uses heading_3 (exception per spec). Disclaimer is a heading_4 block appended after the Вывод callout.

- [ ] **Step 1: Add tests**

Add to `tests/test_notion_render.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "audit_section or conclusion_section or disclaimer" -v
```
Expected: AttributeError.

- [ ] **Step 3: Add audit, conclusion, disclaimer builders to `scripts/notion_render.py`**

Append:

```python

def disclaimer_block() -> dict:
    return {
        "object": "block",
        "type": "heading_4",
        "heading_4": {
            "rich_text": [{
                "type": "text",
                "text": {"content": "Документ носит аналитический характер и составлен на основе открытых источников."},
                "annotations": {"italic": True, "color": "gray"},
            }],
            "is_toggleable": False,
        },
    }


def build_audit_section(
    dossier: dict | None,
    analysis: dict[str, dict],
) -> dict | None:
    """Build Комплексный анализ callout."""
    facts = (analysis.get("audit") or {}).get("facts") or {}
    d = dossier or {}
    fields: list[dict] = []

    if facts:
        if b := field_block("Общая картина:", facts.get("overview")):
            fields.append(b)

        claims = facts.get("claims_vs_reality") or []
        if claims:
            rows = [[c.get("claim", ""), c.get("reality", "")] for c in claims]
            fields.append(field_block("Заявление → Реальная оценка:", "↓") or empty_block())
            fields.append(_table_block(["Заявление", "Реальная оценка"], rows))

        risks = facts.get("risks") or []
        if risks:
            items = risks if isinstance(risks, list) else [risks]
            fields.append(field_block("Риски:", "↓") or empty_block())
            fields.extend(_bulleted_text_block([str(r) for r in items]))

        if b := field_block("Прогноз:", facts.get("forecast")):
            fields.append(b)

    elif d.get("audit_md"):
        for para in (d["audit_md"] or "").split("\n\n"):
            para = para.strip()
            if para:
                fields.append(_paragraph_block(para))

    if not fields:
        return None

    children = [heading_2_block("Комплексный анализ и оценка"), divider_block(), *fields]
    return callout_block("🔍", children)


def build_conclusion_section(
    dossier: dict | None,
    analysis: dict[str, dict],
) -> dict | None:
    """Build Вывод для нас callout. Uses heading_3 (not heading_2) per spec."""
    facts = (analysis.get("audit") or {}).get("facts") or {}
    d = dossier or {}
    fields: list[dict] = []

    if facts:
        interesting = facts.get("why_interesting") or []
        if interesting:
            items = interesting if isinstance(interesting, list) else [interesting]
            fields.append(field_block("Почему интересны:", "↓") or empty_block())
            fields.extend(_bulleted_text_block([str(i) for i in items]))

        if b := field_block("Точка входа:", facts.get("entry_point")):
            fields.append(b)
        if b := field_block("Угол для питча:", facts.get("pitch_angle")):
            fields.append(b)
        if b := field_block("Рекомендуемый следующий шаг:", facts.get("next_step")):
            fields.append(b)

    elif d.get("summary_md"):
        for para in (d["summary_md"] or "").split("\n\n"):
            para = para.strip()
            if para:
                fields.append(_paragraph_block(para))

    if not fields:
        return None

    # Spec: heading_3 for Вывод (not heading_2)
    children = [heading_3_block("Вывод для нас"), divider_block(), *fields]
    return callout_block("🎯", children)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "audit_section or conclusion_section or disclaimer" -v
```
Expected: 6 PASSED.

- [ ] **Step 5: Commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add scripts/notion_render.py tests/test_notion_render.py
git commit -m "feat: add build_audit_section, build_conclusion_section, disclaimer_block"
```

---

### Task 9: `build_page_blocks` — top-level assembler and graceful degradation

**Files:**
- Modify: `scripts/notion_render.py`
- Modify: `tests/test_notion_render.py`

The function assembles all sections into the full page structure per spec:
```
heading_1 "Dossier"
quote      metadata
divider
callout    О компании
callout    Продукт [основной]
callout    Продукт [второстепенный]   ← if exists
divider
callout    Сотрудничество
divider
callout    Финансы
empty_block
divider
callout    Новости
divider
callout    Комплексный анализ и оценка
callout    Вывод для нас
heading_4  disclaimer
empty_block
```

- [ ] **Step 1: Add tests**

Add to `tests/test_notion_render.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "build_page_blocks" -v
```
Expected: AttributeError (build_page_blocks doesn't exist).

- [ ] **Step 3: Add `build_page_blocks` to `scripts/notion_render.py`**

Append:

```python

# ---------------------------------------------------------------------------
# Top-level assembler
# ---------------------------------------------------------------------------

def build_page_blocks(
    company: dict,
    dossier: dict | None,
    analysis: dict[str, dict],
    contacts: list[dict],
    news: list[dict],
) -> list[dict]:
    """Return list of Notion block payloads for the company page body."""
    today = date.today().isoformat()
    status = company.get("status", "unknown")

    blocks: list[dict] = [
        heading_1_block("Dossier"),
        quote_block(f"Составлено: {today} | Система: kvetio-agent | Статус: {status}"),
        divider_block(),
    ]

    if section := build_company_section(company, dossier, analysis, contacts):
        blocks.append(section)

    for section in build_product_sections(dossier, analysis):
        blocks.append(section)

    blocks.append(divider_block())

    if section := build_collaboration_section(contacts, analysis):
        blocks.append(section)

    blocks.append(divider_block())

    if section := build_financials_section(dossier, analysis):
        blocks.append(section)

    blocks.append(empty_block())
    blocks.append(divider_block())

    if section := build_news_section(news):
        blocks.append(section)

    blocks.append(divider_block())

    if section := build_audit_section(dossier, analysis):
        blocks.append(section)

    if section := build_conclusion_section(dossier, analysis):
        blocks.append(section)

    blocks.append(disclaimer_block())
    blocks.append(empty_block())

    return blocks
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "build_page_blocks" -v
```
Expected: 6 PASSED.

- [ ] **Step 5: Run all render tests**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -v
```
Expected: all PASSED.

- [ ] **Step 6: Commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add scripts/notion_render.py tests/test_notion_render.py
git commit -m "feat: add build_page_blocks with graceful degradation"
```

---

### Task 10: NotionGateway and DbGateway extensions

**Files:**
- Modify: `scripts/notion_sync.py`
- Modify: `tests/test_notion_render.py`

Add to `NotionGateway`: `list_block_children`, `delete_block`.
Add to `DbGateway`: `fetch_for_company`, `fetch_news_for_company`.

- [ ] **Step 1: Add tests for new gateway methods**

Add to `tests/test_notion_render.py`:

```python
# ---- Gateway extensions ---------------------------------------------------

import notion_sync as ns


class _FakeNotionExt(ns.NotionGateway.__bases__[0] if False else object):
    """Minimal fake that tracks list/delete calls."""
    def __init__(self):
        self._blocks = {}  # page_id -> list of block dicts
        self.deleted = []

    def blocks_children_list(self, page_id, existing=None):
        # Simulate notion_client blocks.children.list
        return {"results": self._blocks.get(page_id, []), "has_more": False}

    def blocks_delete(self, block_id):
        self.deleted.append(block_id)


class _FakeInnerClient:
    def __init__(self, blocks_data):
        self._blocks_data = blocks_data
        self.deleted = []

    @property
    def blocks(self):
        return self

    def children(self):  # noqa
        return self

    def list(self, block_id, start_cursor=None):
        return {"results": self._blocks_data.get(block_id, []), "has_more": False}

    def delete(self, block_id):
        self.deleted.append(block_id)


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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "notion_gateway" -v
```
Expected: AttributeError (methods don't exist on NotionGateway).

- [ ] **Step 3: Add methods to `NotionGateway` in `scripts/notion_sync.py`**

Locate the `NotionGateway` class (around line 190). Add after `append_children`:

```python
    def list_block_children(self, block_id: str) -> list[dict]:
        """Return all child blocks with pagination."""
        results, cursor = [], None
        while True:
            resp = (
                self._c.blocks.children.list(block_id=block_id, start_cursor=cursor)
                if cursor
                else self._c.blocks.children.list(block_id=block_id)
            )
            results.extend(resp["results"])
            if not resp.get("has_more"):
                break
            cursor = resp["next_cursor"]
        return results

    def delete_block(self, block_id: str) -> None:
        self._c.blocks.delete(block_id=block_id)
```

- [ ] **Step 4: Add methods to `DbGateway` in `scripts/notion_sync.py`**

Locate `DbGateway` class (around line 225). Add after `insert`:

```python
    def fetch_for_company(self, table: str, company_id: str) -> list[dict]:
        """Fetch all rows for a company_id from any table."""
        return (
            self._c.table(table)
            .select("*")
            .eq("company_id", company_id)
            .execute()
            .data or []
        )

    def fetch_news_for_company(self, company_id: str, limit: int = 10) -> list[dict]:
        """Fetch latest news research_records for a company."""
        return (
            self._c.table("research_records")
            .select("*")
            .eq("company_id", company_id)
            .eq("record_type", "news")
            .order("observed_at", desc=True)
            .limit(limit)
            .execute()
            .data or []
        )

    def fetch_one_by_id(self, table: str, id_value: str) -> dict | None:
        """Fetch single row by primary key 'id'."""
        rows = (
            self._c.table(table)
            .select("*")
            .eq("id", id_value)
            .limit(1)
            .execute()
            .data or []
        )
        return rows[0] if rows else None
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "notion_gateway" -v
```
Expected: 2 PASSED.

- [ ] **Step 6: Run full existing notion_sync test suite to confirm no regressions**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_sync.py -v
```
Expected: all PASSED (no regressions).

- [ ] **Step 7: Commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add scripts/notion_sync.py tests/test_notion_render.py
git commit -m "feat: add list_block_children, delete_block, fetch_for_company to gateways"
```

---

### Task 11: `render_and_write_body` + `sync_forward` integration + `--refresh-body` CLI flag

**Files:**
- Modify: `scripts/notion_render.py`
- Modify: `scripts/notion_sync.py`
- Modify: `tests/test_notion_render.py`

- [ ] **Step 1: Add tests for `render_and_write_body` with refresh**

Add to `tests/test_notion_render.py`:

```python
# ---- render_and_write_body ------------------------------------------------

class _FakeDbForRender:
    """Fake DB for render_and_write_body tests."""
    def __init__(self, company, dossier, analysis_records, contacts, news):
        self._company = company
        self._dossier = dossier
        self._analysis = analysis_records  # list of dicts
        self._contacts = contacts
        self._news = news
        self.appended = []
        self.deleted = []

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
```

- [ ] **Step 2: Run to verify they fail**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "render_and_write_body or refresh_deletes" -v
```
Expected: AttributeError (render_and_write_body doesn't exist).

- [ ] **Step 3: Add `render_and_write_body` to `scripts/notion_render.py`**

Add at the bottom of `scripts/notion_render.py`:

```python

# ---------------------------------------------------------------------------
# Data orchestrator
# ---------------------------------------------------------------------------

def render_and_write_body(
    sync,          # NotionSync instance with .db and .notion attributes
    company_id: str,
    page_id: str,
    refresh: bool = False,
) -> None:
    """Fetch data from DB, build blocks, write to Notion.

    If refresh=True, delete all existing page blocks first.
    """
    # Fetch raw data
    company = sync.db.fetch_one_by_id("companies", company_id) or {}
    dossier_rows = sync.db.fetch_for_company("dossiers", company_id)
    dossier = dossier_rows[0] if dossier_rows else None

    analysis_rows = sync.db.fetch_for_company("analysis_records", company_id)
    analysis: dict[str, dict] = {row["section"]: row for row in analysis_rows}

    contacts = sync.db.fetch_for_company("contacts", company_id)
    news = sync.db.fetch_news_for_company(company_id)

    blocks = build_page_blocks(company, dossier, analysis, contacts, news)
    if not blocks:
        return

    if refresh:
        existing = sync.notion.list_block_children(page_id)
        for blk in existing:
            sync.notion.delete_block(blk["id"])

    sync.notion.append_children(page_id, blocks)
```

- [ ] **Step 4: Run render_and_write_body tests**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py -k "render_and_write_body or refresh_deletes or no_refresh" -v
```
Expected: 3 PASSED.

- [ ] **Step 5: Wire `render_and_write_body` into `sync_forward` for companies**

In `scripts/notion_sync.py`, find the `sync_forward` method. Locate the `else` branch that calls `create_page` (around line 287):

```python
                else:
                    page = self.notion.create_page(db_id, props)
                    self.db.update(cfg["db_table"], cfg["db_key"],
                                   row[cfg["db_key"]],
                                   {"notion_page_id": page["id"],
                                    "notion_synced_at": datetime.utcnow().isoformat()})
                    created += 1
```

Replace with:

```python
                else:
                    page = self.notion.create_page(db_id, props)
                    page_id = page["id"]
                    self.db.update(cfg["db_table"], cfg["db_key"],
                                   row[cfg["db_key"]],
                                   {"notion_page_id": page_id,
                                    "notion_synced_at": datetime.utcnow().isoformat()})
                    if entity == "companies":
                        try:
                            from notion_render import render_and_write_body  # noqa: PLC0415
                            render_and_write_body(self, row[cfg["db_key"]], page_id, refresh=False)
                        except Exception as exc:  # noqa: BLE001
                            logger.error("render body %s: %s", row.get(cfg["db_key"]), exc)
                    created += 1
```

Note: `row[cfg["db_key"]]` for companies is `row["id"]` (the UUID) — but the mapping uses `"db_key": "domain"` for companies. Check `config/notion_mapping.yaml` first. If `db_key` is `"domain"`, then `row["domain"]` is not the `company_id`. We need the `id` field for `render_and_write_body`. Pass `row.get("id")` instead:

```python
                    if entity == "companies" and row.get("id"):
                        try:
                            from notion_render import render_and_write_body  # noqa: PLC0415
                            render_and_write_body(self, row["id"], page_id, refresh=False)
                        except Exception as exc:  # noqa: BLE001
                            logger.error("render body %s: %s", row.get("id"), exc)
```

- [ ] **Step 6: Verify `db_key` for companies in the mapping**

```bash
grep -A 5 "companies:" /Users/maxkhvedinich/Projects/kvetio/kvetio-agent/config/notion_mapping.yaml | head -10
```

If `db_key` is `domain`, use `row.get("id")` as shown above. If it is `id`, use `row[cfg["db_key"]]`.

- [ ] **Step 7: Add `--refresh-body` CLI flag to `notion_sync.py`**

In `build_arg_parser`, add after `--dry-run`:

```python
    p.add_argument("--refresh-body", dest="refresh_body", action="store_true",
                   help="Re-render body for all companies with existing notion_page_id")
```

In `main`, add handling before the existing entity dispatch (after `sync = NotionSync(...)` line, around line 525):

```python
    if args.refresh_body:
        from notion_render import render_and_write_body  # noqa: PLC0415
        companies = sync.db.fetch("companies")
        refreshed = errors = 0
        for company in companies:
            page_id = company.get("notion_page_id")
            company_id = company.get("id")
            if not page_id or not company_id:
                continue
            if args.dry_run:
                refreshed += 1
                continue
            try:
                render_and_write_body(sync, company_id, page_id, refresh=True)
                refreshed += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("refresh body %s: %s", company.get("domain"), exc)
                errors += 1
        print(json.dumps({"entity": "companies", "refreshed": refreshed, "errors": errors},
                         ensure_ascii=False))
        return 0
```

Place this block right after `sync = NotionSync(...)` and before the existing `if args.entity == "dossiers":` dispatch.

- [ ] **Step 8: Run full test suite to verify no regressions**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/test_notion_render.py tests/test_notion_sync.py -v
```
Expected: all PASSED.

- [ ] **Step 9: Commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add scripts/notion_render.py scripts/notion_sync.py tests/test_notion_render.py
git commit -m "feat: wire render_and_write_body into sync_forward and add --refresh-body flag"
```

---

### Task 12: Final validation

- [ ] **Step 1: Run complete test suite**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: all green; no new failures.

- [ ] **Step 2: Validate notion_sync CLI still works**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m scripts.notion_sync --validate
```
Expected: `{"valid": true}`.

- [ ] **Step 3: Verify `--help` shows new flag**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
python3 -m scripts.notion_sync --help | grep refresh
```
Expected: `--refresh-body` in output.

- [ ] **Step 4: Update ARCHITECTURE.md**

In section **5. Notion → Что и когда синхронизируется** add a note about body rendering, and in **Триггеры синхронизации** add:

```
5. **Флаг `--refresh-body`** → пересобирает тело (blocks) всех страниц компаний с `notion_page_id`. Запускается вручную: `python -m scripts.notion_sync --refresh-body [--dry-run]`.
```

In section **5. Notion → Конфигурация** add a note:

```
### Тело страницы (blocks)

При первом создании страницы компании `notion_sync.py` автоматически вызывает `notion_render.py`, 
которая заполняет тело из данных Supabase. Повторные sync только обновляют properties.
Принудительный re-render — `--refresh-body`.
```

- [ ] **Step 5: Final commit**

```bash
cd /Users/maxkhvedinich/Projects/kvetio/kvetio-agent
git add ARCHITECTURE.md
git commit -m "docs: update ARCHITECTURE.md with notion_render and --refresh-body"
```

---

## Self-Review

### Spec coverage check

| Spec requirement | Task covering it |
|---|---|
| `build_page_blocks(company, dossier, analysis, contacts, news)` | Task 9 |
| `render_and_write_body(sync, company_id, page_id, refresh)` | Task 11 |
| `NotionGateway.list_block_children` | Task 10 |
| `NotionGateway.delete_block` | Task 10 |
| `DbGateway.fetch_for_company` | Task 10 |
| `DbGateway.fetch_news_for_company` | Task 10 |
| О компании callout with leaders + page mentions | Task 3 |
| Продукт (основной + второстепенный) | Task 4 |
| Сотрудничество with partners table + team table + mention cell | Task 5 |
| Финансы with rounds table | Task 6 |
| Новости with bulleted children | Task 7 |
| Комплексный анализ with claims_vs_reality table | Task 8 |
| Вывод для нас with heading_3 | Task 8 |
| heading_4 disclaimer | Task 8 |
| Graceful degradation (no dossier, no contacts, no news) | Task 9 |
| refresh=True deletes existing blocks | Task 11 |
| Повторные sync не трогают тело (no refresh on update) | Task 11 — `refresh=False` default; `sync_forward` only calls on `create_page` |
| `--refresh-body` CLI flag | Task 11 |
| Body written after `create_page` in `sync_forward` | Task 11 |
| Field skipped if None/empty | Task 2 (`field_block` returns None) |
| Callout skipped if all fields empty | Tasks 3-8 (each returns None) |
| Callout children: heading_2 + divider first | Tasks 3-8 |
| Tests for all 8 spec test cases | Tasks 3-11 |

### Placeholder scan

No TBDs, no "implement later", no incomplete steps found.

### Type consistency

- `build_company_section` → returns `dict | None` ✓
- `build_product_sections` → returns `list[dict]` ✓
- `build_collaboration_section` → returns `dict | None` ✓
- `build_financials_section` → returns `dict | None` ✓
- `build_news_section` → returns `dict | None` ✓
- `build_audit_section` → returns `dict | None` ✓
- `build_conclusion_section` → returns `dict | None` ✓
- `build_page_blocks` → returns `list[dict]` ✓
- `render_and_write_body` → returns `None` ✓
- `_table_block`, `_bulleted_text_block`, `_paragraph_block` → consistent across tasks ✓

### Known limitation

`heading_4` is not a standard Notion API block type (Notion supports only heading_1/2/3). The spec explicitly defines it. If Notion rejects it at runtime, change `disclaimer_block()` to use a paragraph with italic+gray annotations — a 2-line fix in `notion_render.py`.
