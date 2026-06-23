"""contacts_store tests with a mocked Supabase client."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from contacts_store import list_contacts, normalize_other_channels, normalize_x_url, upsert_contact


@pytest.fixture
def mock_store():
    store = MagicMock()
    table_mock = MagicMock()
    store._client.table.return_value = table_mock
    table_mock.upsert.return_value = table_mock
    table_mock.insert.return_value = table_mock
    table_mock.update.return_value = table_mock
    table_mock.select.return_value = table_mock
    table_mock.eq.return_value = table_mock
    table_mock.limit.return_value = table_mock
    table_mock.order.return_value = table_mock
    table_mock.execute.side_effect = [
        MagicMock(data=[{"id": "company-uuid", "domain": "radai.com"}]),
        MagicMock(data=[]),
        MagicMock(data=[{"id": "contact-uuid"}]),
    ]
    return store


def test_upsert_contact_uses_name_and_type(mock_store):
    upsert_contact(mock_store, {"company_domain": "radai.com", "name": "Sarah Chen"})
    row = mock_store._client.table.return_value.insert.call_args[0][0]
    assert row["name"] == "Sarah Chen"
    assert row["contact_type"] == "person"
    assert "first_name" not in row
    assert "last_name" not in row


def test_upsert_contact_accepts_organization(mock_store):
    upsert_contact(
        mock_store,
        {
            "company_domain": "radai.com",
            "name": "Rad AI GitHub",
            "contact_type": "organization",
        },
    )
    assert mock_store._client.table.return_value.insert.call_args[0][0]["contact_type"] == (
        "organization"
    )


def test_upsert_contact_back_compat_first_last(mock_store):
    upsert_contact(
        mock_store,
        {"company_domain": "radai.com", "first_name": "Sarah", "last_name": "Chen"},
    )
    assert mock_store._client.table.return_value.insert.call_args[0][0]["name"] == "Sarah Chen"


def test_upsert_contact_sets_required_channels(mock_store):
    contact = {
        "company_domain": "radai.com",
        "name": "Sarah Chen",
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

    row = mock_store._client.table.return_value.insert.call_args[0][0]
    assert row["company_id"] == "company-uuid"
    assert row["name"] == "Sarah Chen"
    assert row["info"] == "Head of ML; likely owns dataset/vendor decisions."
    assert row["email"] == "sarah@radai.com"
    assert row["other_channels"] == [{"type": "github", "url": "https://github.com/sarahchen"}]


def test_list_contacts_resolves_company_and_queries_by_company_id(mock_store):
    mock_store._client.table.return_value.execute.side_effect = [
        MagicMock(data=[{"id": "company-uuid", "domain": "radai.com"}]),
        MagicMock(data=[{"name": "Sarah Chen", "contact_type": "person"}]),
    ]

    results = list_contacts(mock_store, "radai.com")

    assert len(results) == 1
    assert results[0]["name"] == "Sarah Chen"
    mock_store._client.table.return_value.eq.assert_any_call("company_id", "company-uuid")


def test_normalize_other_channels_removes_primary_channel_duplicates():
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
    assert normalize_x_url({"x_url": "https://x.com/alice"}) == "https://x.com/alice"
    assert normalize_x_url({"twitter_handle": "alice"}) == "https://x.com/alice"
    assert normalize_x_url({"twitter_handle": "@alice"}) == "https://x.com/alice"


def test_contacts_store_has_no_legacy_relation_helpers():
    import contacts_store

    assert not hasattr(contacts_store, "mark_enriched")
    assert not hasattr(contacts_store, "link_contact_to_" + "companies")
    assert not hasattr(contacts_store, "get_company_domains_for_" + "contact")


def test_resolve_company_ref_by_domain(mock_store):
    from contacts_store import resolve_company_ref

    mock_store._client.table.return_value.execute.return_value = MagicMock(
        data=[{"id": "company-uuid", "domain": "acme.ai"}]
    )
    mock_store._client.table.return_value.execute.side_effect = None

    result = resolve_company_ref(mock_store, domain="acme.ai")

    assert result == {"id": "company-uuid", "domain": "acme.ai"}
    mock_store._client.table.assert_called_with("companies")


def test_resolve_company_ref_raises_for_missing_company(mock_store):
    from contacts_store import resolve_company_ref

    mock_store._client.table.return_value.execute.return_value = MagicMock(data=[])
    mock_store._client.table.return_value.execute.side_effect = None

    with pytest.raises(ValueError, match="company not found for contact"):
        resolve_company_ref(mock_store, domain="missing.ai")


def test_upsert_contact_forwards_research_provenance(mock_store):
    upsert_contact(
        mock_store,
        {
            "company_id": "company-uuid",
            "name": "Sam Lee",
            "discovered_from_research_record_id": "rr-9",
        },
    )
    row = mock_store._client.table.return_value.insert.call_args[0][0]
    assert row["discovered_from_research_record_id"] == "rr-9"


def test_upsert_contact_no_research_provenance_key_absent(mock_store):
    upsert_contact(mock_store, {"company_id": "company-uuid", "name": "Sam Lee"})
    row = mock_store._client.table.return_value.insert.call_args[0][0]
    assert "discovered_from_research_record_id" not in row


def test_upsert_contact_updates_existing_by_email(mocker):
    from contacts_store import upsert_contact

    store = MagicMock()
    table = MagicMock()
    store._client.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.limit.return_value = table
    table.order.return_value = table
    table.update.return_value = table
    table.execute.side_effect = [
        MagicMock(data=[{"id": "company-uuid", "domain": "radai.com"}]),
        MagicMock(data=[
            {
                "id": "contact-1",
                "company_id": "company-uuid",
                "contact_type": "person",
                "name": "Alice Chen",
                "info": None,
                "email": "alice@radai.com",
                "phone": None,
                "linkedin_url": None,
                "x_url": None,
                "facebook_url": None,
                "instagram_url": None,
                "other_channels": [],
            }
        ]),
        MagicMock(data=[{"id": "contact-1"}]),
    ]

    contact_id = upsert_contact(
        store,
        {
            "company_domain": "radai.com",
            "name": "Alice C.",
            "email": "alice@radai.com",
            "linkedin_url": "https://linkedin.com/in/alicechen",
            "info": "tier 1 - CTO",
        },
    )

    assert contact_id == "contact-1"
    table.update.assert_called_once()
    row = table.update.call_args.args[0]
    assert row["name"] == "Alice Chen"
    assert row["email"] == "alice@radai.com"
    assert row["linkedin_url"] == "https://linkedin.com/in/alicechen"
    assert row["info"] == "tier 1 - CTO"


def test_upsert_contact_updates_existing_by_other_channel_url(mocker):
    from contacts_store import upsert_contact

    store = MagicMock()
    table = MagicMock()
    store._client.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.limit.return_value = table
    table.order.return_value = table
    table.update.return_value = table
    table.execute.side_effect = [
        MagicMock(data=[{"id": "company-uuid", "domain": "radai.com"}]),
        MagicMock(data=[
            {
                "id": "contact-1",
                "company_id": "company-uuid",
                "contact_type": "person",
                "name": "Alice Chen",
                "info": "Existing",
                "email": None,
                "phone": None,
                "linkedin_url": None,
                "x_url": None,
                "facebook_url": None,
                "instagram_url": None,
                "other_channels": [{"type": "github", "url": "https://github.com/alice"}],
            }
        ]),
        MagicMock(data=[{"id": "contact-1"}]),
    ]

    upsert_contact(
        store,
        {
            "company_domain": "radai.com",
            "name": "Alice",
            "email": "alice@radai.com",
            "other_channels": [
                {"type": "github", "url": "https://github.com/alice"},
                {"type": "personal_website", "url": "https://alice.dev"},
            ],
        },
    )

    row = table.update.call_args.args[0]
    assert row["info"] == "Existing"
    assert row["email"] == "alice@radai.com"
    assert row["other_channels"] == [
        {"type": "github", "url": "https://github.com/alice"},
        {"type": "personal_website", "url": "https://alice.dev"},
    ]


def test_upsert_contact_falls_back_to_name_identity(mocker):
    from contacts_store import upsert_contact

    store = MagicMock()
    table = MagicMock()
    store._client.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.limit.return_value = table
    table.order.return_value = table
    table.update.return_value = table
    table.execute.side_effect = [
        MagicMock(data=[{"id": "company-uuid", "domain": "radai.com"}]),
        MagicMock(data=[
            {
                "id": "contact-1",
                "company_id": "company-uuid",
                "contact_type": "person",
                "name": "Alice Chen",
                "info": None,
                "email": None,
                "phone": None,
                "linkedin_url": None,
                "x_url": None,
                "facebook_url": None,
                "instagram_url": None,
                "other_channels": [],
            }
        ]),
        MagicMock(data=[{"id": "contact-1"}]),
    ]

    assert upsert_contact(store, {"company_domain": "radai.com", "name": " alice  chen "}) == (
        "contact-1"
    )


def test_resolve_company_ref_creates_missing_domain(mocker):
    from contacts_store import resolve_company_ref

    store = MagicMock()
    table = MagicMock()
    store._client.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.limit.return_value = table
    table.upsert.return_value = table
    table.execute.side_effect = [
        MagicMock(data=[]),
        MagicMock(data=[{"id": "company-uuid", "domain": "newco.ai"}]),
    ]

    result = resolve_company_ref(store, domain="newco.ai", create_missing=True)

    assert result == {"id": "company-uuid", "domain": "newco.ai"}
    table.upsert.assert_called_once()
    row = table.upsert.call_args.args[0]
    assert row["domain"] == "newco.ai"
    assert row["name"] == "newco.ai"
    assert row["website"] == "https://newco.ai"
    assert row["status"] == "discovered"
