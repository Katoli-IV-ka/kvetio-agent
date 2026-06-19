"""Тесты фреймворка enrichment и резолверов."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import Response

from enrichment import (
    GithubOrgResolver,
    WaybackResolver,
    _DisabledStub,
    run_enrichment,
)
from http_client import HttpClient


class _FakeResolver:
    def __init__(self, kind, enabled, link):
        self.kind = kind
        self.enabled = enabled
        self._link = link

    def resolve(self, company, store, client):
        return self._link


def _link(company_id, kind):
    return {"company_id": company_id, "kind": kind, "url": f"https://x/{kind}"}


def test_run_enrichment_skips_disabled():
    store = MagicMock()
    client = MagicMock()
    company = {"domain": "radai.com", "id": "00000000-0000-0000-0000-000000000001"}
    resolvers = [
        _FakeResolver("a", True, _link(company["id"], "a")),
        _FakeResolver("b", False, _link(company["id"], "b")),
    ]
    written = run_enrichment(company, store, client, resolvers=resolvers)
    kinds = [w["kind"] for w in written]
    assert kinds == ["a"]
    assert store.upsert_research_record.call_count == 1
    entry = store.upsert_research_record.call_args[0][0]
    assert entry.record_type == "source_link"
    assert entry.record_role == "source"


def test_run_enrichment_swallows_resolver_errors():
    store = MagicMock()
    client = MagicMock()

    class _Boom:
        kind = "boom"
        enabled = True

        def resolve(self, company, store, client):
            raise RuntimeError("network down")

    written = run_enrichment({"domain": "radai.com"}, store, client, resolvers=[_Boom()])
    assert written == []


def test_disabled_stub_is_disabled_and_returns_none():
    stub = _DisabledStub("linkedin")
    assert stub.enabled is False
    assert stub.kind == "linkedin"
    assert stub.resolve({"domain": "radai.com"}, MagicMock(), MagicMock()) is None


_COMPANY = {"domain": "radai.com", "id": "00000000-0000-0000-0000-000000000001"}


def test_github_org_resolver_from_research_records():
    store = MagicMock()
    store.get_research_records_for_company.return_value = [
        {"url": "https://github.com/radai-robolab/some-repo"},
    ]
    link = GithubOrgResolver().resolve(_COMPANY, store, MagicMock())
    assert link["kind"] == "github_org"
    assert link["url"] == "https://github.com/radai-robolab"
    assert link["company_id"] == _COMPANY["id"]


def test_github_org_resolver_none_when_no_github_signal():
    store = MagicMock()
    store.get_research_records_for_company.return_value = [
        {"url": "https://huggingface.co/radai"},
    ]
    assert GithubOrgResolver().resolve(_COMPANY, store, MagicMock()) is None


@pytest.mark.respx(base_url="http://archive.org")
def test_wayback_resolver_returns_snapshot(respx_mock):
    respx_mock.get("/wayback/available").mock(
        return_value=Response(200, json={
            "archived_snapshots": {
                "closest": {"url": "http://web.archive.org/web/2025/https://radai.com"}
            }
        })
    )
    with HttpClient(rate_limit_rps=0) as client:
        link = WaybackResolver().resolve(_COMPANY, MagicMock(), client)
    assert link["kind"] == "wayback"
    assert "web.archive.org" in link["url"]
    assert link["company_id"] == _COMPANY["id"]


@pytest.mark.respx(base_url="http://archive.org")
def test_wayback_resolver_none_when_no_snapshot(respx_mock):
    respx_mock.get("/wayback/available").mock(
        return_value=Response(200, json={"archived_snapshots": {}})
    )
    with HttpClient(rate_limit_rps=0) as client:
        assert WaybackResolver().resolve(_COMPANY, MagicMock(), client) is None
