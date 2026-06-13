"""Контракт-тесты содержимого промптов этапов 1–2."""

from __future__ import annotations

from pathlib import Path

PROMPTS = Path(__file__).parent.parent / "agents" / "prompts"


def _read(name: str) -> str:
    return (PROMPTS / name).read_text(encoding="utf-8")


def test_discovery_prompt_exists_and_writes_discovered():
    p = _read("discovery_task.md")
    assert "DiscoveryAgent" in p
    assert "discovered" in p
    assert "scripts/huggingface.py" in p
    assert "scripts/yc_browser.py" in p
    # Этап 1 НЕ делает верификацию релевантности:
    assert "Quick Filter" not in p


def test_relevance_prompt_exists_and_consumes_discovered():
    p = _read("relevance_task.md")
    assert "RelevanceAgent" in p
    assert "status = 'discovered'" in p
    assert "Quick Filter" in p
    assert "'relevant'" in p
    assert "'not_relevant'" in p
    assert "manual_review" in p


def test_discover_verify_is_deprecated():
    p = _read("discover_verify_task.md")
    assert "УСТАРЕЛ" in p


def test_pipeline_orchestrates_discovery_then_relevance():
    p = _read("pipeline_task.md")
    assert "discovery_task" in p
    assert "relevance_task" in p


def test_scoring_is_triage_gate():
    p = _read("scoring_task.md")
    # Вход — relevant (этап 2), а не старый pending_enrich:
    assert "status = 'relevant'" in p
    assert "pending_enrich" not in p
    # Выход — гейт-статусы:
    assert "'qualified'" in p
    assert "'triaged_out'" in p
    # Гейт по порогу manual_review (Hot+Warm проходят даже в shadow mode):
    assert "threshold_manual_review" in p or "manual_review threshold" in p
    # Notion-синк уехал на этап 5:
    assert "Синхронизация в Notion" not in p


def test_enrichment_prompt_gathers_links_no_analysis():
    p = _read("enrichment_task.md")
    assert "EnrichmentAgent" in p
    assert "status = 'qualified'" in p
    assert "scripts/enrichment.py --domain" in p
    assert "upsert-source-link" in p
    assert "sources_gathered" in p
    # Этап 3 не анализирует:
    assert "аудит" not in p.lower()


def test_analysis_section_prompt():
    p = _read("analysis_section_task.md")
    assert "section" in p
    assert "upsert-analysis-note" in p
    # Разделение заявлений и фактов:
    assert "заявлен" in p.lower()
    assert "факт" in p.lower()
    # Контекст задачи (продажа data services):
    assert "data services" in p or "датасет" in p.lower()


def test_analysis_audit_prompt():
    p = _read("analysis_audit_task.md")
    assert "list-analysis-notes" in p
    assert "audit" in p
    assert "продаж" in p.lower()  # вывод для нас: продажа датасетов


def test_analysis_orchestrator_prompt():
    p = _read("analysis_task.md")
    assert "AnalysisAgent" in p
    assert "status = 'sources_gathered'" in p
    assert "analysis_section_task" in p
    assert "analysis_audit_task" in p
    assert "analyzed" in p
    for section in ("company", "product", "collaboration", "financials", "news"):
        assert section in p


def test_conclusions_prompt():
    p = _read("conclusions_task.md")
    assert "ConclusionAgent" in p
    assert "status = 'analyzed'" in p
    assert "list-analysis-notes" in p
    assert "upsert-dossier" in p
    assert "Notion" in p
    assert "dossier_ready" in p
    # 6 секций саммари:
    for section in ("компании", "Продукт", "Сотрудничество", "Финанс", "Новости", "удит"):
        assert section in p
