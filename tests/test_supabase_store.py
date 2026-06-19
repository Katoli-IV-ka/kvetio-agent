from datetime import date
from unittest.mock import MagicMock

from scripts.models import Company, ResearchRecord
from supabase_store import SupabaseStore


def _store() -> SupabaseStore:
    store = SupabaseStore.__new__(SupabaseStore)
    store._client = MagicMock()
    return store


def _company() -> Company:
    return Company(
        normalized_domain="radai.com",
        name="Rad AI",
        website="https://radai.com",
        linkedin_url="https://www.linkedin.com/company/rad-ai",
        funding_stage="seed",
        last_verified=date(2026, 6, 1),
        last_funding_date=date(2026, 5, 1),
        status="discovered",
        icp_segment="medical-imaging",
    )


def test_upsert_company_writes_only_lean_columns():
    store = _store()
    store._client.table.return_value.upsert.return_value.execute.return_value = MagicMock(data=[])

    store.upsert_company(_company())

    row = store._client.table.return_value.upsert.call_args[0][0]
    for removed in (
        "last_signal_date",
        "last_verified",
        "funding_stage",
        "funding_amount",
        "funding_date",
        "team_size",
        "site_note",
        "website_snippet",
        "dm_enriched_at",
        "created_from_signal_id",
        "last_signal_id",
    ):
        assert removed not in row


def test_upsert_research_record_writes_research_records_table():
    store = _store()
    store.resolve_company_id = MagicMock(return_value="cid")
    store._client.table.return_value.upsert.return_value.execute.return_value = MagicMock(
        data=[{"id": "rr1"}]
    )
    e = ResearchRecord(
        source="web",
        record_type="news",
        company_name="Rad AI",
        domain="radai.com",
        linkedin_url=None,
        url="https://x/y",
        observed_at=date(2026, 6, 19),
        confidence=0.5,
        record_role="monitor",
    )

    store.upsert_research_record(e, domain="radai.com")

    store._client.table.assert_called_with("research_records")
    row = store._client.table.return_value.upsert.call_args[0][0]
    assert row["record_type"] == "news"
    assert row["observed_at"] == "2026-06-19"
    assert row["record_role"] == "monitor"
