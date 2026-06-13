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
