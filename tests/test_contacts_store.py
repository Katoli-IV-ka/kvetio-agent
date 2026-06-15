"""contacts_store tests with a mocked Supabase client."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from contacts_store import list_contacts, mark_enriched, upsert_contact


@pytest.fixture
def mock_store():
    store = MagicMock()
    table_mock = MagicMock()
    store._client.table.return_value = table_mock
    table_mock.upsert.return_value = table_mock
    table_mock.update.return_value = table_mock
    table_mock.select.return_value = table_mock
    table_mock.eq.return_value = table_mock
    table_mock.order.return_value = table_mock
    table_mock.execute.return_value = MagicMock(data=[])
    return store


def test_upsert_contact_sets_required_fields(mock_store):
    contact = {
        "company_domain": "radai.com",
        "full_name": "Sarah Chen",
        "title": "Head of ML",
        "dm_priority": 1,
        "email": "sarah@radai.com",
        "email_status": "verified",
        "source_vector": "apollo",
    }
    upsert_contact(mock_store, contact)
    mock_store._client.table.assert_called_with("contacts")
    call_args = mock_store._client.table.return_value.upsert.call_args
    row = call_args[0][0]
    assert row["company_domain"] == "radai.com"
    assert row["full_name"] == "Sarah Chen"
    assert row["dm_priority"] == 1
    assert row["email_status"] == "verified"


def test_upsert_contact_defaults_priority_to_2(mock_store):
    contact = {"company_domain": "radai.com", "full_name": "Jane Doe"}
    upsert_contact(mock_store, contact)
    row = mock_store._client.table.return_value.upsert.call_args[0][0]
    assert row["dm_priority"] == 2


def test_mark_enriched_updates_dm_enriched_at(mock_store):
    mark_enriched(mock_store, "radai.com")
    mock_store._client.table.assert_called_with("companies")
    update_args = mock_store._client.table.return_value.update.call_args[0][0]
    assert "dm_enriched_at" in update_args


def test_list_contacts_returns_ordered_results(mock_store):
    mock_store._client.table.return_value.execute.return_value = MagicMock(
        data=[{"full_name": "Sarah Chen", "dm_priority": 1}]
    )
    results = list_contacts(mock_store, "radai.com")
    assert len(results) == 1
    assert results[0]["full_name"] == "Sarah Chen"


def test_upsert_contact_includes_personal_website(mock_store):
    """upsert_contact must write personal_website to the row."""
    from scripts.contacts_store import upsert_contact
    from unittest.mock import MagicMock

    store = MagicMock()
    upsert_mock = MagicMock()
    store._client.table.return_value.upsert.return_value.execute = upsert_mock

    upsert_contact(store, {
        "company_domain": "radai.com",
        "full_name": "Sarah Chen",
        "source_vector": "github",
        "personal_website": "https://sarahchen.dev",
    })

    call_args = store._client.table.return_value.upsert.call_args
    row = call_args[0][0]
    assert row.get("personal_website") == "https://sarahchen.dev"
