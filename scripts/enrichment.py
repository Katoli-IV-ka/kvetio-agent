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


SEC_EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index"


class SecEdgarResolver:
    """SEC EDGAR full-text search for Form D filings — private-placement funding signal.

    Form D is the notice US companies file for an exempt securities offering (a raise).
    Name-search can mismatch, so the display name is kept in payload for the analyst.
    """

    kind = "form_d"
    enabled = True
    max_results = 5

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> list[dict]:
        name = _company_query_name(company)
        if not name:
            return []
        data = client.get_json(
            SEC_EDGAR_FTS,
            params={"q": f'"{name}"', "forms": "D"},
        )
        hits = (((data.get("hits") or {}).get("hits")) or []) if isinstance(data, dict) else []
        links: list[dict] = []
        for hit in hits[: self.max_results]:
            doc_id = hit.get("_id") or ""
            source = hit.get("_source") or {}
            accession, _, filename = doc_id.partition(":")
            cik_list = source.get("cik") or []
            cik = str(cik_list[0]) if cik_list else None
            if not accession or not cik:
                continue
            acc_nodash = accession.replace("-", "")
            url = (
                f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/"
                f"{filename or 'primary_doc.xml'}"
            )
            names = source.get("display_names") or []
            links.append({
                "company_id": company["id"],
                "kind": self.kind,
                "record_type": "form_d",
                "url": url,
                "source": "sec_edgar_resolver",
                "confidence": "medium",
                "title": names[0] if names else f"Form D — {name}",
                "file_date": source.get("file_date"),
                "cik": cik,
                "accession": accession,
            })
        return links


SBIR_AWARDS_API = "https://api.www.sbir.gov/public/api/awards"


class SbirGrantsResolver:
    """SBIR.gov awards — US government research grants (funding signal for the financials section)."""

    kind = "grant"
    enabled = True
    max_results = 5

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> list[dict]:
        name = _company_query_name(company)
        if not name:
            return []
        data = client.get_json(SBIR_AWARDS_API, params={"firm": name})
        awards = data if isinstance(data, list) else (data.get("results") or []) \
            if isinstance(data, dict) else []
        links: list[dict] = []
        for award in awards[: self.max_results]:
            if not isinstance(award, dict):
                continue
            url = award.get("award_link")
            if not url:
                continue
            links.append({
                "company_id": company["id"],
                "kind": self.kind,
                "record_type": "grant",
                "url": url,
                "source": "sbir_resolver",
                "confidence": "medium",
                "title": award.get("award_title"),
                "agency": award.get("agency"),
                "amount": award.get("amount"),
                "award_year": award.get("award_year"),
            })
        return links


GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"


class GdeltFundingResolver:
    """GDELT DOC API — recent funding-related news matching the company name.

    Name-match across global news is weak → low confidence; the analyst confirms the match.
    """

    kind = "gdelt_funding"
    enabled = True
    max_results = 5

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> list[dict]:
        name = _company_query_name(company)
        if not name:
            return []
        data = client.get_json(
            GDELT_DOC_API,
            params={
                "query": f'"{name}" (funding OR raises OR investment)',
                "mode": "artlist",
                "format": "json",
                "maxrecords": self.max_results,
                "sort": "datedesc",
            },
        )
        articles = (data.get("articles") or []) if isinstance(data, dict) else []
        links: list[dict] = []
        for art in articles[: self.max_results]:
            url = art.get("url")
            if not url:
                continue
            links.append({
                "company_id": company["id"],
                "kind": self.kind,
                "record_type": "funding_announcement",
                "url": url,
                "source": "gdelt_resolver",
                "confidence": "low",
                "title": " ".join((art.get("title") or "").split()),
                "seendate": art.get("seendate"),
                "domain": art.get("domain"),
            })
        return links


STOOQ_QUOTE_CSV = "https://stooq.com/q/l/"


def _ticker_from_records(company: dict, store: SupabaseStore) -> str | None:
    """Find a stock ticker in the company's stored research_records payloads.

    Tickers come from earlier resolvers (e.g. Wikidata P249) or manual enrichment;
    they live under payload['ticker']. No ticker → the company is treated as private.
    """
    for rec in store.get_research_records_for_company(company.get("domain") or ""):
        payload = rec.get("payload") or {}
        ticker = payload.get("ticker")
        if ticker:
            return str(ticker)
    return None


class MarketDataResolver:
    """Stooq public CSV quote for a listed company — optional market signal (financials).

    Only acts when a ticker is already known (public companies); otherwise no-op. The
    spec marks market data as optional (Phase 3), so this is safe to leave enabled.
    """

    kind = "market_data"
    enabled = True

    def resolve(self, company: dict, store: SupabaseStore, client: HttpClient) -> dict | None:
        ticker = _ticker_from_records(company, store)
        if not ticker:
            return None
        csv_text = client.get_text(
            STOOQ_QUOTE_CSV,
            params={"s": ticker, "f": "sd2t2ohlcv", "h": "", "e": "csv"},
        )
        lines = [ln for ln in csv_text.splitlines() if ln.strip()]
        if len(lines) < 2:
            return None
        header = [h.strip().lower() for h in lines[0].split(",")]
        row = lines[1].split(",")
        fields = dict(zip(header, [c.strip() for c in row]))
        close = fields.get("close")
        if not close or close in {"N/D", "0"}:
            return None
        return {
            "company_id": company["id"],
            "kind": self.kind,
            "record_type": "market_quote",
            "url": f"https://stooq.com/q/?s={ticker}",
            "source": "stooq_resolver",
            "confidence": "medium",
            "ticker": ticker,
            "close": close,
            "quote_date": fields.get("date"),
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
    SecEdgarResolver(),
    SbirGrantsResolver(),
    GdeltFundingResolver(),
    MarketDataResolver(),
    LINKEDIN_STUB,
    CRUNCHBASE_STUB,
    SIMILARWEB_STUB,
]


def _headcount_to_size(n: int) -> str:
    """Map raw headcount to a canonical company_size label."""
    if n <= 10:
        return "1-10"
    if n <= 50:
        return "11-50"
    if n <= 200:
        return "51-200"
    if n <= 500:
        return "201-500"
    if n <= 1000:
        return "501-1000"
    return "1000+"


def _jurisdiction_to_country(jurisdiction: str) -> str:
    """'us_de' → 'US', 'gb' → 'GB'. Uses prefix before first underscore."""
    return jurisdiction.split("_")[0].upper()


class FirmographicsExtractor:
    """Reads Wikidata / OpenCorporates payloads already stored as research_records
    and extracts firmographic facts (country, founded_year, company_size).

    Does NOT make network calls — all data is already in the DB from prior resolvers.
    """

    def extract(self, company: dict, store) -> dict:
        """Return dict of firmographic updates for patch_company. Empty dict if nothing found."""
        updates: dict = {}
        for rec in store.get_research_records_for_company(company.get("domain") or ""):
            source = rec.get("source") or ""
            payload = rec.get("payload") or {}

            if "wikidata" in source:
                if not updates.get("founded_year"):
                    inception = payload.get("inception")  # e.g. "2015-03-01"
                    if inception:
                        try:
                            updates["founded_year"] = int(str(inception)[:4])
                        except (ValueError, TypeError):
                            pass

                if not updates.get("company_size"):
                    raw = payload.get("employees")  # e.g. "+120" or "120"
                    if raw:
                        try:
                            n = int(str(raw).lstrip("+").split(".")[0])
                            updates["company_size"] = _headcount_to_size(n)
                        except (ValueError, TypeError):
                            pass

            if "opencorporates" in source:
                if not updates.get("country"):
                    jurisdiction = payload.get("jurisdiction")
                    if jurisdiction:
                        updates["country"] = _jurisdiction_to_country(jurisdiction)

        return updates


def run_firmographics(company: dict, store) -> dict:
    """Extract firmographic fields from existing research_records and patch companies table.

    Call after run_enrichment so Wikidata/OpenCorporates records are already written.
    Returns the dict of fields written (empty dict if nothing found).
    """
    updates = FirmographicsExtractor().extract(company, store)
    if updates:
        store.patch_company(company["domain"], updates)
        logger.info(
            "firmographics %s: %s", company.get("domain"), sorted(updates.keys())
        )
    return updates


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
