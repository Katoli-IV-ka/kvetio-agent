"""Telegram routines for Kvetio operations.

CLI:
    python scripts/telegram_routines.py daily_digest --dry-run
    python scripts/telegram_routines.py hot_leads --limit 5
    python scripts/telegram_routines.py stale_review --days 30
"""

from __future__ import annotations

import argparse
import html
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, Protocol


class RoutineStore(Protocol):
    def stats(self) -> dict:
        ...

    def coverage_by_segment(self) -> dict[str, dict[str, int]]:
        ...

    def list_hot_leads(self, limit: int = 5) -> list[dict]:
        ...

    def list_stale_review_queue(self, days: int = 14, limit: int = 10) -> list[dict]:
        ...


SendMessage = Callable[[str], object]


@dataclass(frozen=True)
class RoutineResult:
    name: str
    message: str
    payload: dict[str, Any]
    sent: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_routine(
    name: str,
    *,
    store: RoutineStore,
    send_message: SendMessage | None = None,
    dry_run: bool = False,
    limit: int = 5,
    days: int = 14,
) -> RoutineResult:
    """Build and optionally send a Telegram routine message."""
    if name == "daily_digest":
        result = _daily_digest(store)
    elif name == "hot_leads":
        result = _hot_leads(store, limit=limit)
    elif name == "stale_review":
        result = _stale_review(store, days=days, limit=limit)
    else:
        raise ValueError(f"Unknown Telegram routine: {name}")

    if dry_run:
        return result

    sender = send_message or _default_sender()
    send_result = sender(result.message)
    return RoutineResult(
        name=result.name,
        message=result.message,
        payload=result.payload,
        sent=send_result is not False,
    )


def _daily_digest(store: RoutineStore) -> RoutineResult:
    stats = store.stats()
    coverage = store.coverage_by_segment()
    by_status = stats.get("by_status") or {}

    lines = [
        "📊 <b>Daily digest</b>",
        f"Total companies: <b>{int(stats.get('total') or 0)}</b>",
        "",
        "<b>Status</b>",
        *_format_count_lines(by_status),
        "",
        "<b>Segments</b>",
        *_format_segment_lines(coverage),
    ]
    return RoutineResult(
        name="daily_digest",
        message="\n".join(lines).strip(),
        payload={"stats": stats, "coverage": coverage},
    )


def _hot_leads(store: RoutineStore, *, limit: int) -> RoutineResult:
    leads = store.list_hot_leads(limit=limit)
    lines = ["🔥 <b>Hot leads</b>"]
    if not leads:
        lines.append("No hot leads found.")
    for idx, lead in enumerate(leads, start=1):
        name = _escape(lead.get("name") or "Unknown")
        domain = _escape(lead.get("domain") or "")
        segment = lead.get("icp_segment") or "unknown"
        status = lead.get("status") or "unknown"
        lines.append(f"{idx}. <b>{name}</b> — {domain}")
        lines.append(f"Status: {_escape(status)} | Segment: {_escape(segment)}")
    return RoutineResult(
        name="hot_leads",
        message="\n".join(lines),
        payload={"limit": limit, "leads": leads},
    )


def _stale_review(store: RoutineStore, *, days: int, limit: int) -> RoutineResult:
    queue = store.list_stale_review_queue(days=days, limit=limit)
    lines = [f"🧭 <b>Stale review queue (&gt;{days}d)</b>"]
    if not queue:
        lines.append("No stale companies found.")
    for idx, company in enumerate(queue, start=1):
        name = _escape(company.get("name") or "Unknown")
        domain = _escape(company.get("domain") or "")
        status = _escape(company.get("status") or "unknown")
        verified = _escape(str(company.get("last_verified") or "never"))
        lines.append(f"{idx}. <b>{name}</b> — {domain}")
        lines.append(f"Status: {status} | Verified: {verified}")
    return RoutineResult(
        name="stale_review",
        message="\n".join(lines),
        payload={"days": days, "limit": limit, "companies": queue},
    )


def _format_count_lines(counts: dict[str, int]) -> list[str]:
    if not counts:
        return ["none"]
    return [f"• {_escape(status)}: {int(count)}" for status, count in sorted(counts.items())]


def _format_segment_lines(coverage: dict[str, dict[str, int]]) -> list[str]:
    if not coverage:
        return ["none"]
    lines = []
    for segment, counts in sorted(coverage.items()):
        summary = ", ".join(
            f"{_escape(status)} {int(count)}" for status, count in sorted(counts.items())
        )
        lines.append(f"• {_escape(segment)}: {summary or 'none'}")
    return lines


def _escape(value: object) -> str:
    return html.escape(str(value), quote=False)


def _default_sender() -> SendMessage:
    from notify import send

    return send


def _default_store() -> RoutineStore:
    from supabase_store import SupabaseStore

    return SupabaseStore()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Telegram routines Kvetio")
    parser.add_argument("routine", choices=("daily_digest", "hot_leads", "stale_review"))
    parser.add_argument("--dry-run", action="store_true", help="Print JSON without Telegram send")
    parser.add_argument("--limit", type=int, default=5, help="Maximum rows for list routines")
    parser.add_argument(
        "--days",
        type=int,
        default=14,
        help="Stale threshold for stale_review routine",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_routine(
        args.routine,
        store=_default_store(),
        dry_run=args.dry_run,
        limit=args.limit,
        days=args.days,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, default=str))
    return 0 if args.dry_run or result.sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
