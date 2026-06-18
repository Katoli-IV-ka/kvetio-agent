"""contacts_store tests with a mocked Supabase client."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from contacts_store import (
    list_contacts,
    mark_enriched,
    upsert_contact,
)


@pytest.fixture
def mock_store():
    store = MagicMock()
    table_mock = MagicMock()
    store._client.table.return_value = table_mock
    table_mock.upsert.return_value = table_mock
    table_mock.update.return_value = table_mock
    table_mock.select.return_value = table_mock
    table_mock.eq.return_value = table_mock
    table_mock.limit.return_value = table_mock
    table_mock.order.return_value = table_mock
    table_mock.execute.return_value = MagicMock(
        data=[{"id": "company-uuid", "domain": "radai.com"}]
    )
    return store


def test_upsert_contact_sets_required_fields(mock_store):
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


def test_upsert_contact_defaults_empty_last_name(mock_store):
    contact = {"company_domain": "radai.com", "full_name": "Prince"}
    upsert_contact(mock_store, contact)
    row = mock_store._client.table.return_value.upsert.call_args[0][0]
    assert row["first_name"] == "Prince"
    assert row["last_name"] == ""


def test_mark_enriched_updates_dm_enriched_at(mock_store):
    mark_enriched(mock_store, "radai.com")
    mock_store._client.table.assert_called_with("companies")
    update_args = mock_store._client.table.return_value.update.call_args[0][0]
    assert "dm_enriched_at" in update_args


def test_list_contacts_resolves_company_and_queries_by_company_id(mock_store):
    mock_store._client.table.return_value.execute.side_effect = [
        MagicMock(data=[{"id": "company-uuid", "domain": "radai.com"}]),
        MagicMock(data=[{"first_name": "Sarah", "last_name": "Chen"}]),
    ]

    results = list_contacts(mock_store, "radai.com")

    assert len(results) == 1
    assert results[0]["first_name"] == "Sarah"
    mock_store._client.table.return_value.eq.assert_any_call("company_id", "company-uuid")


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


def test_contacts_store_has_no_legacy_relation_helpers():
    import contacts_store

    assert not hasattr(contacts_store, "link_contact_to_" + "companies")
    assert not hasattr(contacts_store, "get_company_domains_for_" + "contact")


def test_resolve_company_ref_by_domain(mock_store):
    from contacts_store import resolve_company_ref

    mock_store._client.table.return_value.execute.return_value = MagicMock(
        data=[{"id": "company-uuid", "domain": "acme.ai"}]
    )

    result = resolve_company_ref(mock_store, domain="acme.ai")

    assert result == {"id": "company-uuid", "domain": "acme.ai"}
    mock_store._client.table.assert_called_with("companies")


def test_resolve_company_ref_raises_for_missing_company(mock_store):
    from contacts_store import resolve_company_ref

    mock_store._client.table.return_value.execute.return_value = MagicMock(data=[])

    with pytest.raises(ValueError, match="company not found for contact"):
        resolve_company_ref(mock_store, domain="missing.ai")
