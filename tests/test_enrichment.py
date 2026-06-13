"""Тесты фреймворка enrichment и резолверов."""

from __future__ import annotations

from unittest.mock import MagicMock

from enrichment import _DisabledStub, run_enrichment


class _FakeResolver:
    def __init__(self, kind, enabled, link):
        self.kind = kind
        self.enabled = enabled
        self._link = link

    def resolve(self, company, store, client):
        return self._link


def _link(domain, kind):
    return {"company_domain": domain, "kind": kind, "url": f"https://x/{kind}"}


def test_run_enrichment_skips_disabled():
    store = MagicMock()
    client = MagicMock()
    company = {"domain": "radai.com"}
    resolvers = [
        _FakeResolver("a", True, _link("radai.com", "a")),
        _FakeResolver("b", False, _link("radai.com", "b")),
    ]
    written = run_enrichment(company, store, client, resolvers=resolvers)
    kinds = [w["kind"] for w in written]
    assert kinds == ["a"]


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
