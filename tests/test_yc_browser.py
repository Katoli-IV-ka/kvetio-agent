import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from yc_browser import (
    company_to_signal,
    filter_companies_by_tags,
    ICP_TAG_MAP,
    AI_ML_BASE_TAGS,
    resolve_tags,
)


# ---------------------------------------------------------------------------
# company_to_signal
# ---------------------------------------------------------------------------

def test_company_to_signal_basic():
    """Корректный объект компании конвертируется в сигнал."""
    company = {
        "name": "Acme AI",
        "website": "https://acme.ai",
        "slug": "acme-ai",
        "one_liner": "AI for healthcare diagnostics",
        "batch": "W24",
        "tags": ["Machine Learning", "Healthcare"],
        "team_size": 15,
        "status": "Active",
    }
    signal = company_to_signal(company)
    assert signal is not None
    assert signal["company_name"] == "Acme AI"
    assert signal["domain"] == "acme.ai"
    assert signal["source"] == "yc_browser"
    assert signal["signal_type"] == "yc_company"
    assert signal["batch"] == "W24"
    assert signal["url"] == "https://www.ycombinator.com/companies/acme-ai"


def test_company_to_signal_empty_returns_none():
    """Объект без имени и сайта → None."""
    signal = company_to_signal({"name": "", "website": "", "slug": "x"})
    assert signal is None


def test_company_to_signal_domain_normalization():
    """URL нормализуется до чистого домена."""
    company = {
        "name": "Test Co",
        "website": "https://www.testco.com/path?q=1",
        "slug": "test-co",
        "one_liner": "Test",
        "batch": "S23",
        "tags": [],
        "status": "Active",
    }
    signal = company_to_signal(company)
    assert signal["domain"] == "testco.com"


def test_company_to_signal_uses_long_description_fallback():
    """Если нет one_liner — берём long_description."""
    company = {
        "name": "Speech Co",
        "website": "https://speech.co",
        "slug": "speech-co",
        "long_description": "Voice AI platform for enterprises",
        "batch": "W23",
        "tags": ["Speech Recognition"],
        "status": "Active",
    }
    signal = company_to_signal(company)
    assert signal["description"] == "Voice AI platform for enterprises"


# ---------------------------------------------------------------------------
# filter_companies_by_tags
# ---------------------------------------------------------------------------

def test_filter_companies_by_tags_match():
    """Компания с совпадающим тегом включается."""
    companies = [
        {"name": "A", "tags": ["Machine Learning"], "status": "Active"},
        {"name": "B", "tags": ["Fintech"], "status": "Active"},
    ]
    result = filter_companies_by_tags(companies, ["Machine Learning"])
    assert len(result) == 1
    assert result[0]["name"] == "A"


def test_filter_companies_by_tags_case_insensitive():
    """Сравнение тегов нечувствительно к регистру."""
    companies = [{"name": "A", "tags": ["machine learning"], "status": "Active"}]
    result = filter_companies_by_tags(companies, ["Machine Learning"])
    assert len(result) == 1


def test_filter_companies_by_tags_inactive_excluded():
    """Inactive-компании исключаются по умолчанию."""
    companies = [
        {"name": "A", "tags": ["Machine Learning"], "status": "Inactive"},
        {"name": "B", "tags": ["Machine Learning"], "status": "Active"},
    ]
    result = filter_companies_by_tags(companies, ["Machine Learning"])
    assert len(result) == 1
    assert result[0]["name"] == "B"


# ---------------------------------------------------------------------------
# ICP_TAG_MAP
# ---------------------------------------------------------------------------

def test_icp_tag_map_has_all_segments():
    """Все три ICP-сегмента присутствуют в маппинге."""
    assert "medical-imaging" in ICP_TAG_MAP
    assert "autonomous-vehicles" in ICP_TAG_MAP
    assert "speech-and-audio" in ICP_TAG_MAP


def test_icp_tags_not_empty():
    """Каждый сегмент имеет минимум 3 тега."""
    for segment, tags in ICP_TAG_MAP.items():
        assert len(tags) >= 3, f"Segment '{segment}' has only {len(tags)} tags"


# ---------------------------------------------------------------------------
# resolve_tags
# ---------------------------------------------------------------------------

def test_resolve_tags_by_segment():
    """resolve_tags для known segment возвращает теги сегмента + базовые AI/ML теги."""
    tags = resolve_tags(segment="medical-imaging")
    assert "Healthcare" in tags or "Medical Devices" in tags
    assert len(tags) > 3


def test_resolve_tags_by_custom():
    """resolve_tags для custom строки парсит через запятую."""
    tags = resolve_tags(tags_str="Machine Learning, Computer Vision")
    assert "Machine Learning" in tags
    assert "Computer Vision" in tags


def test_resolve_tags_default_is_ai_ml():
    """resolve_tags без аргументов возвращает AI_ML_BASE_TAGS."""
    tags = resolve_tags()
    assert set(tags) == set(AI_ML_BASE_TAGS)
