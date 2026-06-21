"""Тесты фреймворка enrichment и резолверов."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import Response

from enrichment import (
    ArxivResolver,
    GdeltFundingResolver,
    GithubOrgResolver,
    OpenCorporatesResolver,
    PapersWithCodeResolver,
    SbirGrantsResolver,
    SecEdgarResolver,
    WaybackResolver,
    WikidataResolver,
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


_NAMED_COMPANY = {
    "domain": "radai.com",
    "name": "Rad AI",
    "id": "00000000-0000-0000-0000-000000000001",
}

_ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.00001v1</id>
    <title>Deep Medical Imaging
      at Rad AI</title>
    <published>2024-01-01T00:00:00Z</published>
    <author><name>Alice Chen</name></author>
    <author><name>Bob Lee</name></author>
  </entry>
  <entry>
    <id>http://arxiv.org/abs/2401.00002v1</id>
    <title>Second Paper</title>
    <published>2024-02-02T00:00:00Z</published>
    <author><name>Carol Ng</name></author>
  </entry>
</feed>"""


@pytest.mark.respx(base_url="http://export.arxiv.org")
def test_arxiv_resolver_parses_entries(respx_mock):
    respx_mock.get("/api/query").mock(return_value=Response(200, text=_ATOM_FEED))
    with HttpClient(rate_limit_rps=0) as client:
        links = ArxivResolver().resolve(_NAMED_COMPANY, MagicMock(), client)
    assert len(links) == 2
    first = links[0]
    assert first["kind"] == "arxiv"
    assert first["url"] == "http://arxiv.org/abs/2401.00001v1"
    assert first["title"] == "Deep Medical Imaging at Rad AI"  # whitespace collapsed
    assert first["published"] == "2024-01-01"
    assert first["authors"] == ["Alice Chen", "Bob Lee"]
    assert first["company_id"] == _NAMED_COMPANY["id"]


@pytest.mark.respx(base_url="http://export.arxiv.org")
def test_arxiv_resolver_empty_feed(respx_mock):
    empty = '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>'
    respx_mock.get("/api/query").mock(return_value=Response(200, text=empty))
    with HttpClient(rate_limit_rps=0) as client:
        assert ArxivResolver().resolve(_NAMED_COMPANY, MagicMock(), client) == []


@pytest.mark.respx(base_url="https://paperswithcode.com")
def test_papers_with_code_resolver(respx_mock):
    respx_mock.get("/api/v1/search/").mock(return_value=Response(200, json={
        "count": 2,
        "results": [
            {"paper": {"id": "deep-medical", "title": "Deep Medical",
                       "url_abs": "https://paperswithcode.com/paper/deep-medical"}},
            {"paper": {"id": "x2", "title": "X2", "url_pdf": "https://arxiv.org/pdf/x2"}},
        ],
    }))
    with HttpClient(rate_limit_rps=0) as client:
        links = PapersWithCodeResolver().resolve(_NAMED_COMPANY, MagicMock(), client)
    assert [link["url"] for link in links] == [
        "https://paperswithcode.com/paper/deep-medical",
        "https://arxiv.org/pdf/x2",
    ]
    assert all(link["kind"] == "papers_with_code" for link in links)


@pytest.mark.respx(base_url="https://paperswithcode.com")
def test_papers_with_code_resolver_empty(respx_mock):
    respx_mock.get("/api/v1/search/").mock(return_value=Response(200, json={"results": []}))
    with HttpClient(rate_limit_rps=0) as client:
        assert PapersWithCodeResolver().resolve(_NAMED_COMPANY, MagicMock(), client) == []


@pytest.mark.respx(base_url="https://www.wikidata.org")
def test_wikidata_resolver_extracts_claims(respx_mock):
    respx_mock.get("/w/api.php").mock(return_value=Response(200, json={
        "search": [{"id": "Q42", "label": "Rad AI", "description": "AI company"}],
    }))
    respx_mock.get("/wiki/Special:EntityData/Q42.json").mock(return_value=Response(200, json={
        "entities": {"Q42": {"claims": {
            "P571": [{"mainsnak": {"datavalue": {"value": {"time": "+2018-05-01T00:00:00Z"}}}}],
            "P1128": [{"mainsnak": {"datavalue": {"value": {"amount": "+120"}}}}],
            "P159": [{"mainsnak": {"datavalue": {"value": {"id": "Q62"}}}}],
            "P169": [{"mainsnak": {"datavalue": {"value": {"id": "Q100"}}}}],
        }}},
    }))
    with HttpClient(rate_limit_rps=0) as client:
        link = WikidataResolver().resolve(_NAMED_COMPANY, MagicMock(), client)
    assert link["url"] == "https://www.wikidata.org/wiki/Q42"
    assert link["label"] == "Rad AI"
    assert link["inception"] == "2018-05-01"
    assert link["employees"] == "120"
    assert link["headquarters_qid"] == "Q62"
    assert link["ceo_qid"] == "Q100"
    assert link["confidence"] == "medium"


@pytest.mark.respx(base_url="https://www.wikidata.org")
def test_wikidata_resolver_none_when_no_hit(respx_mock):
    respx_mock.get("/w/api.php").mock(return_value=Response(200, json={"search": []}))
    with HttpClient(rate_limit_rps=0) as client:
        assert WikidataResolver().resolve(_NAMED_COMPANY, MagicMock(), client) is None


@pytest.mark.respx(base_url="https://api.opencorporates.com")
def test_opencorporates_resolver(respx_mock):
    respx_mock.get("/v0.4/companies/search").mock(return_value=Response(200, json={
        "results": {"companies": [{"company": {
            "name": "Rad AI Inc",
            "jurisdiction_code": "us_de",
            "incorporation_date": "2018-05-01",
            "opencorporates_url": "https://opencorporates.com/companies/us_de/123",
        }}]},
    }))
    with HttpClient(rate_limit_rps=0) as client:
        link = OpenCorporatesResolver().resolve(_NAMED_COMPANY, MagicMock(), client)
    assert link["kind"] == "company_registry"
    assert link["url"] == "https://opencorporates.com/companies/us_de/123"
    assert link["jurisdiction"] == "us_de"
    assert link["incorporation_date"] == "2018-05-01"


@pytest.mark.respx(base_url="https://api.opencorporates.com")
def test_opencorporates_resolver_none_when_no_match(respx_mock):
    respx_mock.get("/v0.4/companies/search").mock(
        return_value=Response(200, json={"results": {"companies": []}})
    )
    with HttpClient(rate_limit_rps=0) as client:
        assert OpenCorporatesResolver().resolve(_NAMED_COMPANY, MagicMock(), client) is None


@pytest.mark.respx(base_url="https://efts.sec.gov")
def test_sec_edgar_resolver_parses_form_d(respx_mock):
    respx_mock.get("/LATEST/search-index").mock(return_value=Response(200, json={
        "hits": {"hits": [
            {"_id": "0001234567-24-000123:primary_doc.xml",
             "_source": {"cik": ["1234567"], "file_date": "2024-03-01",
                         "display_names": ["Rad AI, Inc."], "form": "D"}},
        ]},
    }))
    with HttpClient(rate_limit_rps=0) as client:
        links = SecEdgarResolver().resolve(_NAMED_COMPANY, MagicMock(), client)
    assert len(links) == 1
    link = links[0]
    assert link["record_type"] == "form_d"
    assert link["kind"] == "form_d"
    assert link["url"] == (
        "https://www.sec.gov/Archives/edgar/data/1234567/"
        "000123456724000123/primary_doc.xml"
    )
    assert link["file_date"] == "2024-03-01"
    assert link["cik"] == "1234567"
    assert link["company_id"] == _NAMED_COMPANY["id"]


@pytest.mark.respx(base_url="https://efts.sec.gov")
def test_sec_edgar_resolver_empty(respx_mock):
    respx_mock.get("/LATEST/search-index").mock(return_value=Response(200, json={"hits": {"hits": []}}))
    with HttpClient(rate_limit_rps=0) as client:
        assert SecEdgarResolver().resolve(_NAMED_COMPANY, MagicMock(), client) == []


@pytest.mark.respx(base_url="https://api.www.sbir.gov")
def test_sbir_grants_resolver_parses_awards(respx_mock):
    respx_mock.get("/public/api/awards").mock(return_value=Response(200, json=[
        {"firm": "Rad AI", "award_title": "AI for radiology", "agency": "HHS",
         "amount": "150000", "award_year": 2023, "award_link": "https://www.sbir.gov/node/1"},
        {"firm": "Rad AI", "award_title": "Phase II", "agency": "HHS",
         "amount": "1000000", "award_year": 2024, "award_link": "https://www.sbir.gov/node/2"},
    ]))
    with HttpClient(rate_limit_rps=0) as client:
        links = SbirGrantsResolver().resolve(_NAMED_COMPANY, MagicMock(), client)
    assert [link["url"] for link in links] == [
        "https://www.sbir.gov/node/1", "https://www.sbir.gov/node/2",
    ]
    assert all(link["record_type"] == "grant" for link in links)
    assert links[0]["agency"] == "HHS"
    assert links[0]["amount"] == "150000"


@pytest.mark.respx(base_url="https://api.www.sbir.gov")
def test_sbir_grants_resolver_empty(respx_mock):
    respx_mock.get("/public/api/awards").mock(return_value=Response(200, json=[]))
    with HttpClient(rate_limit_rps=0) as client:
        assert SbirGrantsResolver().resolve(_NAMED_COMPANY, MagicMock(), client) == []


@pytest.mark.respx(base_url="https://api.gdeltproject.org")
def test_gdelt_funding_resolver_parses_articles(respx_mock):
    respx_mock.get("/api/v2/doc/doc").mock(return_value=Response(200, json={
        "articles": [
            {"url": "https://techcrunch.com/rad-ai-raises", "title": "Rad AI raises $50M",
             "seendate": "20240301T120000Z", "domain": "techcrunch.com"},
        ],
    }))
    with HttpClient(rate_limit_rps=0) as client:
        links = GdeltFundingResolver().resolve(_NAMED_COMPANY, MagicMock(), client)
    assert len(links) == 1
    link = links[0]
    assert link["record_type"] == "funding_announcement"
    assert link["url"] == "https://techcrunch.com/rad-ai-raises"
    assert link["title"] == "Rad AI raises $50M"
    assert link["seendate"] == "20240301T120000Z"


@pytest.mark.respx(base_url="https://api.gdeltproject.org")
def test_gdelt_funding_resolver_empty(respx_mock):
    respx_mock.get("/api/v2/doc/doc").mock(return_value=Response(200, json={"articles": []}))
    with HttpClient(rate_limit_rps=0) as client:
        assert GdeltFundingResolver().resolve(_NAMED_COMPANY, MagicMock(), client) == []


def test_run_enrichment_honours_per_link_record_type():
    store = MagicMock()
    client = MagicMock()
    company = {"domain": "radai.com", "id": "00000000-0000-0000-0000-000000000001"}

    class _TypedResolver:
        kind = "edgar"
        enabled = True

        def resolve(self, company, store, client):
            return {
                "company_id": company["id"],
                "kind": "edgar",
                "url": "https://sec.gov/x",
                "record_type": "form_d",
                "form": "D",
            }

    run_enrichment(company, store, client, resolvers=[_TypedResolver()])
    entry = store.upsert_research_record.call_args[0][0]
    assert entry.record_type == "form_d"
    # record_type drives the column, it is not duplicated into payload
    assert "record_type" not in entry.payload
    assert entry.payload["form"] == "D"


def test_run_enrichment_defaults_record_type_to_source_link():
    store = MagicMock()
    client = MagicMock()
    company = {"domain": "radai.com", "id": "00000000-0000-0000-0000-000000000001"}
    resolvers = [_FakeResolver("a", True, _link(company["id"], "a"))]
    run_enrichment(company, store, client, resolvers=resolvers)
    entry = store.upsert_research_record.call_args[0][0]
    assert entry.record_type == "source_link"


def test_run_enrichment_writes_each_link_from_list():
    store = MagicMock()
    client = MagicMock()
    company = {"domain": "radai.com", "id": "00000000-0000-0000-0000-000000000001"}

    class _MultiResolver:
        kind = "multi"
        enabled = True

        def resolve(self, company, store, client):
            return [
                {"company_id": company["id"], "kind": "multi", "url": "https://x/1", "title": "P1"},
                {"company_id": company["id"], "kind": "multi", "url": "https://x/2", "title": "P2"},
            ]

    written = run_enrichment(company, store, client, resolvers=[_MultiResolver()])
    assert [w["url"] for w in written] == ["https://x/1", "https://x/2"]
    assert store.upsert_research_record.call_count == 2
    # title falls through to the link's own title, not the kind
    first_entry = store.upsert_research_record.call_args_list[0][0][0]
    assert first_entry.title == "P1"
