from scripts.research_notes_store import content_hash, ensure_category, upsert_note


class _Response:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, client, name):
        self.client = client
        self.name = name
        self._filters = {}
        self._pending_insert = None

    def select(self, *_args):
        return self

    def eq(self, column, value):
        self._filters[column] = value
        return self

    def insert(self, row):
        self._pending_insert = row
        return self

    def execute(self):
        if self._pending_insert is not None:
            row = dict(self._pending_insert)
            row.setdefault("id", f"id{len(self.client.data.get(self.name, [])) + 1}")
            self.client.data.setdefault(self.name, []).append(row)
            return _Response([row])

        rows = [
            row
            for row in self.client.data.get(self.name, [])
            if all(row.get(column) == value for column, value in self._filters.items())
        ]
        return _Response(rows)


class _FakeClient:
    def __init__(self):
        self.data = {}

    def table(self, name):
        return _FakeTable(self, name)


class _FakeStore:
    def __init__(self):
        self._client = _FakeClient()


def test_content_hash_stable_and_distinct():
    first = content_hash("Acme builds medical imaging models.")
    second = content_hash("Acme builds medical imaging models.")
    different = content_hash("Different content.")
    assert first == second
    assert first != different
    assert len(first) == 64


def test_upsert_note_is_idempotent():
    store = _FakeStore()
    company_id = "company-1"
    first = upsert_note(
        store,
        company_id=company_id,
        note_type="product",
        content="Acme builds models.",
        source_url="https://acme.ai",
    )
    second = upsert_note(
        store,
        company_id=company_id,
        note_type="product",
        content="Acme builds models.",
        source_url="https://acme.ai",
    )
    assert first == second
    assert len(store._client.data["research_notes"]) == 1


def test_upsert_note_rejects_invalid_note_type():
    store = _FakeStore()
    try:
        upsert_note(store, company_id="company-1", note_type="other", content="x")
    except ValueError as exc:
        assert "invalid note_type" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_ensure_category_inserts_when_missing():
    store = _FakeStore()
    store._client.data["category_options"] = [
        {"value": "data_provider", "label": "Data provider"}
    ]

    ensure_category(store, "data_provider")
    assert len(store._client.data["category_options"]) == 1

    ensure_category(store, "robotics_lab", label="Robotics lab")
    values = [row["value"] for row in store._client.data["category_options"]]
    assert "robotics_lab" in values
