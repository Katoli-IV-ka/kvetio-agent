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
            from urllib.parse import urlparse  # noqa: PLC0415
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
    company = sync.db.fetch_one_by_id("companies", company_id) or {}
    dossier_rows = sync.db.fetch_for_company("dossiers", company_id)
    dossier = dossier_rows[0] if dossier_rows else None

    translator = getattr(sync, 'translator', None)
    if translator is not None and dossier is not None:
        dossier = dict(dossier)  # shallow copy — avoid mutating original
        if dossier.get("summary_md"):
            dossier["summary_md"] = translator.translate(dossier["summary_md"])
        if dossier.get("audit_md"):
            dossier["audit_md"] = translator.translate(dossier["audit_md"])

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
