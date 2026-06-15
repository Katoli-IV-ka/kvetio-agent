"""Unit-тесты notion_sync: чистые функции + движок с фейковыми клиентами."""

from __future__ import annotations

from pathlib import Path

import pytest

import notion_sync as ns


def test_load_mapping_reads_entities():
    mapping = ns.load_mapping()
    assert "companies" in mapping
    assert "contacts" in mapping
    fields = mapping["companies"]["fields"]
    names = {f["db_column"] for f in fields}
    assert "name" in names
    assert "outreach_status" in names


def test_validate_mapping_flags_bad_type():
    mapping = {
        "companies": {
            "notion_database_id_env": "NOTION_COMPANIES_DB_ID",
            "fields": [
                {"db_column": "name", "notion_property": "Name",
                 "notion_type": "title", "direction": "forward"},
                {"db_column": "score", "notion_property": "Score",
                 "notion_type": "bogus", "direction": "forward"},
            ],
        }
    }
    errors = ns.validate_mapping(mapping)
    assert any("bogus" in e for e in errors)


def test_validate_mapping_flags_bad_direction():
    mapping = {
        "companies": {
            "notion_database_id_env": "NOTION_COMPANIES_DB_ID",
            "fields": [
                {"db_column": "name", "notion_property": "Name",
                 "notion_type": "title", "direction": "sideways"},
            ],
        }
    }
    errors = ns.validate_mapping(mapping)
    assert any("sideways" in e for e in errors)


@pytest.mark.parametrize("ntype,value,expected", [
    ("title", "Acme", {"title": [{"text": {"content": "Acme"}}]}),
    ("rich_text", "hi", {"rich_text": [{"text": {"content": "hi"}}]}),
    ("url", "https://a.co", {"url": "https://a.co"}),
    ("email", "a@b.co", {"email": "a@b.co"}),
    ("number", 42, {"number": 42}),
    ("select", "Hot", {"select": {"name": "Hot"}}),
    ("date", "2026-06-15", {"date": {"start": "2026-06-15"}}),
])
def test_to_notion_property(ntype, value, expected):
    assert ns.to_notion_property(ntype, value) == expected


def test_to_notion_property_none_clears_value():
    assert ns.to_notion_property("select", None) == {"select": None}
    assert ns.to_notion_property("url", None) == {"url": None}
    assert ns.to_notion_property("title", None) == {"title": []}


def test_from_notion_property_roundtrip():
    assert ns.from_notion_property("select", {"select": {"name": "Hot"}}) == "Hot"
    assert ns.from_notion_property("rich_text",
        {"rich_text": [{"plain_text": "note"}]}) == "note"
    assert ns.from_notion_property("select", {"select": None}) is None
    assert ns.from_notion_property("rich_text", {"rich_text": []}) is None


class FakeNotion:
    """In-memory Notion gateway double."""
    def __init__(self):
        self.pages = {}       # page_id -> {"properties": {...}, "children": [...]}
        self.databases = {}   # db_id -> {"properties": {name: {"type": ...}}}
        self._seq = 0

    def query_database(self, db_id):
        return [{"id": pid, **p} for pid, p in self.pages.items()
                if p.get("_db") == db_id]

    def create_page(self, db_id, properties, children=None):
        self._seq += 1
        pid = f"page-{self._seq}"
        self.pages[pid] = {"_db": db_id, "properties": properties,
                           "children": list(children or [])}
        return {"id": pid}

    def update_page(self, page_id, properties):
        self.pages[page_id]["properties"].update(properties)
        return {"id": page_id}

    def append_children(self, page_id, children):
        self.pages[page_id].setdefault("children", []).extend(children)

    def retrieve_database(self, db_id):
        return {"properties": self.databases.get(db_id, {}).get("properties", {})}

    def update_database(self, db_id, properties):
        db = self.databases.setdefault(db_id, {"properties": {}})
        db["properties"].update(properties)


class FakeDb:
    """In-memory DB gateway double."""
    def __init__(self, rows=None):
        self.tables = {"companies": list(rows or [])}

    def fetch(self, table, status_filter=None):
        rows = self.tables.get(table, [])
        if status_filter:
            rows = [r for r in rows if r.get("status") in status_filter]
        return [dict(r) for r in rows]

    def update(self, table, key_col, key_val, fields):
        for r in self.tables.setdefault(table, []):
            if r.get(key_col) == key_val:
                r.update(fields)
                return


COMPANIES_MAPPING = {
    "companies": {
        "notion_database_id_env": "NOTION_COMPANIES_DB_ID",
        "db_table": "companies",
        "db_key": "domain",
        "db_status_filter": ["qualified"],
        "fields": [
            {"db_column": "name", "notion_property": "Company name",
             "notion_type": "title", "direction": "forward"},
            {"db_column": "score", "notion_property": "Score",
             "notion_type": "number", "direction": "forward"},
            {"db_column": "outreach_status", "notion_property": "Статус анализа",
             "notion_type": "select", "direction": "reverse"},
        ],
    }
}


def _engine(rows):
    notion = FakeNotion()
    notion.databases["DBID"] = {"properties": {
        "Company name": {"type": "title"},
        "Score": {"type": "number"},
        "Статус анализа": {"type": "select"},
    }}
    db = FakeDb(rows)
    monkey_env = {"NOTION_COMPANIES_DB_ID": "DBID"}
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env=monkey_env)
    return sync, notion, db


def test_forward_creates_page_and_writes_back_id():
    rows = [{"domain": "acme.com", "name": "Acme", "score": 80,
             "status": "qualified", "notion_page_id": None}]
    sync, notion, db = _engine(rows)
    result = sync.sync_forward("companies")
    assert result["created"] == 1
    page_id = db.tables["companies"][0]["notion_page_id"]
    assert page_id is not None
    props = notion.pages[page_id]["properties"]
    assert props["Company name"] == {"title": [{"text": {"content": "Acme"}}]}
    assert props["Score"] == {"number": 80}
    # forward не пишет reverse-поле:
    assert "Статус анализа" not in props


def test_forward_is_idempotent():
    rows = [{"domain": "acme.com", "name": "Acme", "score": 80,
             "status": "qualified", "notion_page_id": "page-1"}]
    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {}, "children": []}
    db = FakeDb(rows)
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    r1 = sync.sync_forward("companies")
    r2 = sync.sync_forward("companies")
    assert r1["updated"] == 1
    assert r2["updated"] == 1
    assert len(notion.pages) == 1  # без дублей


def test_reverse_pulls_whitelist_into_db():
    rows = [{"domain": "acme.com", "name": "Acme", "score": 80,
             "status": "qualified", "notion_page_id": "page-1",
             "outreach_status": None}]
    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {
        "Статус анализа": {"select": {"name": "Contacted"}},
    }, "children": []}
    db = FakeDb(rows)
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.sync_reverse("companies")
    assert result["updated"] == 1
    assert db.tables["companies"][0]["outreach_status"] == "Contacted"


def test_reverse_skips_rows_without_page_id():
    rows = [{"domain": "acme.com", "name": "Acme", "notion_page_id": None,
             "status": "qualified"}]
    notion = FakeNotion()
    db = FakeDb(rows)
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.sync_reverse("companies")
    assert result["updated"] == 0


def test_sync_all_runs_reverse_then_forward():
    rows = [{"domain": "acme.com", "name": "Acme", "score": 80,
             "status": "qualified", "notion_page_id": "page-1",
             "outreach_status": None}]
    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {
        "Статус анализа": {"select": {"name": "Replied"}}}, "children": []}
    db = FakeDb(rows)
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.sync_all("companies")
    # reverse подтянул статус в БД:
    assert db.tables["companies"][0]["outreach_status"] == "Replied"
    # forward обновил страницу:
    assert result["forward"]["updated"] == 1


NOTION_TYPE_SCHEMA = {
    "title": {"title": {}}, "rich_text": {"rich_text": {}}, "url": {"url": {}},
    "email": {"email": {}}, "number": {"number": {}}, "select": {"select": {}},
    "multi_select": {"multi_select": {}}, "date": {"date": {}},
}


def test_ensure_schema_creates_missing_props():
    notion = FakeNotion()
    notion.databases["DBID"] = {"properties": {"Company name": {"type": "title"}}}
    db = FakeDb([])
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.ensure_schema("companies")
    props = notion.databases["DBID"]["properties"]
    assert "Score" in props          # создано
    assert "Статус анализа" in props # создано
    assert result["created"] == 2
    assert "Score" in result["created_props"]


def test_ensure_schema_leaves_existing_untouched():
    notion = FakeNotion()
    notion.databases["DBID"] = {"properties": {
        "Company name": {"type": "title"},
        "Score": {"type": "number"},
        "Статус анализа": {"type": "select"},
    }}
    db = FakeDb([])
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.ensure_schema("companies")
    assert result["created"] == 0


def test_backfill_imports_reverse_fields_by_page_id():
    rows = [{"domain": "acme.com", "name": "Acme", "status": "qualified",
             "notion_page_id": "page-1", "outreach_status": None}]
    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {
        "Статус анализа": {"select": {"name": "Won"}}}, "children": []}
    db = FakeDb(rows)
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.backfill("companies")
    assert result["updated"] == 1
    assert db.tables["companies"][0]["outreach_status"] == "Won"


def test_md_to_blocks_makes_heading_and_paragraphs():
    blocks = ns.md_to_blocks("О компании", "Строка 1\n\nСтрока 2")
    assert blocks[0]["type"] == "heading_2"
    assert blocks[0]["heading_2"]["rich_text"][0]["text"]["content"] == "О компании"
    paras = [b for b in blocks if b["type"] == "paragraph"]
    assert len(paras) == 2
    assert paras[0]["paragraph"]["rich_text"][0]["text"]["content"] == "Строка 1"


def test_sync_dossier_appends_blocks_to_company_page():
    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {}, "children": []}
    db = FakeDb([])
    db.tables["companies"] = [{"domain": "acme.com", "notion_page_id": "page-1"}]
    db.tables["dossiers"] = [{"company_domain": "acme.com",
                              "summary_md": "## О компании\nтекст",
                              "audit_md": "вывод"}]
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.sync_dossiers()
    assert result["updated"] == 1
    children = notion.pages["page-1"]["children"]
    assert any(b["type"] == "heading_2" for b in children)
