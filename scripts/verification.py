"""Этап Verification (Phase 2): гейт качества перед досье.

Детерминированно проверяет research_records:
- свежесть (пороги в config/verification.yaml);
- живость ссылки (HEAD; 404 / только-Wayback → не живая).
Помечает каждую запись `verified` / `unverified` / `stale` в payload.verification.

Мягкая интерпретация (конфликты claim↔fact) остаётся за verification_task.md / агентом.

CLI:
    python scripts/verification.py --domain radai.com
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent))
from http_client import HttpClient
from supabase_store import SupabaseStore

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent / "config" / "verification.yaml"

VerificationStatus = str  # "verified" | "unverified" | "stale"


def load_thresholds(path: Path | None = None) -> dict:
    """Flatten config/verification.yaml into a single thresholds dict."""
    raw = yaml.safe_load((path or _CONFIG_PATH).read_text(encoding="utf-8")) or {}
    freshness = raw.get("freshness") or {}
    return {
        "news_event_months": freshness.get("news_event_months", 12),
        "news_priority_months": freshness.get("news_priority_months", 6),
        "funding_signal_months": freshness.get("funding_signal_months", 18),
        "financial_record_types": raw.get("financial_record_types") or [],
    }


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)


def classify_freshness(
    record_type: str, observed_at: date, thresholds: dict, today: date
) -> str:
    """Return 'fresh' or 'stale' based on record age and per-type thresholds.

    Financial signals stale after funding_signal_months; news after news_event_months;
    everything else is never stale on age alone.
    """
    age = _months_between(observed_at, today)
    if record_type in set(thresholds.get("financial_record_types") or []):
        return "stale" if age > thresholds["funding_signal_months"] else "fresh"
    if record_type == "news":
        return "stale" if age > thresholds["news_event_months"] else "fresh"
    return "fresh"


def link_status(url: str, client: HttpClient) -> str:
    """Return 'live' or 'dead' for a URL.

    Dead when: it only survives on web.archive.org, it 404s, or it is unreachable.
    Redirect-to-root is left to the agent (needs original-vs-final comparison).
    """
    if not url:
        return "dead"
    if "web.archive.org" in url:
        return "dead"
    status = client.head_status(url)
    if status == 0 or status == 404 or status >= 500:
        return "dead"
    return "live"


def verify_record(
    record: dict, client: HttpClient, thresholds: dict, today: date
) -> str:
    """Classify one research_record as verified / unverified / stale."""
    observed_raw = str(record.get("observed_at") or "")[:10]
    try:
        observed = date.fromisoformat(observed_raw)
    except ValueError:
        observed = today
    freshness = classify_freshness(
        record.get("record_type") or "", observed, thresholds, today
    )
    if freshness == "stale":
        return "stale"
    return "verified" if link_status(record.get("url") or "", client) == "live" else "unverified"


def run_verification(
    records: list[dict],
    store: SupabaseStore,
    client: HttpClient,
    *,
    today: date | None = None,
    thresholds: dict | None = None,
) -> list[tuple[str, str]]:
    """Verify each record, persist status, and return [(record_id, status)]."""
    today = today or date.today()
    thresholds = thresholds or load_thresholds()
    results: list[tuple[str, str]] = []
    for record in records:
        rid = record.get("id")
        if not rid:
            continue
        status = verify_record(record, client, thresholds, today)
        store.set_record_verification(rid, status)
        results.append((rid, status))
    return results


def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", required=True)
    args = parser.parse_args()

    store = SupabaseStore()
    records = store.get_research_records_for_company(args.domain)
    with HttpClient(rate_limit_rps=2.0) as client:
        results = run_verification(records, store, client)
    counts: dict[str, int] = {}
    for _, status in results:
        counts[status] = counts.get(status, 0) + 1
    print(json.dumps({"domain": args.domain, "counts": counts}, indent=2))


if __name__ == "__main__":
    _main()
