# Contacts Schema Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify `contacts` into a compact outreach contact table with structured names, primary contact channels, `info`, and flexible `other_channels` without AI confidence or email status fields.

**Architecture:** `contacts` stores current contact state only. Primary outreach channels are first-class columns; secondary profile/discovery channels live in `other_channels` JSONB and must not duplicate primary channel fields. Notion receives computed display fields from `notion_sync.py`, while source/provenance history is intentionally left for the later `signals` redesign.

**Tech Stack:** PostgreSQL/Supabase SQL baseline, Python 3.11, Supabase Python client, Notion sync mapping YAML, pytest.

---

## Product Spec

### Target `contacts` Contract

`contacts` should answer: who is this contact for a company, what is useful context about them, and where can we reach them?

Target columns:

```sql
CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id),

    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL DEFAULT '',
    info TEXT,

    email TEXT,
    phone TEXT,
    linkedin_url TEXT,
    x_url TEXT,
    facebook_url TEXT,
    instagram_url TEXT,

    other_channels JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(other_channels) = 'array'),

    notion_page_id TEXT,
    notion_synced_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

Target indexes:

```sql
CREATE UNIQUE INDEX idx_contacts_company_name
    ON contacts (company_id, lower(first_name), lower(last_name));
CREATE INDEX idx_contacts_company_id
    ON contacts (company_id);
CREATE INDEX idx_contacts_email
    ON contacts (email)
    WHERE email IS NOT NULL;
```

`last_name` is stored as empty string when unknown, not `NULL`. This is deliberate: Postgres unique indexes treat `NULL` values as distinct, which would allow duplicate contacts for `(company_id, first_name, NULL)`.

### Removed Columns

Remove these fields from the active schema, store layer, models, tests, and Notion mapping:

```text
company_domain
full_name
title
title_normalized
dm_priority
email_status
email_source
twitter_handle
github_username
hf_username
personal_website
source_vector
source_url
confidence
raw_payload
contact_type
```

### Kept / Renamed Semantics

| Old field | New field | Rule |
|---|---|---|
| `title`, `title_normalized`, `info` | `info` | One human-readable context field |
| `twitter_handle` | `x_url` | Store full URL, not handle |
| `github_username` | `other_channels` | Store as `{"type":"github","url":"https://github.com/<username>"}` |
| `hf_username` | `other_channels` | Store as `{"type":"huggingface","url":"https://huggingface.co/<username>"}` |
| `personal_website` | `other_channels` | Store as `{"type":"personal_website","url":"..."}` |

### Primary Channel Rule

If a channel has a first-class contact column, it must not also appear in `other_channels`.

Primary columns:

```text
email
phone
linkedin_url
x_url
facebook_url
instagram_url
```

Disallowed `other_channels[*].type` values:

```text
email
phone
linkedin
linkedin_url
x
twitter
twitter_url
facebook
facebook_url
instagram
instagram_url
```

Valid `other_channels` examples:

```json
[
  {"type": "github", "url": "https://github.com/alicechen", "label": "GitHub"},
  {"type": "huggingface", "url": "https://huggingface.co/alicechen"},
  {"type": "personal_website", "url": "https://alicechen.dev"}
]
```

Invalid `other_channels` example:

```json
[
  {"type": "linkedin", "url": "https://www.linkedin.com/in/alicechen"},
  {"type": "x", "url": "https://x.com/alicechen"}
]
```

Those URLs belong in `linkedin_url` and `x_url`.

### Out Of Scope

- Redesigning `signals`.
- Adding contact-to-signal references.
- Storing message send/reply/bounce history.
- Reverse syncing manual contact data from Notion.

These belong in later work.

## File Structure

- Modify: `sql/schema.sql`
- Modify: `scripts/contacts_store.py`
- Modify: `scripts/models.py`
- Modify: `scripts/notion_sync.py`
- Modify: `config/notion_mapping.yaml`
- Modify: `agents/prompts/dm_enrich_task.md`
- Modify: `scripts/dm_apollo.py`
- Modify: `scripts/dm_contact_page.py`
- Modify: `scripts/dm_github.py`
- Modify: `scripts/dm_huggingface_contacts.py`
- Modify: `scripts/dm_wellfound.py`
- Modify: `scripts/contact_enricher.py`
- Modify: `tests/test_migrations.py`
- Modify: `tests/test_contacts_store.py`
- Modify: `tests/test_notion_sync.py`
- Modify: `tests/test_models_cleanup.py`
- Modify: `tests/test_contact_enricher.py`
- Modify: `docs/DB-FIELD-AUDIT-2026-06-18.md`

## Task 1: Rewrite Schema Contract Tests For Contacts

**Files:**
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Replace contact-specific schema tests**

In `tests/test_migrations.py`, replace the existing contact tests with these tests:

```python
def test_contacts_schema_is_compact_outreach_contract() -> None:
    sql = _schema()
    assert "CREATE TABLE contacts" in sql
    for column in (
        "company_id UUID NOT NULL REFERENCES companies(id)",
        "first_name TEXT NOT NULL",
        "last_name TEXT NOT NULL DEFAULT ''",
        "info TEXT",
        "email TEXT",
        "phone TEXT",
        "linkedin_url TEXT",
        "x_url TEXT",
        "facebook_url TEXT",
        "instagram_url TEXT",
        "other_channels JSONB NOT NULL DEFAULT '[]'::jsonb",
        "notion_page_id TEXT",
        "notion_synced_at TIMESTAMPTZ",
    ):
        assert column in sql


def test_contacts_schema_removed_legacy_fields() -> None:
    sql = _schema()
    for removed in (
        "company_domain",
        "full_name",
        "title TEXT",
        "title_normalized",
        "dm_priority",
        "email_status",
        "email_source",
        "twitter_handle",
        "github_username",
        "hf_username",
        "personal_website",
        "source_vector",
        "source_url",
        "confidence TEXT",
        "raw_payload",
        "contact_type",
    ):
        assert removed not in sql


def test_contacts_schema_uses_company_name_dedup() -> None:
    sql = _schema()
    assert "CREATE UNIQUE INDEX idx_contacts_company_name" in sql
    assert "ON contacts (company_id, lower(first_name), lower(last_name))" in sql
    assert "idx_contacts_company_id" in sql
    assert "idx_contacts_email" in sql
```

- [ ] **Step 2: Run the schema tests and verify they fail**

Run:

```bash
python3 -m pytest tests/test_migrations.py -q
```

Expected: fail because `sql/schema.sql` still contains the old `contacts` fields.

## Task 2: Update `sql/schema.sql`

**Files:**
- Modify: `sql/schema.sql`

- [ ] **Step 1: Replace the contacts table block**

Replace the full `CREATE TABLE contacts ... trg_contacts_updated_at` block in `sql/schema.sql` with:

```sql
CREATE TABLE contacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id UUID NOT NULL REFERENCES companies(id),

    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL DEFAULT '',
    info TEXT,

    email TEXT,
    phone TEXT,
    linkedin_url TEXT,
    x_url TEXT,
    facebook_url TEXT,
    instagram_url TEXT,

    other_channels JSONB NOT NULL DEFAULT '[]'::jsonb
        CHECK (jsonb_typeof(other_channels) = 'array'),

    notion_page_id TEXT,
    notion_synced_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_contacts_company_name
    ON contacts (company_id, lower(first_name), lower(last_name));
CREATE INDEX idx_contacts_company_id
    ON contacts (company_id);
CREATE INDEX idx_contacts_email
    ON contacts (email)
    WHERE email IS NOT NULL;

DROP TRIGGER IF EXISTS trg_contacts_updated_at ON contacts;
CREATE TRIGGER trg_contacts_updated_at
BEFORE UPDATE ON contacts
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

- [ ] **Step 2: Run schema tests and verify they pass**

Run:

```bash
python3 -m pytest tests/test_migrations.py -q
```

Expected: pass.

## Task 3: Add Contact Normalization Helpers

**Files:**
- Modify: `scripts/contacts_store.py`
- Test: `tests/test_contacts_store.py`

- [ ] **Step 1: Add tests for name and channel normalization**

Append these tests to `tests/test_contacts_store.py`:

```python
def test_split_full_name_supports_legacy_payloads():
    from contacts_store import split_contact_name

    assert split_contact_name({"first_name": "Sarah", "last_name": "Chen"}) == ("Sarah", "Chen")
    assert split_contact_name({"full_name": "Sarah Chen"}) == ("Sarah", "Chen")
    assert split_contact_name({"full_name": "Prince"}) == ("Prince", "")


def test_normalize_other_channels_removes_primary_channel_duplicates():
    from contacts_store import normalize_other_channels

    channels = normalize_other_channels(
        {
            "linkedin_url": "https://www.linkedin.com/in/alice",
            "x_url": "https://x.com/alice",
            "github_username": "alice",
            "hf_username": "alice-hf",
            "personal_website": "https://alice.dev",
            "other_channels": [
                {"type": "linkedin", "url": "https://www.linkedin.com/in/alice"},
                {"type": "github", "url": "https://github.com/alice"},
                {"type": "github", "url": "https://github.com/alice"},
                {"type": "substack", "url": "https://alice.substack.com", "label": "Substack"},
            ],
        }
    )

    assert channels == [
        {"type": "github", "url": "https://github.com/alice"},
        {"type": "huggingface", "url": "https://huggingface.co/alice-hf"},
        {"type": "personal_website", "url": "https://alice.dev"},
        {"type": "substack", "url": "https://alice.substack.com", "label": "Substack"},
    ]


def test_normalize_x_url_accepts_twitter_handle():
    from contacts_store import normalize_x_url

    assert normalize_x_url({"x_url": "https://x.com/alice"}) == "https://x.com/alice"
    assert normalize_x_url({"twitter_handle": "alice"}) == "https://x.com/alice"
    assert normalize_x_url({"twitter_handle": "@alice"}) == "https://x.com/alice"
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
python3 -m pytest tests/test_contacts_store.py::test_split_full_name_supports_legacy_payloads tests/test_contacts_store.py::test_normalize_other_channels_removes_primary_channel_duplicates tests/test_contacts_store.py::test_normalize_x_url_accepts_twitter_handle -q
```

Expected: fail because helper functions do not exist.

- [ ] **Step 3: Add helper functions**

Add these constants and functions near the top of `scripts/contacts_store.py`, after `logger = logging.getLogger(__name__)`:

```python
PRIMARY_OTHER_CHANNEL_TYPES = {
    "email",
    "phone",
    "linkedin",
    "linkedin_url",
    "x",
    "twitter",
    "twitter_url",
    "facebook",
    "facebook_url",
    "instagram",
    "instagram_url",
}


def split_contact_name(contact: dict) -> tuple[str, str]:
    """Return first/last name, accepting legacy full_name payloads."""
    first = (contact.get("first_name") or "").strip()
    last = (contact.get("last_name") or "").strip()
    if first:
        return first, last

    full_name = (contact.get("full_name") or "").strip()
    if not full_name:
        raise ValueError("first_name or full_name is required")

    parts = full_name.split(maxsplit=1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def normalize_x_url(contact: dict) -> str | None:
    """Return a full X URL from x_url, twitter_url, or twitter_handle."""
    explicit = contact.get("x_url") or contact.get("twitter_url")
    if explicit:
        return explicit
    handle = (contact.get("twitter_handle") or "").strip()
    if not handle:
        return None
    return f"https://x.com/{handle.lstrip('@')}"


def _channel(type_: str, url: str, label: str | None = None) -> dict:
    item = {"type": type_, "url": url}
    if label:
        item["label"] = label
    return item


def normalize_other_channels(contact: dict) -> list[dict]:
    """Normalize secondary contact channels and remove primary-channel duplicates."""
    candidates: list[dict] = []

    github_username = (contact.get("github_username") or "").strip()
    if github_username:
        candidates.append(_channel("github", f"https://github.com/{github_username}"))

    hf_username = (contact.get("hf_username") or "").strip()
    if hf_username:
        candidates.append(_channel("huggingface", f"https://huggingface.co/{hf_username}"))

    personal_website = contact.get("personal_website")
    if personal_website:
        candidates.append(_channel("personal_website", personal_website))

    for item in contact.get("other_channels") or []:
        if not isinstance(item, dict):
            continue
        type_ = str(item.get("type") or "").strip()
        url = str(item.get("url") or "").strip()
        if not type_ or not url:
            continue
        if type_ in PRIMARY_OTHER_CHANNEL_TYPES:
            continue
        normalized = {"type": type_, "url": url}
        if item.get("label"):
            normalized["label"] = str(item["label"])
        candidates.append(normalized)

    seen: set[tuple[str, str]] = set()
    result: list[dict] = []
    for item in candidates:
        key = (item["type"], item["url"])
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
```

- [ ] **Step 4: Run helper tests and verify they pass**

Run:

```bash
python3 -m pytest tests/test_contacts_store.py::test_split_full_name_supports_legacy_payloads tests/test_contacts_store.py::test_normalize_other_channels_removes_primary_channel_duplicates tests/test_contacts_store.py::test_normalize_x_url_accepts_twitter_handle -q
```

Expected: pass.

## Task 4: Rewrite Contact Upsert And Listing

**Files:**
- Modify: `scripts/contacts_store.py`
- Modify: `tests/test_contacts_store.py`

- [ ] **Step 1: Replace upsert/list tests with compact schema expectations**

In `tests/test_contacts_store.py`, update the main upsert tests so they assert the new row shape:

```python
def test_upsert_contact_sets_compact_fields(mock_store):
    contact = {
        "company_domain": "radai.com",
        "first_name": "Sarah",
        "last_name": "Chen",
        "info": "Head of ML; likely owns dataset/vendor decisions.",
        "email": "sarah@radai.com",
        "phone": "+1-555-0100",
        "linkedin_url": "https://www.linkedin.com/in/sarahchen",
        "x_url": "https://x.com/sarahchen",
        "facebook_url": "https://facebook.com/sarahchen",
        "instagram_url": "https://instagram.com/sarahchen",
        "github_username": "sarahchen",
    }

    upsert_contact(mock_store, contact)

    mock_store._client.table.assert_called_with("contacts")
    call_args = mock_store._client.table.return_value.upsert.call_args
    row = call_args[0][0]
    assert row == {
        "company_id": "company-uuid",
        "first_name": "Sarah",
        "last_name": "Chen",
        "info": "Head of ML; likely owns dataset/vendor decisions.",
        "email": "sarah@radai.com",
        "phone": "+1-555-0100",
        "linkedin_url": "https://www.linkedin.com/in/sarahchen",
        "x_url": "https://x.com/sarahchen",
        "facebook_url": "https://facebook.com/sarahchen",
        "instagram_url": "https://instagram.com/sarahchen",
        "other_channels": [{"type": "github", "url": "https://github.com/sarahchen"}],
        "updated_at": row["updated_at"],
    }
    assert call_args[1]["on_conflict"] == "company_id,first_name,last_name"
    for removed in (
        "company_domain",
        "full_name",
        "title",
        "title_normalized",
        "dm_priority",
        "email_status",
        "email_source",
        "twitter_handle",
        "github_username",
        "hf_username",
        "personal_website",
        "source_vector",
        "source_url",
        "confidence",
        "raw_payload",
        "contact_type",
    ):
        assert removed not in row
```

Update the list test to expect filtering by resolved `company_id`:

```python
def test_list_contacts_resolves_company_and_queries_by_company_id(mock_store):
    mock_store._client.table.return_value.execute.return_value = MagicMock(
        data=[{"first_name": "Sarah", "last_name": "Chen"}]
    )

    results = list_contacts(mock_store, "radai.com")

    assert len(results) == 1
    assert results[0]["first_name"] == "Sarah"
    mock_store._client.table.return_value.eq.assert_any_call("company_id", "company-uuid")
```

- [ ] **Step 2: Run contact store tests and verify failures**

Run:

```bash
python3 -m pytest tests/test_contacts_store.py -q
```

Expected: fail because `upsert_contact()` still writes the old row shape and conflict key.

- [ ] **Step 3: Update `upsert_contact()`**

Replace the `upsert_contact()` body in `scripts/contacts_store.py` with:

```python
def upsert_contact(store: SupabaseStore, contact: dict) -> str:
    """Upsert one contact. Conflict key: (company_id, first_name, last_name)."""
    company_ref = resolve_company_ref(
        store,
        domain=contact.get("company_domain"),
        company_id=contact.get("company_id"),
    )
    first_name, last_name = split_contact_name(contact)
    row = {
        "company_id": company_ref["id"],
        "first_name": first_name,
        "last_name": last_name,
        "info": contact.get("info") or contact.get("title") or contact.get("title_normalized"),
        "email": contact.get("email"),
        "phone": contact.get("phone"),
        "linkedin_url": contact.get("linkedin_url"),
        "x_url": normalize_x_url(contact),
        "facebook_url": contact.get("facebook_url"),
        "instagram_url": contact.get("instagram_url"),
        "other_channels": normalize_other_channels(contact),
        "updated_at": datetime.utcnow().isoformat(),
    }
    res = store._client.table("contacts").upsert(
        row, on_conflict="company_id,first_name,last_name"
    ).execute()
    logger.debug("upsert_contact: %s / %s %s", company_ref["domain"], first_name, last_name)
    if res.data:
        return res.data[0]["id"]
    return ""
```

- [ ] **Step 4: Update `list_contacts()`**

Replace `list_contacts()` with:

```python
def list_contacts(store: SupabaseStore, domain: str) -> list[dict]:
    """Return company contacts ordered by first name."""
    company_ref = resolve_company_ref(store, domain=domain)
    res = (
        store._client.table("contacts")
        .select("*")
        .eq("company_id", company_ref["id"])
        .order("first_name")
        .execute()
    )
    return res.data or []
```

- [ ] **Step 5: Run contact store tests**

Run:

```bash
python3 -m pytest tests/test_contacts_store.py -q
```

Expected: pass after removing or updating obsolete tests that assert old fields like `personal_website`, `contact_type`, `dm_priority`, or `company_domain` in the upsert row.

## Task 5: Update Contact Domain Model

**Files:**
- Modify: `scripts/models.py`
- Modify: `tests/test_models_cleanup.py`

- [ ] **Step 1: Update the model test**

Replace `test_contact_record_supports_company_id_and_related_person()` in `tests/test_models_cleanup.py` with:

```python
def test_contact_record_matches_compact_contact_schema() -> None:
    contact = ContactRecord(
        company_id="00000000-0000-0000-0000-000000000001",
        first_name="Jane",
        last_name="Advisor",
        info="Advisor to the ML team; possible warm intro path.",
        linkedin_url="https://www.linkedin.com/in/janeadvisor",
        x_url="https://x.com/janeadvisor",
        other_channels=[
            {"type": "github", "url": "https://github.com/janeadvisor"},
        ],
    )

    assert contact.company_id == "00000000-0000-0000-0000-000000000001"
    assert contact.first_name == "Jane"
    assert contact.last_name == "Advisor"
    assert contact.info == "Advisor to the ML team; possible warm intro path."
    assert contact.other_channels == [
        {"type": "github", "url": "https://github.com/janeadvisor"},
    ]
```

- [ ] **Step 2: Run model cleanup test and verify it fails**

Run:

```bash
python3 -m pytest tests/test_models_cleanup.py -q
```

Expected: fail because `ContactRecord` still requires `company_domain` and `full_name`.

- [ ] **Step 3: Replace contact type definitions**

In `scripts/models.py`, replace `EmailStatus`, `ContactType`, and the `ContactRecord` class with:

```python
OtherChannel = dict[str, str]


@dataclass
class ContactRecord:
    """Current outreach contact for a company."""

    company_id: str
    first_name: str
    last_name: str = ""

    info: str | None = None

    email: str | None = None
    phone: str | None = None
    linkedin_url: str | None = None
    x_url: str | None = None
    facebook_url: str | None = None
    instagram_url: str | None = None

    other_channels: list[OtherChannel] = field(default_factory=list)
```

- [ ] **Step 4: Run model cleanup test**

Run:

```bash
python3 -m pytest tests/test_models_cleanup.py -q
```

Expected: pass.

## Task 6: Update Notion Contact Projection

**Files:**
- Modify: `config/notion_mapping.yaml`
- Modify: `scripts/notion_sync.py`
- Modify: `tests/test_notion_sync.py`

- [ ] **Step 1: Update mapping expectations**

In `tests/test_notion_sync.py`, replace `test_contacts_mapping_has_v2_fields()` with:

```python
def test_contacts_mapping_matches_compact_schema():
    mapping = ns.load_mapping()
    contacts_fields = {f["notion_property"] for f in mapping["contacts"]["fields"]}
    assert contacts_fields == {
        "Name",
        "Информация о контакте",
        "Email",
        "Phone",
        "LinkedIn",
        "X",
        "Facebook",
        "Instagram",
        "Другие каналы",
        "Компании",
    }
```

Add a computed fields test:

```python
def test_enrich_contact_rows_adds_display_name_and_other_channels_text():
    rows = [
        {
            "id": "c1",
            "first_name": "Alice",
            "last_name": "Chen",
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

    assert enriched[0]["contact_name"] == "Alice Chen"
    assert enriched[0]["company_page_ids"] == ["np-acme"]
    assert enriched[0]["other_channels_text"] == (
        "GitHub: https://github.com/alice\n"
        "personal_website: https://alice.dev"
    )
```

- [ ] **Step 2: Run Notion tests and verify failures**

Run:

```bash
python3 -m pytest tests/test_notion_sync.py::test_contacts_mapping_matches_compact_schema tests/test_notion_sync.py::test_enrich_contact_rows_adds_display_name_and_other_channels_text -q
```

Expected: fail because mapping and computed fields still use old contact fields.

- [ ] **Step 3: Update `config/notion_mapping.yaml` contacts fields**

Replace the `contacts.fields` list with:

```yaml
  fields:
    - { db_column: contact_name,       notion_property: "Name",                  notion_type: title,        direction: forward }
    - { db_column: info,               notion_property: "Информация о контакте", notion_type: rich_text,    direction: forward }
    - { db_column: email,              notion_property: "Email",                 notion_type: email,        direction: forward }
    - { db_column: phone,              notion_property: "Phone",                 notion_type: phone_number, direction: forward }
    - { db_column: linkedin_url,       notion_property: "LinkedIn",              notion_type: url,          direction: forward }
    - { db_column: x_url,              notion_property: "X",                     notion_type: url,          direction: forward }
    - { db_column: facebook_url,       notion_property: "Facebook",              notion_type: url,          direction: forward }
    - { db_column: instagram_url,      notion_property: "Instagram",             notion_type: url,          direction: forward }
    - { db_column: other_channels_text, notion_property: "Другие каналы",         notion_type: rich_text,    direction: forward }
    - { db_column: company_page_ids,   notion_property: "Компании",              notion_type: relation,     direction: forward }
```

- [ ] **Step 4: Add computed helpers to `notion_sync.py`**

Add these functions above `enrich_contact_rows()`:

```python
def contact_display_name(row: dict) -> str:
    first = str(row.get("first_name") or "").strip()
    last = str(row.get("last_name") or "").strip()
    return " ".join(part for part in (first, last) if part) or "Unknown contact"


def other_channels_text(row: dict) -> str | None:
    channels = row.get("other_channels") or []
    lines: list[str] = []
    for item in channels:
        if not isinstance(item, dict):
            continue
        type_ = str(item.get("label") or item.get("type") or "").strip()
        url = str(item.get("url") or "").strip()
        if type_ and url:
            lines.append(f"{type_}: {url}")
    return "\n".join(lines) if lines else None
```

Then update `enrich_contact_rows()` so each row includes:

```python
enriched.append({
    **row,
    "contact_name": contact_display_name(row),
    "other_channels_text": other_channels_text(row),
    "company_page_ids": [page_id] if page_id else [],
})
```

- [ ] **Step 5: Run Notion sync tests**

Run:

```bash
python3 -m pytest tests/test_notion_sync.py -q
```

Expected: pass after updating old tests that still refer to `full_name`, `Title`, `Тип контакта`, or `Источник`.

## Task 7: Update DM Source Outputs And Contact Enricher

**Files:**
- Modify: `scripts/dm_apollo.py`
- Modify: `scripts/dm_contact_page.py`
- Modify: `scripts/dm_github.py`
- Modify: `scripts/dm_huggingface_contacts.py`
- Modify: `scripts/dm_wellfound.py`
- Modify: `scripts/contact_enricher.py`
- Modify: related tests in `tests/test_dm_*.py` and `tests/test_contact_enricher.py`

- [ ] **Step 1: Update source outputs to prefer first/last/info**

For each DM source script, keep accepting old data internally, but output records in this shape:

```python
{
    "first_name": first_name,
    "last_name": last_name,
    "info": info,
    "email": email,
    "phone": phone,
    "linkedin_url": linkedin_url,
    "x_url": x_url,
    "facebook_url": facebook_url,
    "instagram_url": instagram_url,
    "other_channels": other_channels,
}
```

Specific mappings:

- GitHub profile URL -> `other_channels` item `{type:"github", url:"https://github.com/<login>"}`.
- HuggingFace profile URL -> `other_channels` item `{type:"huggingface", url:"https://huggingface.co/<username>"}`.
- personal website/blog -> `other_channels` item `{type:"personal_website", url:"..."}`.
- old `twitter_handle` -> `x_url`.
- old `title`/bio/company context -> `info`.

- [ ] **Step 2: Remove email status logic from contact enricher**

In `scripts/contact_enricher.py`:

- remove writes to `email_status`;
- remove `run_hunter_verify()` from the default `run()` flow;
- keep email guessing only if it directly fills `email`;
- remove tests that expect `valid`, `invalid`, `guessed`, or `email_status`.

Replacement behavior for guessed emails:

```python
updated.append({
    **contact,
    "email": guessed,
})
```

- [ ] **Step 3: Run DM/contact enricher tests**

Run:

```bash
python3 -m pytest tests/test_dm_apollo.py tests/test_dm_contact_page.py tests/test_dm_github.py tests/test_dm_huggingface_contacts.py tests/test_dm_wellfound.py tests/test_contact_enricher.py -q
```

Expected: pass after updating test expectations to the compact contact schema.

## Task 8: Update Agent Prompt For DM Enrichment

**Files:**
- Modify: `agents/prompts/dm_enrich_task.md`

- [ ] **Step 1: Replace contact payload example**

Replace the contact payload in `agents/prompts/dm_enrich_task.md` with:

```json
{
  "company_id": "00000000-0000-0000-0000-000000000001",
  "first_name": "Alice",
  "last_name": "Chen",
  "info": "Head of ML; likely owns dataset/vendor decisions.",
  "email": "alice@acme.ai",
  "phone": "+1-555-0100",
  "linkedin_url": "https://www.linkedin.com/in/alicechen",
  "x_url": "https://x.com/alicechen",
  "facebook_url": null,
  "instagram_url": null,
  "other_channels": [
    {"type": "github", "url": "https://github.com/alicechen"},
    {"type": "personal_website", "url": "https://alicechen.dev"}
  ]
}
```

Add this rule:

```markdown
Do not put `email`, `phone`, `linkedin_url`, `x_url`, `facebook_url`, or
`instagram_url` into `other_channels`. These are primary channels and must live
only in their dedicated fields.
```

- [ ] **Step 2: Add prompt test**

In `tests/test_pipeline_prompts.py`, add:

```python
def test_dm_enrich_prompt_uses_compact_contact_schema():
    p = _read("dm_enrich_task.md")
    for field in ("first_name", "last_name", "info", "phone", "x_url", "other_channels"):
        assert field in p
    for removed in ("full_name", "email_status", "confidence", "contact_type", "source_vector"):
        assert removed not in p
```

- [ ] **Step 3: Run prompt tests**

Run:

```bash
python3 -m pytest tests/test_pipeline_prompts.py -q
```

Expected: pass.

## Task 9: Update Audit Documentation

**Files:**
- Modify: `docs/DB-FIELD-AUDIT-2026-06-18.md`

- [ ] **Step 1: Replace contacts section**

Update the `contacts` table catalog and schema section so it lists only:

```text
id
company_id
first_name
last_name
info
email
phone
linkedin_url
x_url
facebook_url
instagram_url
other_channels
notion_page_id
notion_synced_at
created_at
updated_at
```

Add the channel normalization rule:

```markdown
Primary channels (`email`, `phone`, `linkedin_url`, `x_url`, `facebook_url`,
`instagram_url`) are never duplicated in `other_channels`. `other_channels`
stores secondary paths such as GitHub, HuggingFace, personal website, Calendly,
Telegram, Discord, YouTube, Medium, Substack, Google Scholar, Crunchbase,
Wellfound, or `other`.
```

- [ ] **Step 2: Run documentation reference scan**

Run:

```bash
rg -n "full_name|email_status|confidence|title_normalized|dm_priority|twitter_handle|github_username|hf_username|personal_website|contact_type|source_vector|source_url|company_domain" docs/DB-FIELD-AUDIT-2026-06-18.md agents/prompts/dm_enrich_task.md config/notion_mapping.yaml sql/schema.sql
```

Expected: no matches except explanatory text that explicitly names removed fields.

## Task 10: Full Verification

**Files:**
- No edits expected

- [ ] **Step 1: Run focused tests**

Run:

```bash
python3 -m pytest tests/test_migrations.py tests/test_contacts_store.py tests/test_notion_sync.py tests/test_models_cleanup.py tests/test_pipeline_prompts.py -q
```

Expected: pass.

- [ ] **Step 2: Run contact-related source tests**

Run:

```bash
python3 -m pytest tests/test_dm_apollo.py tests/test_dm_contact_page.py tests/test_dm_github.py tests/test_dm_huggingface_contacts.py tests/test_dm_wellfound.py tests/test_contact_enricher.py -q
```

Expected: pass.

- [ ] **Step 3: Run full suite**

Run:

```bash
python3 -m pytest -q
```

Expected: full suite passes. If external-service tests fail because they require network/API credentials, capture exact failing tests and errors.

- [ ] **Step 4: Inspect diff**

Run:

```bash
git status --short
git diff --stat
```

Expected: only contacts schema/model/store/source/prompt/test/doc changes plus any pre-existing plan files.

## Task 11: Commit

**Files:**
- All files changed by Tasks 1-9

- [ ] **Step 1: Stage intended files**

Run:

```bash
git add sql/schema.sql \
  scripts/contacts_store.py scripts/models.py scripts/notion_sync.py \
  scripts/dm_apollo.py scripts/dm_contact_page.py scripts/dm_github.py \
  scripts/dm_huggingface_contacts.py scripts/dm_wellfound.py scripts/contact_enricher.py \
  config/notion_mapping.yaml agents/prompts/dm_enrich_task.md \
  tests/test_migrations.py tests/test_contacts_store.py tests/test_notion_sync.py \
  tests/test_models_cleanup.py tests/test_contact_enricher.py tests/test_pipeline_prompts.py \
  docs/DB-FIELD-AUDIT-2026-06-18.md
```

- [ ] **Step 2: Review staged diff**

Run:

```bash
git diff --cached --stat
git diff --cached --name-status
```

Expected: no unrelated files staged.

- [ ] **Step 3: Commit**

Run:

```bash
git commit -m "refactor: simplify contacts schema"
```

Expected: commit succeeds.

## Self-Review

- Spec coverage: covers removing `confidence` and `email_status`, replacing `full_name` with `first_name`/`last_name`, keeping `phone`, renaming role context to `info`, adding primary channel fields with uniform `_url` naming, and defining `other_channels`.
- Placeholder scan: no TODO/TBD placeholders are present.
- Type consistency: SQL, Python store, dataclass, Notion mapping, and tests all use `first_name`, `last_name`, `info`, `x_url`, and `other_channels`.
- Structural risk noted: `last_name` is stored as empty string instead of `NULL` so the Supabase upsert conflict target can work reliably.
