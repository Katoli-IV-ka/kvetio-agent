"""Unit-тесты notion_sync: чистые функции + движок с фейковыми клиентами."""

from __future__ import annotations

import pytest

import notion_sync as ns


def test_load_mapping_reads_entities():
    mapping = ns.load_mapping()
    assert "companies" in mapping
    assert "contacts" in mapping
    fields = mapping["companies"]["fields"]
    names = {f["db_column"] for f in fields}
    assert "name" in names
    for column in ("outreach" + "_status", "outreach" + "_note", "latest" + "_signal"):
        assert column not in names


def test_contacts_mapping_has_company_relation_and_name():
    mapping = ns.load_mapping()
    fields = mapping["contacts"]["fields"]
    by_column = {field["db_column"]: field for field in fields}

    assert by_column["company_page_ids"]["notion_type"] == "relation"
    assert by_column["company_page_ids"]["notion_property"] == "Company"
    assert by_column["name"]["notion_property"] == "Name"
    assert by_column["contact_type"]["notion_type"] == "select"


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
        "db_status_filter": ["relevant"],
        "fields": [
            {"db_column": "name", "notion_property": "Company name",
             "notion_type": "title", "direction": "forward"},
            {"db_column": "icp_segment", "notion_property": "ICP Segment",
             "notion_type": "select", "direction": "forward"},
            {"db_column": "manual_note", "notion_property": "Manual note",
             "notion_type": "rich_text", "direction": "reverse"},
        ],
    }
}


def _engine(rows):
    notion = FakeNotion()
    notion.databases["DBID"] = {"properties": {
        "Company name": {"type": "title"},
        "ICP Segment": {"type": "select"},
        "Manual note": {"type": "rich_text"},
    }}
    db = FakeDb(rows)
    monkey_env = {"NOTION_COMPANIES_DB_ID": "DBID"}
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env=monkey_env)
    return sync, notion, db


def test_forward_creates_page_and_writes_back_id():
    rows = [{"domain": "acme.com", "name": "Acme", "icp_segment": "medical-imaging",
             "status": "relevant", "notion_page_id": None}]
    sync, notion, db = _engine(rows)
    result = sync.sync_forward("companies")
    assert result["created"] == 1
    page_id = db.tables["companies"][0]["notion_page_id"]
    assert page_id is not None
    props = notion.pages[page_id]["properties"]
    assert props["Company name"] == {"title": [{"text": {"content": "Acme"}}]}
    assert props["ICP Segment"] == {"select": {"name": "medical-imaging"}}
    # forward не пишет reverse-поле:
    assert "Manual note" not in props


def test_forward_is_idempotent():
    rows = [{"domain": "acme.com", "name": "Acme", "icp_segment": "medical-imaging",
             "status": "relevant", "notion_page_id": "page-1"}]
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
    rows = [{"domain": "acme.com", "name": "Acme",
             "status": "relevant", "notion_page_id": "page-1",
             "manual_note": None}]
    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {
        "Manual note": {"rich_text": [{"plain_text": "Needs review"}]},
    }, "children": []}
    db = FakeDb(rows)
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.sync_reverse("companies")
    assert result["updated"] == 1
    assert db.tables["companies"][0]["manual_note"] == "Needs review"


def test_reverse_skips_rows_without_page_id():
    rows = [{"domain": "acme.com", "name": "Acme", "notion_page_id": None,
             "status": "relevant"}]
    notion = FakeNotion()
    db = FakeDb(rows)
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.sync_reverse("companies")
    assert result["updated"] == 0


def test_sync_all_runs_reverse_then_forward():
    rows = [{"domain": "acme.com", "name": "Acme", "icp_segment": "medical-imaging",
             "status": "relevant", "notion_page_id": "page-1",
             "manual_note": None}]
    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {
        "Manual note": {"rich_text": [{"plain_text": "Revisit"}]}}, "children": []}
    db = FakeDb(rows)
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.sync_all("companies")
    # reverse подтянул ручное поле в БД:
    assert db.tables["companies"][0]["manual_note"] == "Revisit"
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
    assert "ICP Segment" in props    # создано
    assert "Manual note" in props    # создано
    assert result["created"] == 2
    assert "ICP Segment" in result["created_props"]


def test_ensure_schema_leaves_existing_untouched():
    notion = FakeNotion()
    notion.databases["DBID"] = {"properties": {
        "Company name": {"type": "title"},
        "ICP Segment": {"type": "select"},
        "Manual note": {"type": "rich_text"},
    }}
    db = FakeDb([])
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.ensure_schema("companies")
    assert result["created"] == 0


def test_backfill_imports_reverse_fields_by_page_id():
    rows = [{"domain": "acme.com", "name": "Acme", "status": "relevant",
             "notion_page_id": "page-1", "manual_note": None}]
    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {
        "Manual note": {"rich_text": [{"plain_text": "Won"}]}}, "children": []}
    db = FakeDb(rows)
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.backfill("companies")
    assert result["updated"] == 1
    assert db.tables["companies"][0]["manual_note"] == "Won"


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
    db.tables["companies"] = [{"id": "cid", "domain": "acme.com", "notion_page_id": "page-1"}]
    db.tables["dossiers"] = [{"company_id": "cid",
                              "summary_md": "## О компании\nтекст",
                              "section_summaries": {"financials": "Seed."},
                              "funding_stage": "seed",
                              "icp_fit": "strong",
                              "audit_md": "вывод"}]
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    result = sync.sync_dossiers()
    assert result["updated"] == 1
    children = notion.pages["page-1"]["children"]
    assert any(b["type"] == "heading_2" for b in children)


def test_list_fields_human_readable():
    sync = ns.NotionSync(notion=FakeNotion(), db=FakeDb([]),
                         mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})
    text = sync.list_fields("companies")
    assert "name" in text
    assert "forward" in text
    assert "Manual note" in text


def test_build_arg_parser_accepts_flags():
    parser = ns.build_arg_parser()
    args = parser.parse_args(["--entity", "companies", "--all", "--dry-run"])
    assert args.entity == "companies"
    assert args.all is True
    assert args.dry_run is True


def test_contacts_mapping_matches_compact_schema():
    mapping = ns.load_mapping()
    contacts_fields = {f["notion_property"] for f in mapping["contacts"]["fields"]}
    assert contacts_fields == {
        "Name",
        "Contact Type",
        "Contact Info",
        "Email",
        "Phone",
        "LinkedIn",
        "Facebook",
        "Instagram",
        "Company",
        "Outreach Status",
        "Source",
    }


def test_companies_mapping_matches_release_schema():
    mapping = ns.load_mapping()
    fields = {f["db_column"]: f for f in mapping["companies"]["fields"]}

    expected_columns = {
        "name", "website", "linkedin_url", "icp_segment", "status",
        "description", "funding_info", "team_size_estimate", "potential_data",
        "hq_country", "last_info_update",
    }
    assert set(fields.keys()) == expected_columns
    assert fields["name"]["notion_property"] == "Company Name"
    assert fields["name"]["notion_type"] == "title"
    assert fields["description"]["notion_property"] == "AI Summary"
    assert fields["funding_info"]["source"] == "computed"
    assert fields["team_size_estimate"]["source"] == "dossier"
    assert fields["potential_data"]["notion_type"] == "multi_select"
    assert fields["last_info_update"]["notion_type"] == "date"
    assert mapping["companies"].get("profile_builder") is True
    for f in mapping["companies"]["fields"]:
        assert f["direction"] == "forward"


def test_to_notion_property_phone_number():
    result = ns.to_notion_property("phone_number", "+1-555-0100")
    assert result == {"phone_number": "+1-555-0100"}


def test_to_notion_property_phone_number_none():
    result = ns.to_notion_property("phone_number", None)
    assert result == {"phone_number": None}


def test_to_notion_property_relation():
    result = ns.to_notion_property("relation", ["page-1", "page-2"])
    assert result == {"relation": [{"id": "page-1"}, {"id": "page-2"}]}


def test_to_notion_property_relation_empty():
    result = ns.to_notion_property("relation", [])
    assert result == {"relation": []}


def test_validate_mapping_accepts_phone_number_and_relation():
    mapping = {
        "contacts": {
            "notion_database_id_env": "NOTION_CONTACTS_DB_ID",
            "fields": [
                {"db_column": "name",             "notion_property": "Name",      "notion_type": "title",        "direction": "forward"},
                {"db_column": "phone",            "notion_property": "Phone",     "notion_type": "phone_number", "direction": "forward"},
                {"db_column": "company_page_ids", "notion_property": "Компании",  "notion_type": "relation",     "direction": "forward"},
            ],
        }
    }
    errors = ns.validate_mapping(mapping)
    assert errors == []


def test_validate_mapping_accepts_source_field():
    mapping = {
        "companies": {
            "notion_database_id_env": "ENV",
            "db_table": "companies",
            "db_key": "domain",
            "fields": [
                {
                    "db_column": "funding_info",
                    "notion_property": "Funding Info",
                    "notion_type": "rich_text",
                    "direction": "forward",
                    "source": "computed",
                }
            ],
        }
    }
    # Should not raise
    ns.validate_mapping(mapping)


def test_validate_mapping_rejects_computed_reverse():
    mapping = {
        "companies": {
            "notion_database_id_env": "ENV",
            "db_table": "companies",
            "db_key": "domain",
            "fields": [
                {
                    "db_column": "funding_info",
                    "notion_property": "Funding Info",
                    "notion_type": "rich_text",
                    "direction": "reverse",
                    "source": "computed",
                }
            ],
        }
    }
    errors = ns.validate_mapping(mapping)
    assert any("computed" in e and "reverse" in e for e in errors)


def test_enrich_contact_rows_uses_company_id_relation():
    rows = [
        {"id": "c1", "name": "Alice", "company_id": "co1"},
        {"id": "c2", "name": "Bob", "company_id": "co2"},
    ]
    companies = [
        {"id": "co1", "domain": "acme.com", "notion_page_id": "np-acme"},
        {"id": "co2", "domain": "beta.io", "notion_page_id": "np-beta"},
    ]

    class FakeDb:
        def fetch(self, table, status_filter=None):
            if table == "companies":
                return companies
            raise AssertionError(f"unexpected table read: {table}")

    enriched = ns.enrich_contact_rows(rows, FakeDb())

    assert enriched[0]["company_page_ids"] == ["np-acme"]
    assert enriched[1]["company_page_ids"] == ["np-beta"]


def test_enrich_contact_rows_adds_display_name_and_other_channels_text():
    rows = [
        {
            "id": "c1",
            "name": "Alice Chen",
            "company_id": "co1",
            "other_channels": [
                {"type": "github", "url": "https://github.com/alice", "label": "GitHub"},
                {"type": "personal_website", "url": "https://alice.dev"},
            ],
        },
    ]
    companies = [
        {"id": "co1", "domain": "acme.com", "notion_page_id": "np-acme"},
    ]

    class FakeDb:
        def fetch(self, table, status_filter=None):
            if table == "companies":
                return companies
            raise AssertionError(f"unexpected table read: {table}")

    enriched = ns.enrich_contact_rows(rows, FakeDb())

    assert enriched[0]["name"] == "Alice Chen"
    assert enriched[0]["company_page_ids"] == ["np-acme"]
    assert enriched[0]["other_channels_text"] == (
        "GitHub: https://github.com/alice\n"
        "personal_website: https://alice.dev"
    )


def test_sync_reverse_imports_new_contact_with_single_company_relation():
    mapping = {
        "contacts": {
            "notion_database_id_env": "NOTION_CONTACTS_DB_ID",
            "db_table": "contacts",
            "db_key": "id",
            "fields": [
                {"db_column": "name", "notion_property": "Name", "notion_type": "title", "direction": "reverse"},
                {"db_column": "contact_type", "notion_property": "Type", "notion_type": "select", "direction": "reverse"},
                {"db_column": "email", "notion_property": "Email", "notion_type": "email", "direction": "reverse"},
                {"db_column": "company_page_ids", "notion_property": "Компания", "notion_type": "relation", "direction": "reverse"},
            ],
        }
    }

    class FakeNotion:
        def query_database(self, db_id):
            return [
                {
                    "id": "notion-contact-1",
                    "properties": {
                        "Name": {"title": [{"plain_text": "Alice"}]},
                        "Type": {"select": {"name": "person"}},
                        "Email": {"email": "alice@acme.ai"},
                        "Компания": {"relation": [{"id": "notion-company-1"}]},
                    },
                }
            ]

    class FakeDb:
        def __init__(self):
            self.tables = {
                "contacts": [],
                "companies": [
                    {
                        "id": "company-uuid",
                        "domain": "acme.ai",
                        "notion_page_id": "notion-company-1",
                    }
                ],
            }
            self.inserted = []

        def fetch(self, table, status_filter=None):
            return self.tables[table]

        def update(self, table, key_col, key_val, fields):
            raise AssertionError("new contact import should insert, not update")

        def insert(self, table, fields):
            self.inserted.append((table, fields))

    db = FakeDb()
    sync = ns.NotionSync(
        notion=FakeNotion(),
        db=db,
        mapping=mapping,
        env={"NOTION_CONTACTS_DB_ID": "contacts-db"},
    )

    result = sync.sync_reverse("contacts")

    assert result == {"entity": "contacts", "updated": 0, "created": 1, "errors": 0}
    assert db.inserted == [
        (
            "contacts",
            {
                "name": "Alice",
                "contact_type": "person",
                "email": "alice@acme.ai",
                "company_id": "company-uuid",
                "notion_page_id": "notion-contact-1",
            },
        )
    ]


def test_contact_display_name_uses_name_field():
    assert ns.contact_display_name({"name": "Sarah Chen"}) == "Sarah Chen"


def test_contact_display_name_uses_first_and_last_name():
    assert ns.contact_display_name({"first_name": "Sarah", "last_name": "Chen"}) == "Sarah Chen"


def test_sync_dossiers_reads_typed_fields():
    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {}, "children": []}
    db = FakeDb([])
    db.tables["companies"] = [{"id": "cid", "notion_page_id": "page-1"}]
    db.tables["dossiers"] = [{
        "company_id": "cid",
        "summary_md": "# Rad AI",
        "section_summaries": {"financials": "Seed."},
        "funding_stage": "seed",
        "icp_fit": "strong",
    }]
    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"})

    result = sync.sync_dossiers(dry_run=True)

    assert result["entity"] == "dossiers"
    assert result["updated"] == 1


def test_no_dossiers_entity_in_mapping():
    mapping = ns.load_mapping()
    assert "dossiers" not in mapping


def test_sync_dossiers_translates_prose_fields():
    """translator.translate() is called on summary_md, section_summaries values, and audit_md."""
    from unittest.mock import MagicMock

    translations = {
        "English summary": "Русский summary",
        "English audit": "Русский audit",
        "Intro section": "Вступительный раздел",
    }
    translator = MagicMock()
    translator.translate.side_effect = lambda t: translations.get(t, t)

    notion = FakeNotion()
    notion.pages["page-1"] = {"_db": "DBID", "properties": {}, "children": []}
    db = FakeDb([])
    db.tables["companies"] = [{"id": "cid", "domain": "acme.com", "notion_page_id": "page-1"}]
    db.tables["dossiers"] = [{
        "company_id": "cid",
        "summary_md": "English summary",
        "audit_md": "English audit",
        "section_summaries": {"intro": "Intro section"},
        "team_size_estimate": "11-50",
    }]

    sync = ns.NotionSync(notion=notion, db=db, mapping=COMPANIES_MAPPING,
                         env={"NOTION_COMPANIES_DB_ID": "DBID"}, translator=translator)
    sync.sync_dossiers()

    translator.translate.assert_any_call("English summary")
    translator.translate.assert_any_call("English audit")
    translator.translate.assert_any_call("Intro section")


def test_sync_forward_uses_profile_builder_when_flag_set():
    """When mapping has profile_builder:true, sync_forward uses build_company_profiles."""
    from unittest.mock import patch, MagicMock

    profile_mapping = {
        "companies": {
            "notion_database_id_env": "NOTION_COMPANIES_DB_ID",
            "db_table": "companies",
            "db_key": "domain",
            "db_status_filter": ["relevant"],
            "profile_builder": True,
            "fields": [
                {"db_column": "name", "notion_property": "Company Name",
                 "notion_type": "title", "direction": "forward", "source": "db_column"},
                {"db_column": "funding_info", "notion_property": "Funding Info",
                 "notion_type": "rich_text", "direction": "forward", "source": "computed"},
            ],
        }
    }

    rows = [{"domain": "acme.com", "name": "Acme", "status": "relevant",
             "notion_page_id": None, "notion_synced_at": None}]
    notion = FakeNotion()
    notion.databases["DBID"] = {"properties": {
        "Company Name": {"type": "title"},
        "Funding Info": {"type": "rich_text"},
    }}
    db = FakeDb(rows)

    built_profiles = [
        {"domain": "acme.com", "name": "Acme", "funding_info": "$5M Seed",
         "notion_page_id": None, "notion_synced_at": None,
         "id": 1, "linkedin_url": None}
    ]

    with patch("notion_sync.build_company_profiles", return_value=built_profiles) as mock_build, \
         patch("notion_sync.load_potential_cfg", return_value={}) as mock_cfg:
        sync = ns.NotionSync(notion=notion, db=db, mapping=profile_mapping,
                             env={"NOTION_COMPANIES_DB_ID": "DBID"})
        result = sync.sync_forward("companies")

    mock_build.assert_called_once()
    call_args = mock_build.call_args
    passed_rows = call_args[0][0]  # first positional arg is company_rows
    assert [r["domain"] for r in passed_rows] == [r["domain"] for r in rows]
    assert result["created"] == 1
