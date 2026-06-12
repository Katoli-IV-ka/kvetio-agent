"""Supabase storage layer — единственный источник истины.

Используется Claude через Bash и напрямую в скриптах:
    from supabase_store import SupabaseStore
    store = SupabaseStore()
    store.upsert_company(company)

Требует переменных окружения (из .env):
    SUPABASE_URL=https://xxxx.supabase.co
    SUPABASE_KEY=eyJ...

CLI (диагностика):
    python scripts/supabase_store.py --stats
    python scripts/supabase_store.py --list-status new
"""

from __future__ import annotations

import argparse
import difflib
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client, Client

sys.path.insert(0, str(Path(__file__).parent))
from models import Company, RawSignal

logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).parent.parent / ".env")


class SupabaseStore:
    """CRUD-операции с Supabase Postgres через официальный Python-клиент."""

    def __init__(self) -> None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL и SUPABASE_KEY должны быть в .env"
            )
        self._client: Client = create_client(url, key)

    # ── Companies ────────────────────────────────────────────────────────────

    def upsert_company(self, company: Company) -> None:
        """Создаёт или обновляет запись о компании. Ключ: domain."""
        row = {
            "domain": company.normalized_domain,
            "name": company.name,
            "website": company.website,
            "linkedin_url": company.linkedin_url,
            "status": company.status,
            "icp_segment": company.icp_segment,
            "funding_stage": company.funding_stage,
            "latest_signal": company.latest_signal,
            "ai_direction": company.ai_direction,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if company.last_verified:
            row["last_verified"] = company.last_verified.isoformat()
        if company.last_funding_date:
            row["funding_date"] = company.last_funding_date.isoformat()
        if company.score:
            row["score"] = company.score.total
            row["score_bucket"] = _map_bucket(company.score.bucket)
            row["score_version"] = company.score.version

        self._client.table("companies").upsert(row, on_conflict="domain").execute()
        logger.debug("upsert_company: %s", company.normalized_domain)

    def find_fuzzy_duplicate(self, company_name: str, threshold: float = 0.85) -> str | None:
        """Ищет компанию с похожим названием в базе.

        Возвращает domain совпавшей компании или None если дублей нет.
        Использует normalize_company_name для нормализации перед сравнением.
        """
        from normalize import normalize_company_name

        normalized_input = normalize_company_name(company_name)
        if not normalized_input:
            return None

        res = (
            self._client.table("companies")
            .select("name, domain")
            .execute()
        )
        existing = res.data or []

        for row in existing:
            existing_name = normalize_company_name(row.get("name", ""))
            if not existing_name:
                continue
            ratio = difflib.SequenceMatcher(
                None, normalized_input, existing_name
            ).ratio()
            if ratio >= threshold:
                logger.debug(
                    "fuzzy_duplicate: '%s' ~ '%s' (ratio=%.2f)",
                    company_name, row["name"], ratio,
                )
                return row.get("domain")

        return None

    def get_company(self, domain: str) -> dict | None:
        res = (
            self._client.table("companies")
            .select("*")
            .eq("domain", domain)
            .maybe_single()
            .execute()
        )
        return res.data

    def list_companies_by_status(self, status: str) -> list[dict]:
        res = (
            self._client.table("companies")
            .select("*")
            .eq("status", status)
            .execute()
        )
        return res.data or []

    def update_status(self, domain: str, status: str) -> None:
        self._client.table("companies").update({
            "status": status,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("domain", domain).execute()

    def update_notion_page_id(self, domain: str, notion_page_id: str) -> None:
        self._client.table("companies").update({
            "notion_page_id": notion_page_id,
            "updated_at": datetime.utcnow().isoformat(),
        }).eq("domain", domain).execute()

    # ── Signals ──────────────────────────────────────────────────────────────

    def upsert_signal(self, signal: RawSignal, normalized_domain: str | None) -> bool:
        """Возвращает True если сигнал новый. evidence_url — UNIQUE."""
        row = {
            "source": signal.source,
            "signal_type": signal.signal_type,
            "company_name": signal.company_name,
            "domain": signal.domain,
            "normalized_domain": normalized_domain,
            "evidence_url": signal.evidence_url,
            "signal_date": signal.signal_date.isoformat(),
            "confidence": signal.confidence,
            "parser_version": signal.parser_version,
            "raw_data": signal.raw_payload,
        }
        res = (
            self._client.table("signals")
            .upsert(row, on_conflict="evidence_url", ignore_duplicates=True)
            .execute()
        )
        # ignore_duplicates=True → пустой массив data если дубликат
        return bool(res.data)

    def get_signals_for_company(self, domain: str) -> list[dict]:
        res = (
            self._client.table("signals")
            .select("*")
            .eq("normalized_domain", domain)
            .order("signal_date", desc=True)
            .execute()
        )
        return res.data or []

    # ── Run logs ─────────────────────────────────────────────────────────────

    def log_run(
        self,
        task_name: str,
        *,
        companies_found: int = 0,
        companies_enriched: int = 0,
        errors: list | None = None,
    ) -> None:
        self._client.table("run_logs").insert({
            "task_name": task_name,
            "started_at": datetime.utcnow().isoformat(),
            "companies_found": companies_found,
            "companies_enriched": companies_enriched,
            "errors": errors or [],
        }).execute()

    # ── Stats ────────────────────────────────────────────────────────────────

    def stats(self) -> dict:
        """Агрегированная статистика для дашборда."""
        res = self._client.table("companies").select("status").execute()
        rows = res.data or []
        counts: dict[str, int] = {}
        for row in rows:
            s = row.get("status", "unknown")
            counts[s] = counts.get(s, 0) + 1
        return {
            "total": len(rows),
            "by_status": counts,
        }

    def coverage_by_segment(self) -> dict[str, dict[str, int]]:
        """Сводка по ICP-сегментам и статусам.

        Возвращает:
            {
                "medical-imaging": {"new": 12, "pending_enrich": 5, "enriched": 3},
                "autonomous-vehicles": {"new": 2, ...},
                ...
            }
        """
        res = (
            self._client.table("companies")
            .select("icp_segment, status")
            .execute()
        )
        rows = res.data or []

        coverage: dict[str, dict[str, int]] = {}
        for row in rows:
            segment = row.get("icp_segment") or "unknown"
            status = row.get("status") or "unknown"
            if segment not in coverage:
                coverage[segment] = {}
            coverage[segment][status] = coverage[segment].get(status, 0) + 1

        return coverage

    def list_hot_leads(self, limit: int = 5) -> list[dict]:
        """Очередь Hot-лидов для Telegram routines."""
        res = (
            self._client.table("companies")
            .select(
                "name, domain, status, score, score_bucket, icp_segment, latest_signal, "
                "notion_page_id, updated_at"
            )
            .eq("status", "enriched")
            .eq("score_bucket", "Hot")
            .order("score", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []

    def list_stale_review_queue(self, days: int = 14, limit: int = 10) -> list[dict]:
        """Компании, которые давно не проверялись или ещё ни разу не проверены."""
        cutoff = date.today() - timedelta(days=days)
        review_statuses = [
            "new",
            "pending_verify",
            "pending_enrich",
            "needs_update",
            "manual_review",
        ]
        res = (
            self._client.table("companies")
            .select(
                "name, domain, status, score, score_bucket, icp_segment, "
                "last_verified, updated_at"
            )
            .in_("status", review_statuses)
            .or_(f"last_verified.is.null,last_verified.lt.{cutoff.isoformat()}")
            .order("last_verified", desc=False)
            .limit(limit)
            .execute()
        )
        return res.data or []


def _map_bucket(bucket: str) -> str:
    """Маппинг внутреннего bucket → Notion Score Bucket."""
    return {
        "qualified": "Hot",
        "manual_review": "Warm",
        "not_relevant": "Cold",
    }.get(bucket, "Cold")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Supabase storage — диагностика")
    parser.add_argument("--stats", action="store_true", help="Показать статистику pipeline")
    parser.add_argument("--list-status", metavar="STATUS",
                        help="Список компаний с указанным статусом")
    parser.add_argument("--coverage", action="store_true",
                        help="Покрытие компаний по ICP-сегментам")
    args = parser.parse_args()

    store = SupabaseStore()

    if args.stats:
        print(json.dumps(store.stats(), ensure_ascii=False, indent=2))
    elif args.list_status:
        companies = store.list_companies_by_status(args.list_status)
        print(json.dumps(companies, ensure_ascii=False, indent=2, default=str))
    elif args.coverage:
        coverage = store.coverage_by_segment()
        print(json.dumps(coverage, ensure_ascii=False, indent=2))
    else:
        parser.print_help()
