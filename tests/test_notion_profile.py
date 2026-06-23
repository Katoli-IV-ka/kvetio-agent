"""Tests for notion_profile: pure profile-builder functions."""
from __future__ import annotations
import pytest
import notion_profile as np_mod


# ---------------------------------------------------------------------------
# _format_amount
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("usd,expected", [
    (12_000_000,        "$12M"),
    (3_500_000,         "$3.5M"),
    (750_000,           "$750K"),
    (1_000_000_000,     "$1B"),
    (1_200_000_000,     "$1.2B"),
    (500,               "$500"),
    (1_000,             "$1K"),
    (1_100,             "$1.1K"),
    (100_000_000,       "$100M"),
])
def test_format_amount(usd, expected):
    assert np_mod._format_amount(usd) == expected


# ---------------------------------------------------------------------------
# _compute_funding_info
# ---------------------------------------------------------------------------

def test_funding_info_both():
    result = np_mod._compute_funding_info("Series A", 12_000_000)
    assert result == "Series A · $12M"


def test_funding_info_stage_only():
    result = np_mod._compute_funding_info("Seed", None)
    assert result == "Seed"


def test_funding_info_amount_only():
    result = np_mod._compute_funding_info(None, 3_000_000)
    assert result == "$3M"


def test_funding_info_none():
    result = np_mod._compute_funding_info(None, None)
    assert result is None


# ---------------------------------------------------------------------------
# _compute_potential_data
# ---------------------------------------------------------------------------

_POTENTIAL_CFG = {
    "segments": {
        "medical-imaging": ["Medical Data", "Images", "Annotation"],
        "generative-ai": ["Text", "LLM Data", "Human Feedback"],
    },
    "status_overrides": {
        "data_partner": ["Data Supplier"],
    },
}


def test_potential_data_by_segment():
    result = np_mod._compute_potential_data("medical-imaging", "relevant", _POTENTIAL_CFG)
    assert result == ["Medical Data", "Images", "Annotation"]


def test_potential_data_union_with_status_override():
    result = np_mod._compute_potential_data("generative-ai", "data_partner", _POTENTIAL_CFG)
    assert result == ["Text", "LLM Data", "Human Feedback", "Data Supplier"]


def test_potential_data_no_duplicate_when_override_already_in_segment():
    cfg = {
        "segments": {"seg": ["A", "B"]},
        "status_overrides": {"data_partner": ["B", "C"]},
    }
    result = np_mod._compute_potential_data("seg", "data_partner", cfg)
    assert result == ["A", "B", "C"]


def test_potential_data_unknown_segment_returns_empty():
    result = np_mod._compute_potential_data("unknown-segment", "relevant", _POTENTIAL_CFG)
    assert result == []


def test_potential_data_none_segment_returns_empty():
    result = np_mod._compute_potential_data(None, None, _POTENTIAL_CFG)
    assert result == []


# ---------------------------------------------------------------------------
# _compute_last_info_update
# ---------------------------------------------------------------------------

def test_last_info_update_max_across_all_sources():
    company = {"updated_at": "2026-01-01T00:00:00"}
    dossier = {"updated_at": "2026-03-15T00:00:00"}
    aggregates = {
        "last_research_created_at": "2026-02-10",
        "last_contact_updated_at": "2026-04-01",
    }
    result = np_mod._compute_last_info_update(company, dossier, aggregates)
    assert result == "2026-04-01"


def test_last_info_update_ignores_none():
    company = {"updated_at": "2026-05-01T00:00:00"}
    result = np_mod._compute_last_info_update(company, None, {})
    assert result == "2026-05-01"


def test_last_info_update_returns_none_when_all_none():
    result = np_mod._compute_last_info_update({}, None, {})
    assert result is None


# ---------------------------------------------------------------------------
# build_company_notion_profile
# ---------------------------------------------------------------------------

_COMPANY = {
    "id": "co-uuid",
    "domain": "acme.ai",
    "name": "Acme AI",
    "website": "https://acme.ai",
    "linkedin_url": "https://linkedin.com/company/acme",
    "icp_segment": "medical-imaging",
    "status": "relevant",
    "description": "AI-powered radiology platform.",
    "hq_country": "US",
    "notion_page_id": "np-123",
    "notion_synced_at": "2026-06-01T00:00:00",
    "updated_at": "2026-06-01T00:00:00",
}

_DOSSIER = {
    "company_id": "co-uuid",
    "team_size_estimate": "11-50",
    "funding_stage": "Series A",
    "funding_amount_usd": 12_000_000,
    "updated_at": "2026-06-10T00:00:00",
}

_AGGREGATES = {
    "last_research_created_at": "2026-06-15",
    "last_contact_updated_at": None,
}


def test_profile_contains_expected_fields():
    profile = np_mod.build_company_notion_profile(
        _COMPANY, _DOSSIER, _AGGREGATES, _POTENTIAL_CFG
    )
    assert profile["name"] == "Acme AI"
    assert profile["website"] == "https://acme.ai"
    assert profile["linkedin_url"] == "https://linkedin.com/company/acme"
    assert profile["icp_segment"] == "medical-imaging"
    assert profile["status"] == "relevant"
    assert profile["description"] == "AI-powered radiology platform."
    assert profile["hq_country"] == "US"
    assert profile["team_size_estimate"] == "11-50"
    assert profile["funding_info"] == "Series A · $12M"
    assert profile["potential_data"] == ["Medical Data", "Images", "Annotation"]
    assert profile["last_info_update"] == "2026-06-15"


def test_profile_preserves_service_keys():
    profile = np_mod.build_company_notion_profile(
        _COMPANY, _DOSSIER, _AGGREGATES, _POTENTIAL_CFG
    )
    assert profile["id"] == "co-uuid"
    assert profile["domain"] == "acme.ai"
    assert profile["notion_page_id"] == "np-123"
    assert profile["notion_synced_at"] == "2026-06-01T00:00:00"


def test_profile_none_dossier():
    profile = np_mod.build_company_notion_profile(
        _COMPANY, None, {}, _POTENTIAL_CFG
    )
    assert profile["team_size_estimate"] is None
    assert profile["funding_info"] is None


def test_profile_translator_translates_description():
    class StubTranslator:
        def translate(self, text: str) -> str:
            return f"RU:{text}"

    profile = np_mod.build_company_notion_profile(
        _COMPANY, None, {}, _POTENTIAL_CFG, translator=StubTranslator()
    )
    assert profile["description"] == "RU:AI-powered radiology platform."


def test_profile_translator_does_not_translate_select_fields():
    class StubTranslator:
        def translate(self, text: str) -> str:
            return f"RU:{text}"

    profile = np_mod.build_company_notion_profile(
        _COMPANY, None, {}, _POTENTIAL_CFG, translator=StubTranslator()
    )
    assert profile["icp_segment"] == "medical-imaging"
    assert profile["status"] == "relevant"
    assert profile["hq_country"] == "US"


# ---------------------------------------------------------------------------
# build_company_profiles
# ---------------------------------------------------------------------------

class _CountingFakeDb:
    """Fake DB that counts fetch calls per table."""
    def __init__(self):
        self.fetch_calls: list[str] = []
        self.tables: dict[str, list[dict]] = {
            "dossiers": [
                {
                    "company_id": "co1",
                    "team_size_estimate": "11-50",
                    "funding_stage": "Series A",
                    "funding_amount_usd": 12_000_000,
                    "updated_at": "2026-06-10T00:00:00",
                }
            ],
            "research_records": [
                {"company_id": "co1", "created_at": "2026-06-15T00:00:00"},
                {"company_id": "co2", "created_at": "2026-06-01T00:00:00"},
            ],
            "contacts": [
                {"company_id": "co1", "updated_at": "2026-06-20T00:00:00"},
            ],
        }

    def fetch(self, table, status_filter=None):
        self.fetch_calls.append(table)
        return list(self.tables.get(table, []))


_COMPANIES_TWO = [
    {
        "id": "co1", "domain": "acme.ai", "name": "Acme", "website": "https://acme.ai",
        "linkedin_url": None, "icp_segment": "medical-imaging", "status": "relevant",
        "description": "Radiology AI.", "hq_country": "US",
        "notion_page_id": None, "notion_synced_at": None,
        "updated_at": "2026-06-01T00:00:00",
    },
    {
        "id": "co2", "domain": "beta.io", "name": "Beta", "website": "https://beta.io",
        "linkedin_url": None, "icp_segment": "generative-ai", "status": "analyzed",
        "description": "LLM platform.", "hq_country": None,
        "notion_page_id": None, "notion_synced_at": None,
        "updated_at": "2026-06-02T00:00:00",
    },
]


def test_build_company_profiles_constant_fetch_count():
    db = _CountingFakeDb()
    profiles = np_mod.build_company_profiles(_COMPANIES_TWO, db, _POTENTIAL_CFG)
    assert len(profiles) == 2
    assert db.fetch_calls.count("dossiers") == 1
    assert db.fetch_calls.count("research_records") == 1
    assert db.fetch_calls.count("contacts") == 1
    assert len(db.fetch_calls) == 3


def test_build_company_profiles_correct_dossier_lookup():
    db = _CountingFakeDb()
    profiles = np_mod.build_company_profiles(_COMPANIES_TWO, db, _POTENTIAL_CFG)
    co1 = next(p for p in profiles if p["domain"] == "acme.ai")
    assert co1["team_size_estimate"] == "11-50"
    assert co1["funding_info"] == "Series A · $12M"


def test_build_company_profiles_aggregates_max_dates():
    db = _CountingFakeDb()
    profiles = np_mod.build_company_profiles(_COMPANIES_TWO, db, _POTENTIAL_CFG)
    co1 = next(p for p in profiles if p["domain"] == "acme.ai")
    # research 2026-06-15 < contact 2026-06-20 → last_info_update = 2026-06-20
    assert co1["last_info_update"] == "2026-06-20"


def test_build_company_profiles_no_dossier_for_company():
    db = _CountingFakeDb()
    profiles = np_mod.build_company_profiles(_COMPANIES_TWO, db, _POTENTIAL_CFG)
    co2 = next(p for p in profiles if p["domain"] == "beta.io")
    assert co2["team_size_estimate"] is None
    assert co2["funding_info"] is None
