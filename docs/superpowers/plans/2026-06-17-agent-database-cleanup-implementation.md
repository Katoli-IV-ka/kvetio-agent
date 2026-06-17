# Agent Database Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved agent database cleanup design without breaking the runtime agent, Telegram `/run`, or Notion contact sync.

**Architecture:** Make code and prompts compatible with the new model first, then drop obsolete schema objects last. `signals` becomes the source for evidence/latest-signal display, `contacts.company_id` becomes the canonical company relation, Telegram keeps only the stateless `/run` wizard, and Notion contact relation is resolved through `company_id -> companies.id -> companies.notion_page_id`.

**Tech Stack:** Python 3.11, pytest, ruff, Supabase Python client, Postgres SQL, Notion API, FastAPI Telegram webhook, Markdown prompt files.

---

## Scope Check

This plan covers several subsystems because the cleanup is schema-driven and cross-cutting. Execute it in the order below. Do not run destructive SQL against live Supabase until all code, prompt, and test tasks pass locally.

Authoritative design spec:

```text
docs/superpowers/specs/2026-06-17-agent-database-cleanup-design.md
```

Existing audit references:

```text
docs/DB-FIELD-AUDIT-2026-06-17.md
docs/DB-RUNTIME-USAGE-AUDIT-2026-06-17.md
```

## File Map

### Domain Models And Storage

- Modify: `scripts/models.py`
  - Remove scoring dataclasses and score-related fields from `Company`.
  - Update status literals to the approved status model.
  - Add `company_id` to `ContactRecord`.
  - Update `ContactType` to include `Related Person`.
  - Remove contact outreach/result types.
- Modify: `scripts/supabase_store.py`
  - Stop writing score fields, `latest_signal`, and `ai_direction`.
  - Replace score-based hot lead queries with status/signal based queries.
  - Keep `get_signals_for_company()`.
  - Add a small helper for latest-signal display rows.
- Modify: `scripts/contacts_store.py`
  - Resolve domain input to `companies.id`.
  - Write `contacts.company_id`.
  - Keep `contacts.company_domain` as transitional denormalized data.
  - Remove `contact_companies` helpers.
- Modify: `scripts/contact_enricher.py`
  - Continue accepting domain input, but rely on `contacts_store.upsert_contact()` to resolve `company_id`.

### Notion

- Modify: `config/notion_mapping.yaml`
  - Remove `Latest Signal`, company outreach reverse fields, and contact result reverse field.
  - Add `title` for contacts.
  - Keep computed relation property for contacts.
- Modify: `scripts/notion_sync.py`
  - Build contact relation from `contacts.company_id`.
  - Import new Notion contacts with exactly one company relation.
  - Update existing contacts through `contacts.notion_page_id`.
  - Stop reading `contact_companies`.

### Telegram Bot

- Modify: `bot/gateway.py`
  - Remove `PresetsStore` dependency, `/presets`, and `/quickrun`.
  - Keep `/run` callback wizard.
  - Update `/start`, `/help`, and `/settings` text.
- Delete: `bot/presets.py`
- Delete: `bot/preset_args.py`

### Prompts And Docs

- Modify: `agents/prompts/*.md`
  - Remove scoring stage, `source_page_url`, `companies.sources`, `companies.latest_signal`, and `reject_reason`.
  - Document/use `signals.signal_type` prefixes.
  - Move relevance output to `status = relevant | not_relevant | manual_review`.
- Modify: `docs/AGENT-ECOSYSTEM.md`
  - Align with the approved design.
- Modify: `README.md`
  - Remove presets/scoring references.

### SQL

- Modify: `sql/001_init.sql`
  - Align bootstrap schema with the new clean model.
- Add: `sql/017_agent_database_cleanup.sql`
  - Add `contacts.company_id`.
  - Add FK to `companies(id)`.
  - Migrate legacy statuses.
  - Drop obsolete fields/tables after code compatibility is in place.
- Modify: old SQL comments/tests that claim `bot_presets` and `contact_companies` are retained.

### Tests

- Modify: `tests/test_migrations.py`
- Modify: `tests/test_contacts_store.py`
- Modify: `tests/test_notion_sync.py`
- Modify: `tests/test_dedup.py`
- Modify: `tests/test_telegram_routines.py`
- Delete or rewrite: `tests/test_scoring.py`
- Delete: `tests/test_bot_preset_args.py`
- Modify prompt tests in `tests/test_pipeline_prompts.py` and related prompt coverage tests.

---

### Task 1: Lock The New Status And Model Contract

**Files:**
- Modify: `tests/test_status.py`
- Modify: `tests/test_models.py` if it exists; otherwise create `tests/test_models_cleanup.py`
- Modify: `scripts/models.py`

- [ ] **Step 1: Add the failing status/model tests**

Create `tests/test_models_cleanup.py` with:

```python
from __future__ import annotations

from models import ALL_STATUSES, ContactRecord


def test_all_statuses_match_cleanup_design() -> None:
    assert ALL_STATUSES == (
        "discovered",
        "relevant",
        "not_relevant",
        "manual_review",
        "sources_gathered",
        "analyzed",
        "dossier_ready",
    )


def test_contact_record_supports_company_id_and_related_person() -> None:
    contact = ContactRecord(
        company_id="00000000-0000-0000-0000-000000000001",
        company_domain="acme.ai",
        full_name="Jane Advisor",
        contact_type="Related Person",
        title="Advisor",
    )

    assert contact.company_id == "00000000-0000-0000-0000-000000000001"
    assert contact.company_domain == "acme.ai"
    assert contact.contact_type == "Related Person"
    assert contact.title == "Advisor"
```

- [ ] **Step 2: Run the new tests and confirm they fail**

Run:

```bash
pytest tests/test_models_cleanup.py -q
```

Expected: fail because `ALL_STATUSES` still contains legacy values and `ContactRecord` does not accept `company_id` or `Related Person`.

- [ ] **Step 3: Update status literals in `scripts/models.py`**

Replace the current `Status` and `ALL_STATUSES` block with:

```python
Status = Literal[
    "discovered",
    "relevant",
    "not_relevant",
    "manual_review",
    "sources_gathered",
    "analyzed",
    "dossier_ready",
]

# Canonical cleanup status model:
# discovered -> relevant/not_relevant/manual_review ->
# sources_gathered -> analyzed -> dossier_ready.
ALL_STATUSES: tuple[str, ...] = (
    "discovered",
    "relevant",
    "not_relevant",
    "manual_review",
    "sources_gathered",
    "analyzed",
    "dossier_ready",
)
```

- [ ] **Step 4: Remove scoring model types from `scripts/models.py`**

Delete these definitions from `scripts/models.py`:

```python
Bucket = Literal["not_relevant", "manual_review", "qualified"]
ScoringSignal
ScoreBreakdown
```

Then update `Company` to remove score fields:

```python
@dataclass
class Company:
    """Company aggregate stored in Supabase."""

    normalized_domain: str
    name: str
    website: str
    linkedin_url: str | None = None
    industries: list[str] = field(default_factory=list)
    funding_stage: str | None = None
    last_funding_date: date | None = None
    evidences: list[Evidence] = field(default_factory=list)
    notion_page_id: str | None = None
    last_verified: date | None = None
    status: Status = "discovered"
    icp_segment: str | None = None
```

- [ ] **Step 5: Update contact types in `scripts/models.py`**

Replace contact-related literals with:

```python
ContactSource = Literal[
    "github",
    "huggingface",
    "team_page",
    "apollo",
    "wellfound",
    "arxiv",
    "contact_page",
]
EmailStatus = Literal["verified", "guessed", "bounced", "unknown", "scraped"]
ContactType = Literal["Person", "Company", "Related Person", "Other"]
```

Update `ContactRecord` identity fields to:

```python
@dataclass
class ContactRecord:
    """Contact path for one company."""

    company_id: str
    company_domain: str
    full_name: str
```

Delete these fields from `ContactRecord`:

```python
contact_result: ContactResult | None = None
company_domains: list[str] = field(default_factory=list)
company_page_ids: list[str] = field(default_factory=list)
```

- [ ] **Step 6: Run the model tests**

Run:

```bash
pytest tests/test_models_cleanup.py tests/test_status.py -q
```

Expected: pass after updating any old status test expectations to the new `ALL_STATUSES` tuple.

- [ ] **Step 7: Commit**

```bash
git add scripts/models.py tests/test_models_cleanup.py tests/test_status.py
git commit -m "refactor(models): align statuses and contact model with cleanup design"
```

---

### Task 2: Remove Score Writes And Score-Based Store Queries

**Files:**
- Modify: `tests/test_dedup.py`
- Modify: `tests/test_telegram_routines.py`
- Modify: `scripts/supabase_store.py`
- Modify: `scripts/telegram_routines.py`
- Delete: `tests/test_scoring.py`
- Delete: `scripts/score.py`
- Delete: `config/scoring.yaml`

- [ ] **Step 1: Rewrite hot lead store test without score**

In `tests/test_dedup.py`, replace `test_list_hot_leads_queries_hot_enriched_companies` with:

```python
def test_list_hot_leads_queries_relevant_companies_without_score():
    """Hot leads are now relevant companies with recent signal context."""
    from supabase_store import SupabaseStore

    store = SupabaseStore.__new__(SupabaseStore)
    mock_client = MagicMock()
    query = MagicMock()
    response = MagicMock()
    response.data = [{"name": "Acme", "domain": "acme.ai", "status": "relevant"}]

    store._client = mock_client
    mock_client.table.return_value.select.return_value = query
    query.in_.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.return_value = response

    result = store.list_hot_leads(limit=3)

    assert result == response.data
    mock_client.table.assert_called_with("companies")
    query.in_.assert_called_with("status", ["relevant", "sources_gathered", "analyzed", "dossier_ready"])
    query.order.assert_called_with("updated_at", desc=True)
    query.limit.assert_called_with(3)
```

- [ ] **Step 2: Rewrite stale queue test status expectations**

In `tests/test_dedup.py`, update the final assertion in `test_list_stale_review_queue_queries_unverified_or_old_companies` to:

```python
    query.in_.assert_called_with(
        "status",
        ["discovered", "manual_review", "relevant"],
    )
```

- [ ] **Step 3: Run store tests and confirm failures**

Run:

```bash
pytest tests/test_dedup.py -q
```

Expected: fail because `SupabaseStore` still selects `score`, filters `score_bucket`, and uses old statuses.

- [ ] **Step 4: Remove score writes from `upsert_company()`**

In `scripts/supabase_store.py`, replace the `row` construction in `upsert_company()` with:

```python
        row = {
            "domain": company.normalized_domain,
            "name": company.name,
            "website": company.website,
            "linkedin_url": company.linkedin_url,
            "status": company.status,
            "icp_segment": company.icp_segment,
            "funding_stage": company.funding_stage,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if company.last_verified:
            row["last_verified"] = company.last_verified.isoformat()
        if company.last_funding_date:
            row["funding_date"] = company.last_funding_date.isoformat()
```

Delete this block:

```python
        if company.score:
            row["score"] = company.score.total
            row["score_bucket"] = _map_bucket(company.score.bucket)
            row["score_version"] = company.score.version
```

- [ ] **Step 5: Rewrite `list_hot_leads()`**

Replace `list_hot_leads()` in `scripts/supabase_store.py` with:

```python
    def list_hot_leads(self, limit: int = 5) -> list[dict]:
        """Relevant companies for Telegram routines, newest updated first."""
        res = (
            self._client.table("companies")
            .select("name, domain, status, icp_segment, notion_page_id, updated_at")
            .in_("status", ["relevant", "sources_gathered", "analyzed", "dossier_ready"])
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
```

- [ ] **Step 6: Rewrite `list_stale_review_queue()` statuses and select list**

In `scripts/supabase_store.py`, replace `review_statuses` and the `.select(...)` call with:

```python
        review_statuses = ["discovered", "manual_review", "relevant"]
        res = (
            self._client.table("companies")
            .select("name, domain, status, icp_segment, last_verified, updated_at")
            .in_("status", review_statuses)
            .or_(f"last_verified.is.null,last_verified.lt.{cutoff.isoformat()}")
            .order("last_verified", desc=False)
            .limit(limit)
            .execute()
        )
```

Delete `_map_bucket()` from `scripts/supabase_store.py`.

- [ ] **Step 7: Rewrite Telegram routine tests**

In `tests/test_telegram_routines.py`, replace score-bearing fixtures with rows like:

```python
hot_rows = [
    {
        "name": "Acme",
        "domain": "acme.ai",
        "status": "relevant",
        "icp_segment": "medical-imaging",
    }
]
stale_rows = [
    {
        "name": "Old Co",
        "domain": "old.ai",
        "status": "manual_review",
        "last_verified": None,
    }
]
```

Update assertions so hot/stale messages do not require `Score:`. Use:

```python
assert "Score:" not in result.message
assert "relevant" in result.message
```

- [ ] **Step 8: Remove score text from `scripts/telegram_routines.py`**

In `_hot_leads()`, remove:

```python
        score = lead.get("score")
        latest_signal = lead.get("latest_signal") or ""
        lines.append(f"Score: <b>{_format_score(score)}</b> | Segment: {_escape(segment)}")
        if latest_signal:
            lines.append(f"Signal: {_escape(latest_signal)}")
```

Replace it with:

```python
        status = lead.get("status") or "unknown"
        lines.append(f"Status: {_escape(status)} | Segment: {_escape(segment)}")
```

In `_stale_review()`, remove score formatting and replace the second line with:

```python
        lines.append(f"Status: {status} | Verified: {verified}")
```

Delete `_format_score()`.

- [ ] **Step 9: Delete scoring files and tests**

Remove:

```bash
rm scripts/score.py
rm config/scoring.yaml
rm tests/test_scoring.py
```

- [ ] **Step 10: Run focused tests**

Run:

```bash
pytest tests/test_dedup.py tests/test_telegram_routines.py tests/test_models_cleanup.py -q
```

Expected: pass.

- [ ] **Step 11: Commit**

```bash
git add scripts/supabase_store.py scripts/telegram_routines.py scripts/models.py tests/test_dedup.py tests/test_telegram_routines.py tests/test_models_cleanup.py
git rm scripts/score.py config/scoring.yaml tests/test_scoring.py
git commit -m "refactor: remove score runtime model"
```

---

### Task 3: Add Contacts `company_id` Compatibility Layer

**Files:**
- Modify: `tests/test_contacts_store.py`
- Modify: `scripts/contacts_store.py`
- Modify: `scripts/contact_enricher.py` only if tests expose direct `company_domain` assumptions.

- [ ] **Step 1: Add failing contacts store tests**

Append to `tests/test_contacts_store.py`:

```python
def test_resolve_company_ref_by_domain(mock_store):
    from contacts_store import resolve_company_ref

    mock_store._client.table.return_value.execute.return_value = MagicMock(
        data=[{"id": "company-uuid", "domain": "acme.ai"}]
    )

    result = resolve_company_ref(mock_store, domain="acme.ai")

    assert result == {"id": "company-uuid", "domain": "acme.ai"}
    mock_store._client.table.assert_called_with("companies")


def test_upsert_contact_writes_company_id_and_legacy_domain(mock_store):
    from contacts_store import upsert_contact

    mock_store._client.table.return_value.execute.return_value = MagicMock(
        data=[{"id": "contact-uuid"}]
    )

    upsert_contact(
        mock_store,
        {
            "company_id": "company-uuid",
            "company_domain": "acme.ai",
            "full_name": "Jane Doe",
            "source_vector": "apollo",
        },
    )

    row = mock_store._client.table.return_value.upsert.call_args[0][0]
    assert row["company_id"] == "company-uuid"
    assert row["company_domain"] == "acme.ai"
    assert "contact_result" not in row
    assert "outreach_status" not in row
    assert "outreach_note" not in row
```

- [ ] **Step 2: Rewrite old `contact_companies` tests to assert deletion**

Delete imports of `get_company_domains_for_contact` and `link_contact_to_companies`.

Delete:

```python
def test_link_contact_to_companies(mock_store):
    ...

def test_get_company_domains_for_contact(mock_store):
    ...
```

Add:

```python
def test_contacts_store_has_no_contact_companies_helpers():
    import contacts_store

    assert not hasattr(contacts_store, "link_contact_to_companies")
    assert not hasattr(contacts_store, "get_company_domains_for_contact")
```

- [ ] **Step 3: Run contacts tests and confirm failures**

Run:

```bash
pytest tests/test_contacts_store.py -q
```

Expected: fail because `resolve_company_ref()` does not exist and `upsert_contact()` does not write `company_id`.

- [ ] **Step 4: Add `resolve_company_ref()` to `scripts/contacts_store.py`**

Insert above `upsert_contact()`:

```python
def resolve_company_ref(
    store: SupabaseStore,
    *,
    domain: str | None = None,
    company_id: str | None = None,
) -> dict:
    """Return company id/domain for contact writes."""
    if company_id:
        res = (
            store._client.table("companies")
            .select("id,domain")
            .eq("id", company_id)
            .limit(1)
            .execute()
        )
    elif domain:
        res = (
            store._client.table("companies")
            .select("id,domain")
            .eq("domain", domain)
            .limit(1)
            .execute()
        )
    else:
        raise ValueError("company_id or company_domain is required")

    if not res.data:
        ref = company_id or domain
        raise ValueError(f"company not found for contact: {ref}")
    return res.data[0]
```

- [ ] **Step 5: Rewrite `upsert_contact()` row construction**

In `scripts/contacts_store.py`, start `upsert_contact()` with:

```python
    company_ref = resolve_company_ref(
        store,
        domain=contact.get("company_domain"),
        company_id=contact.get("company_id"),
    )
```

Then replace the first row fields with:

```python
    row = {
        "company_id": company_ref["id"],
        "company_domain": company_ref["domain"],
        "full_name": contact["full_name"],
```

Delete these row fields:

```python
        "contact_result": contact.get("contact_result"),
```

Do not add `outreach_status` or `outreach_note`.

- [ ] **Step 6: Remove `contact_companies` helpers**

Delete these functions from `scripts/contacts_store.py`:

```python
link_contact_to_companies
get_company_domains_for_contact
```

In `main()`, delete:

```python
        if contact.get("company_domains"):
            link_contact_to_companies(store, contact_id, contact["company_domains"])
```

- [ ] **Step 7: Run contacts tests**

Run:

```bash
pytest tests/test_contacts_store.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add scripts/contacts_store.py tests/test_contacts_store.py
git commit -m "refactor(contacts): resolve contacts through company id"
```

---

### Task 4: Rewrite Notion Contact Relation And Reverse Import

**Files:**
- Modify: `tests/test_notion_sync.py`
- Modify: `config/notion_mapping.yaml`
- Modify: `scripts/notion_sync.py`

- [ ] **Step 1: Update Notion mapping tests to remove CRM fields**

In `tests/test_notion_sync.py`, update mapping assertions so company fields do not include:

```text
outreach_status
outreach_note
latest_signal
```

And contact fields do not include:

```text
contact_result
```

Add assertions:

```python
def test_contacts_mapping_has_company_relation_and_title():
    mapping = ns.load_mapping()
    fields = mapping["contacts"]["fields"]
    by_column = {field["db_column"]: field for field in fields}

    assert by_column["company_page_ids"]["notion_type"] == "relation"
    assert by_column["title"]["notion_property"] == "Title"
    assert "contact_result" not in by_column
```

- [ ] **Step 2: Replace relation enrichment test**

Replace `test_enrich_contact_rows_adds_company_page_ids()` with:

```python
def test_enrich_contact_rows_uses_company_id_relation():
    rows = [
        {"id": "c1", "full_name": "Alice", "company_id": "co1"},
        {"id": "c2", "full_name": "Bob", "company_id": "co2"},
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
```

- [ ] **Step 3: Add reverse import test for new Notion contact**

Add:

```python
def test_sync_reverse_imports_new_contact_with_single_company_relation():
    mapping = {
        "contacts": {
            "notion_database_id_env": "NOTION_CONTACTS_DB_ID",
            "db_table": "contacts",
            "db_key": "id",
            "fields": [
                {"db_column": "full_name", "notion_property": "Name", "notion_type": "title", "direction": "reverse"},
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
                "full_name": "Alice",
                "email": "alice@acme.ai",
                "company_id": "company-uuid",
                "company_domain": "acme.ai",
                "notion_page_id": "notion-contact-1",
            },
        )
    ]
```

- [ ] **Step 4: Run Notion tests and confirm failures**

Run:

```bash
pytest tests/test_notion_sync.py -q
```

Expected: fail because code still reads `contact_companies`, mapping still has removed fields, and `DbGateway` has no `insert()`.

- [ ] **Step 5: Update `config/notion_mapping.yaml`**

In `companies.fields`, remove:

```yaml
- { db_column: last_signal_date, notion_property: "Signal Date", notion_type: date, direction: forward }
- { db_column: latest_signal, notion_property: "Latest Signal", notion_type: rich_text, direction: forward }
- { db_column: outreach_status, notion_property: "Outreach", notion_type: select, direction: reverse }
- { db_column: outreach_note, notion_property: "Заметка", notion_type: rich_text, direction: reverse }
```

In `contacts.fields`, add:

```yaml
- { db_column: title, notion_property: "Title", notion_type: rich_text, direction: forward }
```

Remove:

```yaml
- { db_column: contact_result, notion_property: "Результаты связи", notion_type: select, direction: reverse }
```

- [ ] **Step 6: Update `enrich_contact_rows()`**

Replace `enrich_contact_rows()` in `scripts/notion_sync.py` with:

```python
def enrich_contact_rows(rows: list[dict], db) -> list[dict]:
    """Add Notion company relation page ids to contact rows via company_id."""
    companies = db.fetch("companies")

    page_id_by_company_id: dict[str, str] = {
        c["id"]: c["notion_page_id"]
        for c in companies
        if c.get("id") and c.get("notion_page_id")
    }

    enriched = []
    for row in rows:
        page_id = page_id_by_company_id.get(row.get("company_id"))
        enriched.append({**row, "company_page_ids": [page_id] if page_id else []})
    return enriched
```

- [ ] **Step 7: Add `DbGateway.insert()`**

In `scripts/notion_sync.py`, add to `DbGateway`:

```python
    def insert(self, table, fields):
        self._c.table(table).insert(fields).execute()
```

- [ ] **Step 8: Replace `sync_reverse()` with create/update support for contacts**

In `NotionSync.sync_reverse()`, keep existing behavior for non-contact entities, but add contact handling:

```python
    def sync_reverse(self, entity, dry_run=False) -> dict:
        if entity == "contacts":
            return self._sync_contacts_reverse(dry_run=dry_run)

        cfg = self._cfg(entity)
        fields = self._fields(entity, "reverse")
        if not fields:
            return {"entity": entity, "updated": 0, "errors": 0}
        index = self._page_index(entity)
        updated = errors = 0
        for page_id, row in index.items():
            try:
                props = self._read_page_props(page_id)
                changes = {}
                for f in fields:
                    val = from_notion_property(
                        f["notion_type"],
                        props.get(f["notion_property"]),
                    )
                    if val != row.get(f["db_column"]):
                        changes[f["db_column"]] = val
                if changes and not dry_run:
                    self.db.update(cfg["db_table"], cfg["db_key"], row[cfg["db_key"]], changes)
                if changes:
                    updated += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("reverse %s %s: %s", entity, page_id, exc)
                errors += 1
        return {"entity": entity, "updated": updated, "errors": errors}
```

Then add this method to `NotionSync`:

```python
    def _sync_contacts_reverse(self, dry_run=False) -> dict:
        cfg = self._cfg("contacts")
        db_id = self._db_id("contacts")
        pages = self.notion.query_database(db_id)
        existing_by_page_id = self._page_index("contacts")
        companies = self.db.fetch("companies")
        company_by_page_id = {
            row["notion_page_id"]: row
            for row in companies
            if row.get("notion_page_id")
        }

        reverse_fields = self._fields("contacts", "reverse")
        created = updated = errors = 0

        for page in pages:
            page_id = page["id"]
            props = page.get("properties", {})
            try:
                changes = {}
                company = None
                for field in reverse_fields:
                    value = from_notion_property(
                        field["notion_type"],
                        props.get(field["notion_property"]),
                    )
                    if field["db_column"] == "company_page_ids":
                        if len(value or []) != 1:
                            raise ValueError("contact must have exactly one company relation")
                        company = company_by_page_id.get(value[0])
                        if not company:
                            raise ValueError(f"company relation not found: {value[0]}")
                    else:
                        changes[field["db_column"]] = value

                if company:
                    changes["company_id"] = company["id"]
                    changes["company_domain"] = company["domain"]

                if page_id in existing_by_page_id:
                    row = existing_by_page_id[page_id]
                    diff = {
                        key: value
                        for key, value in changes.items()
                        if value != row.get(key)
                    }
                    if diff and not dry_run:
                        self.db.update(cfg["db_table"], cfg["db_key"], row[cfg["db_key"]], diff)
                    if diff:
                        updated += 1
                else:
                    insert_row = {**changes, "notion_page_id": page_id}
                    if not dry_run:
                        self.db.insert(cfg["db_table"], insert_row)
                    created += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("reverse contacts %s: %s", page_id, exc)
                errors += 1

        return {"entity": "contacts", "updated": updated, "created": created, "errors": errors}
```

- [ ] **Step 9: Run Notion tests**

Run:

```bash
pytest tests/test_notion_sync.py -q
```

Expected: pass.

- [ ] **Step 10: Commit**

```bash
git add scripts/notion_sync.py config/notion_mapping.yaml tests/test_notion_sync.py
git commit -m "refactor(notion): sync contact relation through company id"
```

---

### Task 5: Remove Telegram Presets And Quickrun

**Files:**
- Modify: `bot/gateway.py`
- Delete: `bot/presets.py`
- Delete: `bot/preset_args.py`
- Delete: `tests/test_bot_preset_args.py`
- Modify: bot tests that reference `/quickrun` or `/presets`.

- [ ] **Step 1: Add or update bot gateway tests for removed commands**

Create `tests/test_bot_gateway_cleanup.py` with:

```python
from __future__ import annotations

import pytest

from bot.gateway import _start_text, _help_text


def test_start_text_exposes_run_without_presets_or_quickrun() -> None:
    text = _start_text()
    assert "/run" in text
    assert "/presets" not in text
    assert "/quickrun" not in text


def test_help_text_exposes_run_without_presets_or_quickrun() -> None:
    text = _help_text()
    assert "/run" in text
    assert "/presets" not in text
    assert "/quickrun" not in text
```

- [ ] **Step 2: Run bot cleanup tests and confirm failures**

Run:

```bash
pytest tests/test_bot_gateway_cleanup.py -q
```

Expected: fail because help/start still mention `/quickrun` and `/presets`.

- [ ] **Step 3: Remove preset imports and dependencies in `bot/gateway.py`**

Delete:

```python
from bot.preset_args import parse_preset_save_args
from bot.presets import PresetsStore
```

Replace `_deps()` with:

```python
def _deps():
    client = _make_supabase()
    return client
```

Replace:

```python
    presets, client = _deps()
```

with:

```python
    client = _deps()
```

Update `_handle_message()` signature to:

```python
async def _handle_message(
    msg: dict[str, Any],
    client: Any,
    tg: "TelegramSender",
) -> None:
```

- [ ] **Step 4: Delete `/presets` and `/quickrun` command branches**

Remove these branches from `_handle_message()`:

```python
    elif command == "/presets":
        ...

    elif command == "/quickrun":
        ...
```

Delete `_handle_presets_command()` entirely.

- [ ] **Step 5: Update `/settings`, `_start_text()`, and `_help_text()`**

Set `/settings` response to:

```python
        await tg.send(
            chat_id,
            "⚙️ Параметры запуска выбираются через /run.",
        )
```

In `_start_text()`, replace the command section with:

```python
            "/run — мастер запуска с выбором параметров",
            "/help — все команды",
```

In `_help_text()`, keep the launch section as:

```python
            "<b>Запуск агента</b>",
            "/run — мастер запуска с выбором сегментов, лимита, stages и флагов",
```

Remove the whole `<b>Пресеты</b>` block.

- [ ] **Step 6: Delete preset files and tests**

Run:

```bash
git rm bot/presets.py bot/preset_args.py tests/test_bot_preset_args.py
```

- [ ] **Step 7: Run bot tests**

Run:

```bash
pytest tests/test_bot_gateway_cleanup.py tests/test_bot_dialog.py tests/test_routine_fire.py -q
```

Expected: pass.

- [ ] **Step 8: Commit**

```bash
git add bot/gateway.py tests/test_bot_gateway_cleanup.py
git commit -m "refactor(bot): remove presets and quickrun"
```

---

### Task 6: Update Prompts To The Clean Data Model

**Files:**
- Modify: `agents/prompts/pipeline_main_task.md`
- Modify: `agents/prompts/discovery_task.md`
- Modify: `agents/prompts/discover_verify_task.md`
- Modify: `agents/prompts/relevance_task.md`
- Modify: `agents/prompts/enrichment_task.md`
- Modify: `agents/prompts/analysis_task.md`
- Modify: `agents/prompts/conclusions_task.md`
- Modify: `agents/prompts/dm_enrich_task.md`
- Modify: `agents/prompts/monitor_task.md`
- Delete: `agents/prompts/scoring_task.md`
- Modify: `tests/test_pipeline_prompts.py`

- [ ] **Step 1: Add prompt cleanup assertions**

In `tests/test_pipeline_prompts.py`, add:

```python
from pathlib import Path


PROMPT_DIR = Path(__file__).parent.parent / "agents" / "prompts"


def test_prompts_do_not_reference_removed_company_fields() -> None:
    removed_terms = [
        "source_page_url",
        "companies.sources",
        "latest_signal",
        "reject_reason",
        "score_bucket",
        "score_version",
        "ai_direction",
        "python scripts/score.py",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in PROMPT_DIR.glob("*.md"))

    for term in removed_terms:
        assert term not in text


def test_prompts_document_signal_type_prefixes() -> None:
    text = (PROMPT_DIR / "pipeline_main_task.md").read_text(encoding="utf-8")
    assert "primary_*" in text
    assert "verification_*" in text
    assert "monitor_*" in text
```

- [ ] **Step 2: Run prompt tests and confirm failures**

Run:

```bash
pytest tests/test_pipeline_prompts.py -q
```

Expected: fail on old field and scoring references.

- [ ] **Step 3: Remove scoring prompt**

Run:

```bash
git rm agents/prompts/scoring_task.md
```

- [ ] **Step 4: Update `agents/prompts/pipeline_main_task.md`**

Remove the scoring stage instructions and replace any stage list with:

```text
Pipeline stages:
1. Discovery writes candidates and primary signals.
2. Relevance sets companies.status to relevant, not_relevant, or manual_review.
3. Source expansion gathers supporting links and sets sources_gathered.
4. Analysis writes structured notes and sets analyzed.
5. Conclusions writes final dossier and sets dossier_ready.
```

Add this signal convention block:

```text
Signal type convention:
- primary_* = signal that first brought the company into the database.
- verification_* = supporting signal found during initial validation.
- monitor_* = new signal for an already known company.

Do not write source_page_url, companies.sources, companies.latest_signal, reject_reason, score,
score_bucket, score_version, or ai_direction.
```

- [ ] **Step 5: Update relevance prompts**

In `agents/prompts/relevance_task.md` and `agents/prompts/discover_verify_task.md`, replace not-relevant update examples with:

```sql
UPDATE companies
SET status = 'not_relevant',
    last_verified = CURRENT_DATE,
    updated_at = NOW()
WHERE domain = 'acme.ai';
```

Replace relevant update examples with:

```sql
UPDATE companies
SET status = 'relevant',
    description = 'Builds AI tooling for medical imaging workflows.',
    linkedin_url = 'https://www.linkedin.com/company/acme-ai',
    team_size = '11-50',
    funding_stage = 'seed',
    funding_date = '2026-01-15',
    website_snippet = 'AI platform for radiology workflow automation.',
    site_note = 'Relevant because the company builds AI workflow software for medical imaging.',
    last_verified = CURRENT_DATE,
    updated_at = NOW()
WHERE domain = 'acme.ai';
```

- [ ] **Step 6: Update analysis/conclusion prompts**

In `agents/prompts/analysis_task.md`, replace:

```sql
ORDER BY score DESC NULLS LAST
```

with:

```sql
ORDER BY updated_at DESC
```

In `agents/prompts/conclusions_task.md`, remove selected score columns and use:

```sql
SELECT domain, name, website, icp_segment, description, funding_stage, team_size
FROM companies
WHERE status = 'analyzed'
ORDER BY updated_at DESC
LIMIT 10;
```

- [ ] **Step 7: Update DM prompt**

In `agents/prompts/dm_enrich_task.md`, replace company selection with:

```sql
SELECT id, domain, name, website, icp_segment
FROM companies
WHERE status IN ('relevant', 'sources_gathered', 'analyzed', 'dossier_ready')
ORDER BY updated_at DESC
LIMIT 10;
```

In contact JSON examples, include both fields:

```json
{
  "company_id": "00000000-0000-0000-0000-000000000001",
  "company_domain": "acme.ai",
  "full_name": "Alice Chen",
  "contact_type": "Person",
  "title": "Head of ML",
  "email": "alice@acme.ai",
  "source_vector": "apollo",
  "source_url": "https://app.apollo.io/#/people/alice-chen"
}
```

- [ ] **Step 8: Run prompt tests**

Run:

```bash
pytest tests/test_pipeline_prompts.py -q
```

Expected: pass.

- [ ] **Step 9: Commit**

```bash
git add agents/prompts tests/test_pipeline_prompts.py
git commit -m "docs(prompts): align agent prompts with cleanup model"
```

---

### Task 7: Add SQL Cleanup Migration Contract

**Files:**
- Modify: `tests/test_migrations.py`
- Add: `sql/017_agent_database_cleanup.sql`
- Modify: `sql/001_init.sql`
- Modify: `sql/006_contacts.sql`
- Modify: `sql/012_bot.sql`
- Modify: `sql/013_contacts_v2.sql`
- Delete or neutralize: `sql/016_bot_default_limit_5.sql`

- [ ] **Step 1: Add failing migration contract test**

Append to `tests/test_migrations.py`:

```python
def test_migration_017_agent_database_cleanup():
    sql = _read("017_agent_database_cleanup.sql")
    assert "ADD COLUMN IF NOT EXISTS company_id UUID" in sql
    assert "REFERENCES companies(id)" in sql
    assert "DROP TABLE IF EXISTS contact_companies" in sql
    assert "DROP TABLE IF EXISTS bot_presets" in sql
    assert "DROP COLUMN IF EXISTS score" in sql
    assert "DROP COLUMN IF EXISTS score_bucket" in sql
    assert "DROP COLUMN IF EXISTS score_version" in sql
    assert "DROP COLUMN IF EXISTS ai_direction" in sql
    assert "DROP COLUMN IF EXISTS sources" in sql
    assert "DROP COLUMN IF EXISTS latest_signal" in sql
    assert "DROP COLUMN IF EXISTS reject_reason" in sql
    assert "DROP COLUMN IF EXISTS outreach_status" in sql
    assert "DROP COLUMN IF EXISTS outreach_note" in sql
    assert "DROP COLUMN IF EXISTS contact_result" in sql
```

- [ ] **Step 2: Run migration test and confirm failure**

Run:

```bash
pytest tests/test_migrations.py::test_migration_017_agent_database_cleanup -q
```

Expected: fail because `017_agent_database_cleanup.sql` does not exist.

- [ ] **Step 3: Add migration file**

Create `sql/017_agent_database_cleanup.sql` with:

```sql
-- Migration 017: agent database cleanup.
--
-- Implements docs/superpowers/specs/2026-06-17-agent-database-cleanup-design.md.
-- Apply only after runtime code no longer reads the dropped objects.

ALTER TABLE contacts
  ADD COLUMN IF NOT EXISTS company_id UUID;

UPDATE contacts AS c
SET company_id = co.id
FROM companies AS co
WHERE c.company_id IS NULL
  AND c.company_domain = co.domain;

ALTER TABLE contacts
  ADD CONSTRAINT contacts_company_id_fk
  FOREIGN KEY (company_id) REFERENCES companies(id)
  NOT VALID;

ALTER TABLE contacts
  VALIDATE CONSTRAINT contacts_company_id_fk;

ALTER TABLE contacts
  ADD CONSTRAINT contacts_company_id_not_null
  CHECK (company_id IS NOT NULL)
  NOT VALID;

ALTER TABLE contacts
  VALIDATE CONSTRAINT contacts_company_id_not_null;

ALTER TABLE contacts
  ALTER COLUMN company_id SET NOT NULL;

ALTER TABLE contacts
  DROP CONSTRAINT contacts_company_id_not_null;

CREATE INDEX IF NOT EXISTS idx_contacts_company_id
  ON contacts (company_id);

UPDATE companies
SET status = CASE status
  WHEN 'qualified' THEN 'relevant'
  WHEN 'pending_enrich' THEN 'relevant'
  WHEN 'enriched' THEN 'relevant'
  WHEN 'triaged_out' THEN 'not_relevant'
  ELSE status
END
WHERE status IN ('qualified', 'pending_enrich', 'enriched', 'triaged_out');

DROP TABLE IF EXISTS contact_companies;
DROP TABLE IF EXISTS bot_presets;

ALTER TABLE companies
  DROP COLUMN IF EXISTS score,
  DROP COLUMN IF EXISTS score_bucket,
  DROP COLUMN IF EXISTS score_version,
  DROP COLUMN IF EXISTS ai_direction,
  DROP COLUMN IF EXISTS sources,
  DROP COLUMN IF EXISTS latest_signal,
  DROP COLUMN IF EXISTS reject_reason,
  DROP COLUMN IF EXISTS outreach_status,
  DROP COLUMN IF EXISTS outreach_note;

ALTER TABLE contacts
  DROP COLUMN IF EXISTS outreach_status,
  DROP COLUMN IF EXISTS outreach_note,
  DROP COLUMN IF EXISTS contact_result;
```

- [ ] **Step 4: Update bootstrap schema files**

In `sql/001_init.sql`, remove company columns:

```sql
latest_signal
score
score_bucket
score_version
```

In `sql/006_contacts.sql`, add:

```sql
company_id UUID NOT NULL REFERENCES companies(id),
```

Keep:

```sql
company_domain TEXT NOT NULL,
```

Remove contact outreach columns from `sql/006_contacts.sql`.

In `sql/013_contacts_v2.sql`, remove `contact_result` and `contact_companies` creation.

In `sql/012_bot.sql`, remove `bot_presets` creation.

In `sql/016_bot_default_limit_5.sql`, replace its body with:

```sql
-- Migration 016 was superseded by migration 017.
-- bot_presets is removed from the runtime schema.
```

- [ ] **Step 5: Run migration tests**

Run:

```bash
pytest tests/test_migrations.py -q
```

Expected: pass after updating old migration assertions that required retaining `bot_presets` or creating `contact_companies`.

- [ ] **Step 6: Commit**

```bash
git add sql tests/test_migrations.py
git commit -m "chore(sql): add agent database cleanup migration"
```

---

### Task 8: Update Docs And Remove Stale References

**Files:**
- Modify: `README.md`
- Modify: `docs/AGENT-ECOSYSTEM.md`
- Modify: `docs/DB-FIELD-AUDIT-2026-06-17.md`
- Modify: `docs/DB-RUNTIME-USAGE-AUDIT-2026-06-17.md`

- [ ] **Step 1: Search for stale terms**

Run:

```bash
rg -n "bot_presets|/presets|/quickrun|score_bucket|score_version|ai_direction|latest_signal|reject_reason|contact_companies|contact_result|outreach_status|outreach_note|source_page_url" README.md docs agents bot scripts tests config sql
```

Expected: many matches before cleanup.

- [ ] **Step 2: Update `README.md`**

Apply these documentation changes:

```text
- Replace "/run, /quickrun" with "/run".
- Remove "presets.py · preset_args.py".
- Remove the command rows for /quickrun and /presets.
- Remove scoring from pipeline descriptions.
- Describe /run as the only Telegram launch entrypoint.
```

- [ ] **Step 3: Update `docs/AGENT-ECOSYSTEM.md`**

Apply these documentation changes:

```text
- Replace the old status path with:
  discovered -> relevant/not_relevant/manual_review -> sources_gathered -> analyzed -> dossier_ready.
- Remove scoring stage sections and scripts/score.py references.
- Remove bot_presets sections.
- Remove contact_companies as active architecture.
- Add contacts.company_id -> companies.id as canonical relation.
- Mark contacts.company_domain as transitional legacy compatibility only.
- Document signal_type primary_*, verification_*, monitor_*.
- State that Latest Signal is derived from signals.
```

- [ ] **Step 4: Update audit documents**

In both audit docs, add a short "Cleanup decision 2026-06-17" note:

```text
Cleanup decision 2026-06-17:
- Score fields are removed.
- companies.sources, latest_signal, reject_reason are removed.
- bot_presets and contact_companies are removed.
- contacts.company_id is canonical; contacts.company_domain remains transitional legacy data.
- Notion CRM reverse fields are removed from the agent database.
```

- [ ] **Step 5: Re-run stale term search**

Run:

```bash
rg -n "bot_presets|/presets|/quickrun|score_bucket|score_version|ai_direction|latest_signal|reject_reason|contact_companies|contact_result|outreach_status|outreach_note|source_page_url" README.md docs agents bot scripts tests config sql
```

Expected: remaining matches only in:

```text
docs/superpowers/specs/2026-06-17-agent-database-cleanup-design.md
docs/superpowers/plans/2026-06-17-agent-database-cleanup-implementation.md
sql/017_agent_database_cleanup.sql
audit docs cleanup decision notes
```

- [ ] **Step 6: Commit**

```bash
git add README.md docs
git commit -m "docs: update ecosystem docs for database cleanup"
```

---

### Task 9: Final Verification Before Live DB Changes

**Files:**
- No code files unless verification exposes failures.

- [ ] **Step 1: Run full local tests**

Run:

```bash
pytest -q
```

Expected: all tests pass.

- [ ] **Step 2: Run stale reference search across active code**

Run:

```bash
rg -n "score_bucket|score_version|ai_direction|latest_signal|reject_reason|source_page_url|contact_companies|bot_presets|contact_result|outreach_status|outreach_note" scripts bot agents config tests sql README.md docs/AGENT-ECOSYSTEM.md
```

Expected: no active runtime references. References inside migration files may remain.

- [ ] **Step 3: Run import smoke checks**

Run:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, "scripts")
import models
import supabase_store
import contacts_store
import notion_sync
from bot import gateway
print("imports ok")
PY
```

Expected:

```text
imports ok
```

- [ ] **Step 4: Run bot dialog tests**

Run:

```bash
pytest tests/test_bot_dialog.py tests/test_routine_fire.py tests/test_bot_gateway_cleanup.py -q
```

Expected: pass.

- [ ] **Step 5: Run Notion/contact focused tests**

Run:

```bash
pytest tests/test_contacts_store.py tests/test_notion_sync.py -q
```

Expected: pass.

- [ ] **Step 6: Route any verification fixes back to the owning task**

If verification exposes failures, do not create a generic catch-all commit. Return to the task that
owns the failing file, apply the smallest fix there, rerun that task's focused tests, and use that
task's commit command. If no files changed, continue to Task 10.


---

### Task 10: Live Supabase Verification And Migration

**Files:**
- No repo files changed by this task.

- [ ] **Step 1: Confirm environment has Supabase credentials**

Run:

```bash
python3 - <<'PY'
from pathlib import Path
env = Path(".env")
text = env.read_text() if env.exists() else ""
for key in ("SUPABASE_URL", "SUPABASE_KEY"):
    print(f"{key}={'present' if key + '=' in text else 'missing'}")
PY
```

Expected:

```text
SUPABASE_URL=present
SUPABASE_KEY=present
```

If credentials are missing, stop and ask the user to provide the correct local `.env` or run the SQL manually in Supabase SQL Editor.

- [ ] **Step 2: Run preflight live counts**

Run:

```bash
python3 - <<'PY'
import os, sys
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(".env")
client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
for table in ("companies", "signals", "contacts", "bot_presets", "contact_companies"):
    try:
        res = client.table(table).select("*", count="exact").limit(1).execute()
        print(table, res.count)
    except Exception as exc:
        print(table, "ERROR", exc)
PY
```

Expected before migration:

```text
companies <non-negative count>
signals <non-negative count>
contacts 0 or more
bot_presets 3 or ERROR if already removed
contact_companies 0 or more
```

- [ ] **Step 3: Review migration SQL before applying**

Run:

```bash
sed -n '1,220p' sql/017_agent_database_cleanup.sql
```

Expected: SQL matches Task 7 and does not drop `companies`, `signals`, `contacts`, `run_logs`, `source_links`, `analysis_notes`, or `dossiers`.

- [ ] **Step 4: Apply migration manually**

Because this is destructive, apply `sql/017_agent_database_cleanup.sql` in Supabase SQL Editor or through the project-approved migration runner. Do not run it against live DB until Task 9 is complete.

- [ ] **Step 5: Verify live schema after migration**

Run:

```bash
python3 - <<'PY'
import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv(".env")
client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])

checks = {
    "companies": "id,domain,name,status,icp_segment,notion_page_id",
    "contacts": "id,company_id,company_domain,full_name,contact_type,title,notion_page_id",
    "signals": "id,source,signal_type,normalized_domain,evidence_url,signal_date",
}
for table, columns in checks.items():
    res = client.table(table).select(columns).limit(1).execute()
    print(table, "ok", len(res.data or []))

for removed in ("bot_presets", "contact_companies"):
    try:
        client.table(removed).select("*").limit(1).execute()
        print(removed, "still_exists")
    except Exception:
        print(removed, "removed")
PY
```

Expected:

```text
companies ok <0 or 1>
contacts ok <0 or 1>
signals ok <0 or 1>
bot_presets removed
contact_companies removed
```

- [ ] **Step 6: Run post-migration smoke tests with live configuration**

Run:

```bash
python3 scripts/supabase_store.py --stats
python3 scripts/notion_sync.py --validate --dry-run
```

Expected:

```text
supabase_store.py --stats prints JSON stats
notion_sync.py --validate --dry-run prints {"valid": true}
```

---

## Execution Order

Execute tasks in this exact order:

```text
Task 1  Models and statuses
Task 2  Score runtime removal
Task 3  Contacts company_id compatibility
Task 4  Notion contact relation rewrite
Task 5  Telegram presets removal
Task 6  Prompt cleanup
Task 7  SQL cleanup migration
Task 8  Docs cleanup
Task 9  Final local verification
Task 10 Live Supabase migration
```

## Final Acceptance Checklist

- [ ] `pytest -q` passes.
- [ ] `rg` finds no active runtime references to removed fields/tables.
- [ ] Telegram `/run` flow tests pass without `bot_presets`.
- [ ] Notion contact relation tests use `company_id`.
- [ ] `contacts_store.upsert_contact()` writes `company_id`.
- [ ] Prompt tests reject score/source_page_url/latest_signal/reject_reason references.
- [ ] SQL migration drops obsolete fields and tables only after code compatibility is complete.
- [ ] Live Supabase smoke checks pass after applying migration.
