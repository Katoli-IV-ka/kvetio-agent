"""NewsAgent deterministic core — fetch, classify, dedup, write news signals.

Free/public news sources only: GDELT DOC 2.0, Google News RSS, Hacker News
(Algolia), and a curated RSS set. The LLM agent (`agents/prompts/news_task.md`)
drives entity resolution and the rough ICP gate; this module provides the
deterministic plumbing it calls through Bash, modelled on `enrichment.py`.

Two flows:
  * monitoring — news about a company already in the DB (record_role='monitor');
    a strong signal on a dossier_ready company flags `needs_refresh`.
  * discovery  — segment-level candidate scan; prints classified candidates for
    the agent to resolve + gate (never writes companies or fires the pipeline).

CLI:
    python scripts/news.py --domain radai.com            # monitor a known company
    python scripts/news.py --segment medical-imaging     # discovery candidate scan
    python scripts/news.py --domain radai.com --dry-run  # classify, write nothing
    python scripts/news.py --domain radai.com --allow-refresh  # may set needs_refresh
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from http_client import HttpClient
from models import ResearchRecord
from normalize import normalize_domain
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config" / "news_sources.yaml"

# ── Signal taxonomy ───────────────────────────────────────────────────────────
# Strong signals → auto-fire candidate (after the agent's ICP gate).
# Soft signals → research_record only, no full pipeline run.
STRONG_EVENTS: frozenset[str] = frozenset(
    {"funding_round", "model_launch", "stealth_exit", "data_need", "hiring_surge"}
)
SOFT_EVENTS: frozenset[str] = frozenset(
    {"partnership", "product_update", "pr_mention", "leadership_change", "negative"}
)
ALL_EVENTS: frozenset[str] = STRONG_EVENTS | SOFT_EVENTS

# Deterministic keyword → event_type map. Order matters: the first matching
# event_type wins, so strong signals are listed before soft ones. The LLM agent
# may override this baseline when context is richer.
_SIGNAL_TERMS: list[tuple[str, str]] = [
    # strong
    ("raises", "funding_round"),
    ("raised", "funding_round"),
    ("series a", "funding_round"),
    ("series b", "funding_round"),
    ("series c", "funding_round"),
    ("seed round", "funding_round"),
    ("seed funding", "funding_round"),
    ("funding round", "funding_round"),
    ("secures", "funding_round"),
    ("closes round", "funding_round"),
    ("out of stealth", "stealth_exit"),
    ("emerges from stealth", "stealth_exit"),
    ("launches new model", "model_launch"),
    ("unveils model", "model_launch"),
    ("announces model", "model_launch"),
    ("training a", "model_launch"),
    ("foundation model", "model_launch"),
    ("building a dataset", "data_need"),
    ("building dataset", "data_need"),
    ("needs data", "data_need"),
    ("data annotation", "data_need"),
    ("labeling data", "data_need"),
    ("hiring", "hiring_surge"),
    ("expands team", "hiring_surge"),
    ("ml engineers", "hiring_surge"),
    # soft
    ("partners with", "partnership"),
    ("partnership", "partnership"),
    ("collaborates", "partnership"),
    ("appoints", "leadership_change"),
    ("names new", "leadership_change"),
    ("joins as", "leadership_change"),
    ("new ceo", "leadership_change"),
    ("new cto", "leadership_change"),
    ("layoffs", "negative"),
    ("lays off", "negative"),
    ("pivots", "negative"),
    ("shuts down", "negative"),
    ("launches", "product_update"),
    ("releases", "product_update"),
    ("introduces", "product_update"),
    ("update", "product_update"),
    ("award", "pr_mention"),
    ("recognized", "pr_mention"),
    ("named to", "pr_mention"),
]


def classify_event(text: str) -> tuple[str | None, str | None]:
    """Map free text to (event_type, signal_class) using keyword baseline.

    Returns (None, None) when nothing matches. signal_class is 'strong' or 'soft'
    derived from STRONG_EVENTS membership.
    """
    if not text:
        return None, None
    lowered = text.lower()
    for term, event_type in _SIGNAL_TERMS:
        if term in lowered:
            cls = "strong" if event_type in STRONG_EVENTS else "soft"
            return event_type, cls
    return None, None


def signal_class_for(event_type: str) -> str:
    """Return 'strong' or 'soft' for a known event_type ('soft' for unknown)."""
    return "strong" if event_type in STRONG_EVENTS else "soft"


# ── Entity resolution / dedup ────────────────────────────────────────────────


def resolve_company_domain(url_or_domain: str | None) -> str | None:
    """Resolve a company homepage/URL to a normalized registered domain.

    Returns None when the input is empty or cannot be normalized. We only act on
    a resolvable domain — an event without one is at most a weak lead in a note.
    """
    if not url_or_domain or not url_or_domain.strip():
        return None
    try:
        return normalize_domain(url_or_domain)
    except ValueError:
        return None


def _date_bucket(event_date: str | None) -> str:
    """ISO year-week bucket for an event date, collapsing multi-edition coverage.

    Falls back to 'unknown' for unparseable/empty dates so the key stays stable.
    """
    if not event_date:
        return "unknown"
    try:
        d = datetime.fromisoformat(event_date[:10]).date()
    except ValueError:
        return "unknown"
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def make_dedupe_key(domain: str, event_type: str, event_date: str | None) -> str:
    """sha1(domain | event_type | date_bucket) — one info-event = one row.

    Deterministic, so repeated runs are idempotent and one event from many
    outlets collapses into a single research_record.
    """
    basis = f"{domain}|{event_type}|{_date_bucket(event_date)}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


# ── Article model + fetchers ─────────────────────────────────────────────────


@dataclass(frozen=True)
class Article:
    """One normalized news item from any source."""

    title: str
    url: str
    source: str                 # 'gdelt' | 'google_news' | 'hn' | 'rss'
    published: str = ""         # YYYY-MM-DD when known
    publisher_domain: str = ""  # outlet domain (not the company)
    snippet: str = ""

    @property
    def text(self) -> str:
        return f"{self.title} {self.snippet}".strip()


GDELT_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
HN_ALGOLIA_API = "https://hn.algolia.com/api/v1/search"


def _gdelt_date(seendate: str | None) -> str:
    """GDELT seendate 'YYYYMMDDTHHMMSSZ' -> 'YYYY-MM-DD'."""
    if not seendate or len(seendate) < 8:
        return ""
    return f"{seendate[0:4]}-{seendate[4:6]}-{seendate[6:8]}"


def fetch_gdelt(client: HttpClient, query: str, *, max_records: int = 20) -> list[Article]:
    """Query the GDELT DOC 2.0 artlist for recent articles matching `query`."""
    data = client.get_json(
        GDELT_DOC_API,
        params={
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": max_records,
            "sort": "datedesc",
        },
    )
    articles = (data.get("articles") or []) if isinstance(data, dict) else []
    out: list[Article] = []
    for art in articles[:max_records]:
        url = art.get("url")
        if not url:
            continue
        out.append(Article(
            title=" ".join((art.get("title") or "").split()),
            url=url,
            source="gdelt",
            published=_gdelt_date(art.get("seendate")),
            publisher_domain=art.get("domain") or "",
        ))
    return out


def _rss_items(xml_text: str) -> list[dict]:
    """Parse RSS 2.0 / Atom into a list of {title,link,pubDate,description}."""
    if not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    items: list[dict] = []
    # RSS 2.0: channel/item
    for item in root.iter("item"):
        link_el = item.find("link")
        items.append({
            "title": (item.findtext("title") or "").strip(),
            "link": (link_el.text or "").strip() if link_el is not None else "",
            "pubDate": (item.findtext("pubDate") or "").strip(),
            "description": (item.findtext("description") or "").strip(),
        })
    if items:
        return items
    # Atom fallback: entry
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("a:entry", ns):
        link_el = entry.find("a:link", ns)
        items.append({
            "title": (entry.findtext("a:title", default="", namespaces=ns) or "").strip(),
            "link": (link_el.get("href") if link_el is not None else "") or "",
            "pubDate": (entry.findtext("a:updated", default="", namespaces=ns) or "").strip(),
            "description": (entry.findtext("a:summary", default="", namespaces=ns) or "").strip(),
        })
    return items


def _parse_rfc822(value: str) -> str:
    """RFC-822 / ISO date string -> 'YYYY-MM-DD' (best effort, '' on failure)."""
    if not value:
        return ""
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(value[:10]).date().isoformat()
    except ValueError:
        return ""


def fetch_google_news(client: HttpClient, query: str, *, max_records: int = 20) -> list[Article]:
    """Query Google News RSS for `query` (keyword or company name/domain)."""
    xml_text = client.get_text(
        GOOGLE_NEWS_RSS,
        params={"q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"},
    )
    out: list[Article] = []
    for item in _rss_items(xml_text)[:max_records]:
        if not item["link"]:
            continue
        out.append(Article(
            title=" ".join(item["title"].split()),
            url=item["link"],
            source="google_news",
            published=_parse_rfc822(item["pubDate"]),
            snippet=" ".join(item["description"].split())[:500],
        ))
    return out


def fetch_hn(client: HttpClient, query: str, *, max_records: int = 20) -> list[Article]:
    """Query Hacker News (Algolia) stories — Show HN / model & product launches."""
    data = client.get_json(
        HN_ALGOLIA_API,
        params={"query": query, "tags": "story", "hitsPerPage": max_records},
    )
    hits = (data.get("hits") or []) if isinstance(data, dict) else []
    out: list[Article] = []
    for hit in hits[:max_records]:
        object_id = hit.get("objectID")
        url = hit.get("url") or (
            f"https://news.ycombinator.com/item?id={object_id}" if object_id else None
        )
        if not url:
            continue
        published = ""
        created = hit.get("created_at")
        if created:
            published = _parse_rfc822(created)
        out.append(Article(
            title=" ".join((hit.get("title") or "").split()),
            url=url,
            source="hn",
            published=published,
            snippet=" ".join((hit.get("story_text") or "").split())[:500],
        ))
    return out


def fetch_rss(client: HttpClient, feed_url: str) -> list[Article]:
    """Fetch a curated RSS/Atom feed and normalize its items."""
    xml_text = client.get_text(feed_url)
    out: list[Article] = []
    for item in _rss_items(xml_text):
        if not item["link"]:
            continue
        out.append(Article(
            title=" ".join(item["title"].split()),
            url=item["link"],
            source="rss",
            published=_parse_rfc822(item["pubDate"]),
            publisher_domain=resolve_company_domain(item["link"]) or "",
            snippet=" ".join(item["description"].split())[:500],
        ))
    return out


# ── Config ───────────────────────────────────────────────────────────────────


def load_config(path: Path = CONFIG_PATH) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def segment_queries(config: dict, segment: str) -> list[str]:
    """Per-segment discovery queries from news_sources.yaml (explicit or derived)."""
    seg_cfg = (config.get("segments") or {}).get(segment) or {}
    explicit = seg_cfg.get("queries")
    if explicit:
        return list(explicit)
    keywords = seg_cfg.get("keywords") or []
    signal_terms = config.get("signal_terms") or []
    return [f'"{kw}" {term}' for kw in keywords for term in signal_terms]


# ── Record building / writing ────────────────────────────────────────────────


def build_news_record(
    company: dict,
    article: Article,
    event_type: str,
    signal_class: str,
    *,
    record_role: str,
    alt_urls: list[str] | None = None,
    confidence: float = 0.50,
) -> ResearchRecord:
    """Assemble a `news` research_record with taxonomy encoded in payload."""
    domain = company["domain"]
    payload = {
        "signal_class": signal_class,
        "event_type": event_type,
        "event_date": article.published or None,
        "headline": article.title,
        "alt_urls": alt_urls or [],
    }
    return ResearchRecord(
        source=article.source,
        record_type="news",
        company_name=company.get("name") or domain,
        domain=domain,
        linkedin_url=company.get("linkedin_url"),
        url=article.url,
        observed_at=date.today(),
        confidence=confidence,
        record_role=record_role,
        agent="news",
        title=article.title,
        summary=article.snippet or None,
        payload=payload,
    )


def monitor_company(
    company: dict,
    store: SupabaseStore,
    client: HttpClient,
    *,
    max_per_source: int = 10,
    record_role: str = "monitor",
    dry_run: bool = False,
    allow_refresh: bool = False,
    run_id: str | None = None,
) -> list[dict]:
    """News-monitoring flow for a company already in the DB.

    Fetches Google News + GDELT by name/domain, classifies + dedups by event,
    writes `news` research_records, and (when `allow_refresh`) flags
    `needs_refresh` on a dossier_ready company that got a strong signal.
    Returns one summary dict per deduplicated event.
    """
    name = company.get("name") or company["domain"]
    query = f'"{name}"'
    articles = (
        fetch_google_news(client, query, max_records=max_per_source)
        + fetch_gdelt(client, query, max_records=max_per_source)
    )

    by_key: dict[str, dict] = {}
    for art in articles:
        event_type, signal_class = classify_event(art.text)
        if not event_type:
            continue
        key = make_dedupe_key(company["domain"], event_type, art.published)
        existing = by_key.get(key)
        if existing is not None:
            # Same event from another outlet → keep as alt_url, do not duplicate.
            if art.url not in existing["alt_urls"] and art.url != existing["article"].url:
                existing["alt_urls"].append(art.url)
            continue
        by_key[key] = {
            "key": key,
            "article": art,
            "event_type": event_type,
            "signal_class": signal_class,
            "alt_urls": [],
        }

    results: list[dict] = []
    strong_found = False
    for ev in by_key.values():
        art: Article = ev["article"]
        if ev["signal_class"] == "strong":
            strong_found = True
        if not dry_run:
            entry = build_news_record(
                company, art, ev["event_type"], ev["signal_class"],
                record_role=record_role, alt_urls=ev["alt_urls"],
            )
            store.upsert_research_record(
                entry, domain=company["domain"], run_id=run_id, dedupe_key=ev["key"],
            )
        results.append({
            "domain": company["domain"],
            "event_type": ev["event_type"],
            "signal_class": ev["signal_class"],
            "title": art.title,
            "url": art.url,
            "event_date": art.published,
            "alt_urls": ev["alt_urls"],
            "dedupe_key": ev["key"],
        })

    if strong_found and allow_refresh and not dry_run:
        if company.get("status") == "dossier_ready":
            store.set_needs_refresh(company["domain"])

    return results


def scan_segment(
    config: dict,
    segment: str,
    client: HttpClient,
    *,
    max_per_query: int = 10,
) -> list[dict]:
    """Discovery candidate scan for a segment — classify, do NOT write.

    Returns classified candidate events for the agent to resolve to a domain and
    pass through the ICP gate. Never creates companies or fires the pipeline.
    """
    candidates: list[dict] = []
    seen: set[str] = set()
    for query in segment_queries(config, segment):
        for art in fetch_google_news(client, query, max_records=max_per_query):
            event_type, signal_class = classify_event(art.text)
            if not event_type:
                continue
            if art.url in seen:
                continue
            seen.add(art.url)
            candidates.append({
                "segment": segment,
                "query": query,
                "event_type": event_type,
                "signal_class": signal_class,
                "title": art.title,
                "url": art.url,
                "publisher_domain": art.publisher_domain,
                "event_date": art.published,
                "source": art.source,
            })
    return candidates


def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="NewsAgent deterministic core")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--domain", help="Monitor a known company by domain")
    group.add_argument("--segment", help="Discovery candidate scan for an ICP segment")
    parser.add_argument("--dry-run", action="store_true",
                        help="Classify but write nothing to Supabase")
    parser.add_argument("--allow-refresh", action="store_true",
                        help="Allow flagging needs_refresh on strong signals (monitoring)")
    args = parser.parse_args()

    config = load_config()

    if args.segment:
        # Discovery scan never writes; safe without DB.
        with HttpClient(rate_limit_rps=1.0) as client:
            candidates = scan_segment(config, args.segment, client)
        print(json.dumps({"segment": args.segment, "candidates": candidates}, indent=2))
        return

    store = SupabaseStore()
    company = store.get_company(args.domain)
    if not company:
        print(json.dumps({"error": "company not found", "domain": args.domain}))
        return
    with HttpClient(rate_limit_rps=1.0) as client:
        results = monitor_company(
            company, store, client,
            dry_run=args.dry_run, allow_refresh=args.allow_refresh,
        )
    print(json.dumps({"domain": args.domain, "events": results}, indent=2))


if __name__ == "__main__":
    _main()
