"""Этап 3 (Enrichment): резолверы ссылок-источников -> research_records.

Детерминированные HTTP-резолверы. MCP/WebSearch-ручки (HF org, новости, соцсети)
собирает EnrichmentAgent в промпте и пишет как source research records.

CLI:
    python scripts/enrichment.py --domain radai.com
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

sys.path.insert(0, str(Path(__file__).parent))
from dm_github import extract_org_login
from http_client import HttpClient
from models import ResearchRecord
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)


class Resolver(Protocol):
    kind: str
    enabled: bool

    def resolve(
        self, company: dict, store: SupabaseStore, client: HttpClient
    ) -> dict | list[dict] | None:
        ...


class _DisabledStub:
    """Стаб платного источника. Реализовать resolve() и enabled=True при подключении."""

    enabled = False

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> dict | None:
        return None


class GithubOrgResolver:
    """Ссылка на GitHub-организацию из уже собранных сигналов компании."""

    kind = "github_org"
    enabled = True

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> dict | None:
        for sig in store.get_research_records_for_company(company["domain"]):
            url = sig.get("url") or ""
            login = extract_org_login(url)
            if login:
                return {
                    "company_id": company["id"],
                    "kind": self.kind,
                    "url": f"https://github.com/{login}",
                    "source": "github_org_resolver",
                    "confidence": "high",
                }
        return None


WAYBACK_API = "http://archive.org/wayback/available"


class WaybackResolver:
    """Ближайший снапшот сайта в Wayback Machine — для динамики позиционирования."""

    kind = "wayback"
    enabled = True

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> dict | None:
        data = client.get_json(f"{WAYBACK_API}?url={company['domain']}")
        closest = (data.get("archived_snapshots") or {}).get("closest") or {}
        url = closest.get("url")
        if not url:
            return None
        return {
            "company_id": company["id"],
            "kind": self.kind,
            "url": url,
            "source": "wayback_resolver",
            "confidence": "high",
        }


ARXIV_API = "http://export.arxiv.org/api/query"
_ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def _company_query_name(company: dict) -> str:
    """Best display name for external search. Falls back to the bare domain."""
    name = (company.get("name") or "").strip()
    if name:
        return name
    domain = (company.get("domain") or "").strip()
    return domain.split(".")[0] if domain else ""


class ArxivResolver:
    """Recent arXiv papers matching the company name — R&D / tech signal for the product section.

    Name-matching is weak (arXiv has no affiliation index), so confidence is low and the
    paper title + authors are kept in payload for the analyst to verify the match.
    """

    kind = "arxiv"
    enabled = True
    max_results = 5

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> list[dict]:
        name = _company_query_name(company)
        if not name:
            return []
        xml_text = client.get_text(
            ARXIV_API,
            params={
                "search_query": f'all:"{name}"',
                "start": 0,
                "max_results": self.max_results,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
            },
        )
        if not xml_text.strip():
            return []
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            return []
        links: list[dict] = []
        for entry in root.findall("atom:entry", _ATOM_NS):
            url = (entry.findtext("atom:id", default="", namespaces=_ATOM_NS) or "").strip()
            if not url:
                continue
            title = " ".join(
                (entry.findtext("atom:title", default="", namespaces=_ATOM_NS) or "").split()
            )
            published = entry.findtext("atom:published", default="", namespaces=_ATOM_NS)
            authors = [
                (a.findtext("atom:name", default="", namespaces=_ATOM_NS) or "").strip()
                for a in entry.findall("atom:author", _ATOM_NS)
            ]
            links.append({
                "company_id": company["id"],
                "kind": self.kind,
                "url": url,
                "source": "arxiv_resolver",
                "confidence": "low",
                "title": title,
                "published": (published or "")[:10],
                "authors": [a for a in authors if a][:6],
            })
        return links


PWC_SEARCH_API = "https://paperswithcode.com/api/v1/search/"


class PapersWithCodeResolver:
    """Papers with Code search hits — implementation-backed research signal for the product section."""

    kind = "papers_with_code"
    enabled = True
    max_results = 5

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> list[dict]:
        name = _company_query_name(company)
        if not name:
            return []
        data = client.get_json(PWC_SEARCH_API, params={"q": name, "items_per_page": self.max_results})
        results = data.get("results") if isinstance(data, dict) else None
        if not results:
            return []
        links: list[dict] = []
        for item in results:
            paper = (item.get("paper") or item) if isinstance(item, dict) else {}
            url = paper.get("url_abs") or paper.get("url_pdf")
            paper_id = paper.get("id")
            if not url and paper_id:
                url = f"https://paperswithcode.com/paper/{paper_id}"
            if not url:
                continue
            links.append({
                "company_id": company["id"],
                "kind": self.kind,
                "url": url,
                "source": "paperswithcode_resolver",
                "confidence": "low",
                "title": " ".join((paper.get("title") or "").split()),
            })
        return links


WIKIDATA_API = "https://www.wikidata.org/w/api.php"
WIKIDATA_ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"


def _wd_value(claims: dict, prop: str):
    arr = claims.get(prop) or []
    if not arr:
        return None
    return ((arr[0].get("mainsnak") or {}).get("datavalue") or {}).get("value")


class WikidataResolver:
    """Wikidata entity for the company — founding date, HQ, leadership, headcount (company section).

    Picks the top search hit; the label/description are kept in payload so the analyst can
    confirm the entity actually matches the company.
    """

    kind = "wikidata"
    enabled = True

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> dict | None:
        name = _company_query_name(company)
        if not name:
            return None
        search = client.get_json(
            WIKIDATA_API,
            params={
                "action": "wbsearchentities",
                "search": name,
                "language": "en",
                "format": "json",
                "type": "item",
                "limit": 1,
            },
        )
        hits = search.get("search") if isinstance(search, dict) else None
        if not hits:
            return None
        hit = hits[0]
        qid = hit.get("id")
        if not qid:
            return None

        payload = {
            "kind": self.kind,
            "label": hit.get("label"),
            "description": hit.get("description"),
        }
        entity = client.get_json(WIKIDATA_ENTITY.format(qid=qid))
        claims = (((entity.get("entities") or {}).get(qid) or {}).get("claims") or {}) \
            if isinstance(entity, dict) else {}

        inception = _wd_value(claims, "P571")
        if isinstance(inception, dict) and inception.get("time"):
            payload["inception"] = inception["time"].lstrip("+")[:10]
        employees = _wd_value(claims, "P1128")
        if isinstance(employees, dict) and employees.get("amount"):
            payload["employees"] = employees["amount"].lstrip("+")
        hq = _wd_value(claims, "P159")
        if isinstance(hq, dict) and hq.get("id"):
            payload["headquarters_qid"] = hq["id"]
        ceo = _wd_value(claims, "P169")
        if isinstance(ceo, dict) and ceo.get("id"):
            payload["ceo_qid"] = ceo["id"]

        return {
            "company_id": company["id"],
            "url": f"https://www.wikidata.org/wiki/{qid}",
            "source": "wikidata_resolver",
            "confidence": "medium",
            **payload,
        }


OPENCORPORATES_API = "https://api.opencorporates.com/v0.4/companies/search"


class OpenCorporatesResolver:
    """OpenCorporates registry match — legal entity, jurisdiction, incorporation date (company section).

    Best-effort: the free endpoint is rate-limited and may reject anonymous calls; run_enrichment
    swallows failures so the stage keeps going. Confidence is low — name search can mismatch.
    """

    kind = "company_registry"
    enabled = True

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> dict | None:
        name = _company_query_name(company)
        if not name:
            return None
        data = client.get_json(OPENCORPORATES_API, params={"q": name, "format": "json"})
        companies = (((data.get("results") or {}).get("companies")) or []) \
            if isinstance(data, dict) else []
        if not companies:
            return None
        match = (companies[0] or {}).get("company") or {}
        url = match.get("opencorporates_url")
        if not url:
            return None
        return {
            "company_id": company["id"],
            "kind": self.kind,
            "url": url,
            "source": "opencorporates_resolver",
            "confidence": "low",
            "legal_name": match.get("name"),
            "jurisdiction": match.get("jurisdiction_code"),
            "incorporation_date": match.get("incorporation_date"),
        }


# Стабы платных источников (tier C). Зарегистрированы, но выключены.
LINKEDIN_STUB = _DisabledStub("linkedin")
CRUNCHBASE_STUB = _DisabledStub("crunchbase")
SIMILARWEB_STUB = _DisabledStub("similarweb")


def run_enrichment(
    company: dict,
    store: SupabaseStore,
    client: HttpClient,
    resolvers: list[Resolver] | None = None,
) -> list[dict]:
    """Run enabled resolvers and write found source URLs as research_records."""
    active = resolvers if resolvers is not None else RESOLVERS
    written: list[dict] = []
    for r in active:
        if not getattr(r, "enabled", False):
            continue
        try:
            result = r.resolve(company, store, client)
        except Exception as exc:  # noqa: BLE001 — резолвер не должен ронять этап
            logger.warning("resolver %s failed: %s", getattr(r, "kind", "?"), exc)
            continue
        # A resolver may return a single link, a list of links, or nothing.
        links = result if isinstance(result, list) else [result]
        for link in links:
            if not link:
                continue
            payload = {
                k: v for k, v in link.items()
                if k not in {"company_id", "source", "url", "confidence", "record_type"}
            }
            payload.setdefault("fetched_at", datetime.utcnow().isoformat())
            entry = ResearchRecord(
                source=link.get("source", "unknown"),
                record_type=link.get("record_type", "source_link"),
                company_name=company.get("name") or company["domain"],
                domain=company.get("domain"),
                linkedin_url=company.get("linkedin_url"),
                url=link["url"],
                observed_at=date.today(),
                confidence=link.get("confidence", "medium"),
                record_role="source",
                agent="enrichment",
                title=link.get("title") or link.get("kind"),
                payload=payload,
            )
            store.upsert_research_record(entry, domain=company["domain"])
            written.append(link)
    return written


RESOLVERS: list[Resolver] = [
    GithubOrgResolver(),
    WaybackResolver(),
    ArxivResolver(),
    PapersWithCodeResolver(),
    WikidataResolver(),
    OpenCorporatesResolver(),
    LINKEDIN_STUB,
    CRUNCHBASE_STUB,
    SIMILARWEB_STUB,
]


def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    store = SupabaseStore()
    company = store.get_company(args.domain)
    if not company:
        print(json.dumps({"error": "company not found", "domain": args.domain}))
        return
    with HttpClient(rate_limit_rps=1.0) as client:
        written = run_enrichment(company, store, client)
    print(json.dumps({"domain": args.domain, "written": written}, indent=2))


if __name__ == "__main__":
    _main()
