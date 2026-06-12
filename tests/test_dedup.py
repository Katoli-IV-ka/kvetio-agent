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


def test_list_hot_leads_queries_hot_enriched_companies():
    """Hot leads queue сортируется по score и ограничивается limit."""
    from supabase_store import SupabaseStore

    store = SupabaseStore.__new__(SupabaseStore)
    mock_client = MagicMock()
    query = MagicMock()
    response = MagicMock()
    response.data = [{"name": "Acme", "domain": "acme.ai", "score": 80}]

    store._client = mock_client
    mock_client.table.return_value.select.return_value = query
    query.eq.return_value = query
    query.order.return_value = query
    query.limit.return_value = query
    query.execute.return_value = response

    result = store.list_hot_leads(limit=3)

    assert result == response.data
    mock_client.table.assert_called_with("companies")
    query.eq.assert_any_call("status", "enriched")
    query.eq.assert_any_call("score_bucket", "Hot")
    query.order.assert_called_with("score", desc=True)
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
        ["new", "pending_verify", "pending_enrich", "needs_update", "manual_review"],
    )
    query.or_.assert_called_with("last_verified.is.null,last_verified.lt.2026-05-13")
    query.order.assert_called_with("last_verified", desc=False)
    query.limit.assert_called_with(10)
