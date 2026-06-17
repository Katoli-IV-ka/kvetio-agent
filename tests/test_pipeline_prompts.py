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
    p = _read("pipeline_main_task.md")
    assert "discovery_task" in p
    assert "relevance_task" in p


def test_pipeline_bootstrap_loads_repo_managed_prompt():
    p = _read("pipeline_task.md")
    assert "pipeline_main_task.md" in p
    assert "cat agents/prompts/pipeline_main_task.md" in p
    assert "pipeline_bootstrap" in p


def test_scoring_prompt_removed():
    assert not (PROMPTS / ("scoring" + "_task.md")).exists()


def test_enrichment_prompt_gathers_links_no_analysis():
    p = _read("enrichment_task.md")
    assert "EnrichmentAgent" in p
    assert "status = 'relevant'" in p
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


def test_pipeline_full_chain():
    p = _read("pipeline_main_task.md")
    for stage in (
        "discovery_task",
        "relevance_task",
        "source_expansion_task",
        "enrichment_task",
        "analysis_task",
        "conclusions_task",
    ):
        assert stage in p


def test_conclusions_uses_notion_sync_script_not_mcp():
    p = _read("conclusions_task.md")
    assert "scripts/notion_sync.py" in p
    # Ad-hoc MCP-публикация ушла:
    assert "Notion MCP" not in p
    assert "через Notion MCP создай" not in p


def test_pipeline_calls_notion_sync_stage():
    p = _read("pipeline_main_task.md")
    assert "scripts/notion_sync.py" in p


def test_pipeline_main_applies_bot_runtime_params():
    p = _read("pipeline_main_task.md")
    for param in ("segments", "limit", "stages", "dry_run", "notion_sync"):
        assert f"`{param}`" in p
    assert "| `limit` | `5` |" in p
    assert "максимум компаний на сегмент" in p


def test_prompts_do_not_reference_removed_company_fields() -> None:
    score_prompt = "scoring" + "_task"
    removed_terms = [
        "source_page" + "_url",
        "companies." + "sources",
        "latest" + "_signal",
        "reject" + "_reason",
        "score" + "_bucket",
        "score" + "_version",
        "ai" + "_direction",
        "python scripts/" + "score.py",
        f"cat agents/prompts/{score_prompt}.md",
        score_prompt,
        "ORDER BY " + "score",
        "needs" + "_update",
        "pending" + "_verify",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in PROMPTS.glob("*.md"))

    for term in removed_terms:
        assert term not in text


def test_prompts_document_signal_type_prefixes() -> None:
    text = (PROMPTS / "pipeline_main_task.md").read_text(encoding="utf-8")
    assert "primary_*" in text
    assert "verification_*" in text
    assert "monitor_*" in text
