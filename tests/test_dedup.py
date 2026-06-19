import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


def test_find_fuzzy_duplicate_exact_name_match():
    """Компания с тем же нормализованным названием — дубль."""
    from supabase_store import SupabaseStore

    store = SupabaseStore.__new__(SupabaseStore)
    mock_client = MagicMock()
    store._client = mock_client

    mock_client.table.return_value.select.return_value.execute.return_value.data = [
        {"name": "MedVision AI Inc.", "domain": "medvision.ai"},
        {"name": "DeepScan Corp", "domain": "deepscan.io"},
    ]

    result = store.find_fuzzy_duplicate("MedVision AI")
    assert result == "medvision.ai"


def test_find_fuzzy_duplicate_no_match():
    """Новая компания — не дубль."""
    from supabase_store import SupabaseStore

    store = SupabaseStore.__new__(SupabaseStore)
    mock_client = MagicMock()
    store._client = mock_client

    mock_client.table.return_value.select.return_value.execute.return_value.data = [
        {"name": "MedVision AI Inc.", "domain": "medvision.ai"},
    ]

    result = store.find_fuzzy_duplicate("Totally Different Company")
    assert result is None


def test_find_fuzzy_duplicate_threshold():
    """Схожесть ниже порога 0.85 — не дубль."""
    from supabase_store import SupabaseStore

    store = SupabaseStore.__new__(SupabaseStore)
    mock_client = MagicMock()
    store._client = mock_client

    mock_client.table.return_value.select.return_value.execute.return_value.data = [
        {"name": "MedVision Technologies", "domain": "medvision.tech"},
    ]

    result = store.find_fuzzy_duplicate("MedVision AI")
    # "medvision technologies" vs "medvision ai" — разные, ниже 0.85
    assert result is None


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


def test_list_stale_review_queue_queries_unverified_or_old_companies(monkeypatch):
    """Stale review queue выбирает записи без проверки или старше порога."""
    from supabase_store import SupabaseStore

    class FakeDate(date):
        @classmethod
        def today(cls) -> date:
            return cls(2026, 6, 12)

    monkeypatch.setattr("supabase_store.date", FakeDate)

    store = SupabaseStore.__new__(SupabaseStore)
    mock_client = MagicMock()
    query = MagicMock()
    response = MagicMock()
    response.data = [{"name": "Needs Review", "domain": "needs-review.ai"}]

    store._client = mock_client
    mock_client.table.return_value.select.return_value = query
    query.in_.return_value = query
    query.or_.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.return_value = response

    result = store.list_stale_review_queue(days=30, limit=10)

    assert result == response.data
    query.in_.assert_called_with(
        "status",
        ["discovered", "manual_review", "relevant"],
    )
    query.or_.assert_called_with("last_verified.is.null,last_verified.lt.2026-05-13")
    query.order.assert_called_with("last_verified", desc=False)
    query.limit.assert_called_with(10)


# ── New signal upsert tests ───────────────────────────────────────────────────

def _make_raw_signal(url: str = "https://github.com/acme", signal_type: str = "github_repo"):
    from scripts.models import RawSignal
    return RawSignal(
        source="github",
        signal_type=signal_type,
        company_name="Acme",
        domain="acme.com",
        linkedin_url=None,
        url=url,
        signal_date=date(2026, 6, 1),
        confidence="high",
        agent="discovery",
    )


def test_upsert_signal_uses_dedupe_key():
    from supabase_store import SupabaseStore

    store = SupabaseStore.__new__(SupabaseStore)
    mock_client = MagicMock()
    store._client = mock_client

    # company_id lookup not needed — we pass company_id directly
    upsert_chain = MagicMock()
    upsert_chain.execute.return_value.data = [{"id": "sig-1"}]
    mock_client.table.return_value.upsert.return_value = upsert_chain

    sig = _make_raw_signal()
    result = store.upsert_signal(
        sig,
        company_id="11111111-1111-1111-1111-111111111111",
    )

    assert result is True
    call_kwargs = mock_client.table.return_value.upsert.call_args
    row = call_kwargs[0][0]
    assert call_kwargs[1]["on_conflict"] == "dedupe_key"
    assert "dedupe_key" in row
    assert row["company_id"] == "11111111-1111-1111-1111-111111111111"
    assert row["url"] == "https://github.com/acme"
    assert row["confidence"] == 0.9   # "high" -> 0.9


def test_upsert_signal_resolves_domain_when_no_company_id():
    from supabase_store import SupabaseStore

    store = SupabaseStore.__new__(SupabaseStore)
    mock_client = MagicMock()
    store._client = mock_client

    # First call: resolve domain -> company_id
    resolve_chain = MagicMock()
    resolve_chain.execute.return_value.data = [{"id": "cid-resolved"}]
    # Second call: upsert signal
    upsert_chain = MagicMock()
    upsert_chain.execute.return_value.data = [{"id": "sig-2"}]

    mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value = resolve_chain
    mock_client.table.return_value.upsert.return_value = upsert_chain

    sig = _make_raw_signal()
    store.upsert_signal(sig, domain="acme.com")

    row = mock_client.table.return_value.upsert.call_args[0][0]
    assert row["company_id"] == "cid-resolved"


def test_upsert_signal_raises_when_company_not_found():
    from supabase_store import SupabaseStore

    store = SupabaseStore.__new__(SupabaseStore)
    mock_client = MagicMock()
    store._client = mock_client

    mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []

    sig = _make_raw_signal()
    try:
        store.upsert_signal(sig, domain="unknown.com")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_dedupe_key_is_deterministic():
    from supabase_store import SupabaseStore

    k1 = SupabaseStore._dedupe_key("cid-1", "github_repo", "https://github.com/a", "fallback")
    k2 = SupabaseStore._dedupe_key("cid-1", "github_repo", "https://github.com/a", "fallback")
    assert k1 == k2
    assert len(k1) == 40  # SHA-1 hex


def test_get_signals_for_company_uses_company_id():
    from supabase_store import SupabaseStore

    store = SupabaseStore.__new__(SupabaseStore)
    mock_client = MagicMock()
    store._client = mock_client

    resolve_chain = MagicMock()
    resolve_chain.execute.return_value.data = [{"id": "cid-xyz"}]
    mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value = resolve_chain

    signals_chain = MagicMock()
    signals_chain.execute.return_value.data = [{"id": "sig-1", "company_id": "cid-xyz"}]
    mock_client.table.return_value.select.return_value.eq.return_value.order.return_value = signals_chain

    result = store.get_signals_for_company("acme.com")
    assert result == [{"id": "sig-1", "company_id": "cid-xyz"}]
