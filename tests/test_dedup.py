import sys
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
