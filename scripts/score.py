"""Детерминированный scoring engine.

Pure-функция: одинаковые входы → одинаковый выход.
Никаких сетевых вызовов, никаких side effects.

CLI (вызывается Claude через Bash):
    # Скор одной компании по JSON-профилю из stdin
    echo '{"domain": "acme.ai", "evidences": [...]}' | python scripts/score.py

    # Или передать файл
    python scripts/score.py --profile /tmp/company.json

    # Пересчитать все компании из Supabase (batch-режим)
    python scripts/score.py --all

Возвращает JSON:
    {
      "domain": "acme.ai",
      "score": 23,
      "bucket": "not_relevant",   # not_relevant | manual_review | qualified
      "breakdown": {
        "training_intensity": 0,
        "external_data_fit": 8,
        "commercial_readiness": 6,
        "freshness": 5,
        "negative_flags": 0,
        "total": 19
      },
      "contributing_signals": [...]
    }
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

# Плоский импорт из той же папки
sys.path.insert(0, str(Path(__file__).parent))
from models import Bucket, Company, Evidence, ScoreBreakdown, ScoringSignal

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "scoring.yaml"


# ─── Конфиг ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScoringConfig:
    version: str
    threshold_qualified: int
    threshold_manual_review: int
    weights: dict


def load_config(path: Path | str = _DEFAULT_CONFIG) -> ScoringConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return ScoringConfig(
        version=raw["version"],
        threshold_qualified=int(raw["thresholds"]["qualified"]),
        threshold_manual_review=int(raw["thresholds"]["manual_review"]),
        weights=raw["weights"],
    )


# ─── Scoring components ───────────────────────────────────────────────────────

def _bucketize(total: int, cfg: ScoringConfig) -> Bucket:
    if total >= cfg.threshold_qualified:
        return "qualified"
    if total >= cfg.threshold_manual_review:
        return "manual_review"
    return "not_relevant"


def _freshness(company: Company, weights: dict) -> tuple[int, list[ScoringSignal]]:
    """Самый свежий сигнал даёт freshness-баллы."""
    if not company.evidences:
        return 0, []
    most_recent = max(e.signal_date for e in company.evidences)
    age_days = (date.today() - most_recent).days

    bands = [
        (30, "freshness.signal_within_30d", "signal_within_30d"),
        (90, "freshness.signal_within_90d", "signal_within_90d"),
        (180, "freshness.signal_within_180d", "signal_within_180d"),
    ]
    for max_days, rule_key, weight_key in bands:
        if age_days <= max_days:
            pts = int(weights.get(weight_key, 0))
            if pts == 0:
                return 0, []
            return pts, [ScoringSignal(rule=rule_key, points=pts)]
    return 0, []


def _training_intensity(company: Company, weights: dict) -> tuple[int, list[ScoringSignal]]:
    """Сигналы, что компания активно обучает модели.
    TODO: расширить после накопления данных о wandb, github."""
    signals: list[ScoringSignal] = []
    pts = 0

    for ev in company.evidences:
        snippet = (ev.snippet or "").lower()
        if any(k in snippet for k in ("training data", "we train", "training pipeline")):
            w = int(weights.get("site_we_train", 0))
            if w:
                pts += w
                signals.append(ScoringSignal(
                    rule="training_intensity.site_we_train",
                    points=w,
                    evidence_url=ev.url,
                ))
            break  # один раз за компанию

    return pts, signals


def _external_data_fit(company: Company, weights: dict) -> tuple[int, list[ScoringSignal]]:
    """Сигналы, что компании нужны внешние данные."""
    signals: list[ScoringSignal] = []
    pts = 0
    seen_job_kw = False

    data_keywords = (
        "annotation", "labeling", "rlhf", "training data",
        "dataset curation", "data annotation",
    )
    high_data_industries = {"medical", "automotive", "robotics", "defense", "healthcare"}

    for ev in company.evidences:
        snippet = (ev.snippet or "").lower()
        if not seen_job_kw and ev.signal_type == "job_posting":
            if any(k in snippet for k in data_keywords):
                w = int(weights.get("job_keyword_training_data", 0))
                if w:
                    pts += w
                    signals.append(ScoringSignal(
                        rule="external_data_fit.job_keyword_training_data",
                        points=w,
                        evidence_url=ev.url,
                    ))
                    seen_job_kw = True

    for industry in company.industries:
        if any(h in industry.lower() for h in high_data_industries):
            w = int(weights.get("industry_high_data_need", 0))
            if w:
                pts += w
                signals.append(ScoringSignal(
                    rule="external_data_fit.industry_high_data_need",
                    points=w,
                ))
            break

    return pts, signals


def _commercial_readiness(company: Company, weights: dict) -> tuple[int, list[ScoringSignal]]:
    """Коммерческая состоятельность по стадии финансирования."""
    signals: list[ScoringSignal] = []
    pts = 0
    stage = (company.funding_stage or "").lower()

    if any(s in stage for s in ("series a", "series b", "series c", "growth")):
        w = int(weights.get("series_a_or_higher", 0))
        if w:
            pts += w
            signals.append(ScoringSignal(
                rule="commercial_readiness.series_a_or_higher", points=w
            ))

    if company.last_funding_date:
        age = (date.today() - company.last_funding_date).days
        if age <= 180:
            w = int(weights.get("funding_last_6m", 0))
            if w:
                pts += w
                signals.append(ScoringSignal(
                    rule="commercial_readiness.funding_last_6m", points=w
                ))
        elif age <= 365:
            w = int(weights.get("funding_last_12m", 0))
            if w:
                pts += w
                signals.append(ScoringSignal(
                    rule="commercial_readiness.funding_last_12m", points=w
                ))

    return pts, signals


def _negative_flags(company: Company, weights: dict) -> tuple[int, list[ScoringSignal]]:
    """Снижающие факторы."""
    signals: list[ScoringSignal] = []
    pts = 0

    # Компания сама продаёт данные — не покупатель
    name_lower = company.name.lower()
    if any(k in name_lower for k in ("scale ai", "labelbox", "appen", "surge ai", "dataloop")):
        w = int(weights.get("api_wrapper_only", 0))
        if w:
            pts += w
            signals.append(ScoringSignal(rule="negative_flags.data_provider", points=w))

    return pts, signals


# ─── Main scorer ─────────────────────────────────────────────────────────────

def score(company: Company, cfg: ScoringConfig) -> ScoreBreakdown:
    """Pure: одинаковые входы → одинаковый выход."""
    contributing: list[ScoringSignal] = []

    a, s_a = _training_intensity(company, cfg.weights.get("training_intensity", {}))
    b, s_b = _external_data_fit(company, cfg.weights.get("external_data_fit", {}))
    c, s_c = _commercial_readiness(company, cfg.weights.get("commercial_readiness", {}))
    d, s_d = _freshness(company, cfg.weights.get("freshness", {}))
    neg, s_neg = _negative_flags(company, cfg.weights.get("negative_flags", {}))

    contributing.extend(s_a + s_b + s_c + s_d + s_neg)
    total = a + b + c + d - neg

    return ScoreBreakdown(
        version=cfg.version,
        training_intensity=a,
        external_data_fit=b,
        commercial_readiness=c,
        freshness=d,
        negative_flags=neg,
        bucket=_bucketize(total, cfg),
        contributing_signals=tuple(contributing),
    )


# ─── CLI helpers ──────────────────────────────────────────────────────────────

def _parse_company_json(data: dict) -> Company:
    """Из JSON-профиля компании собирает объект Company."""
    from datetime import date as date_cls  # noqa: PLC0415

    evidences = []
    for ev in data.get("evidences", []):
        evidences.append(Evidence(
            source=ev["source"],
            signal_type=ev["signal_type"],
            url=ev["url"],
            signal_date=date_cls.fromisoformat(ev["signal_date"]),
            confidence=ev.get("confidence", "medium"),
            snippet=ev.get("snippet", ""),
        ))

    last_funding = data.get("last_funding_date")

    return Company(
        normalized_domain=data.get("domain", ""),
        name=data.get("name", ""),
        website=data.get("website", f"https://{data.get('domain', '')}"),
        industries=data.get("industries", []),
        funding_stage=data.get("funding_stage"),
        last_funding_date=date_cls.fromisoformat(last_funding) if last_funding else None,
        evidences=evidences,
        icp_segment=data.get("icp_segment"),
    )


def _result_dict(domain: str, breakdown: ScoreBreakdown) -> dict:
    return {
        "domain": domain,
        "score": breakdown.total,
        "bucket": breakdown.bucket,
        "version": breakdown.version,
        "breakdown": {
            "training_intensity": breakdown.training_intensity,
            "external_data_fit": breakdown.external_data_fit,
            "commercial_readiness": breakdown.commercial_readiness,
            "freshness": breakdown.freshness,
            "negative_flags": breakdown.negative_flags,
            "total": breakdown.total,
        },
        "contributing_signals": [
            {"rule": s.rule, "points": s.points, "evidence_url": s.evidence_url}
            for s in breakdown.contributing_signals
        ],
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Kvetio scoring engine")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--profile", help="JSON-файл с профилем компании")
    group.add_argument("--stdin", action="store_true", default=True,
                       help="Читать JSON из stdin (по умолчанию)")
    parser.add_argument("--config", default=str(_DEFAULT_CONFIG),
                        help="Путь к scoring.yaml")
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.profile:
        raw = json.loads(Path(args.profile).read_text(encoding="utf-8"))
    else:
        raw = json.loads(sys.stdin.read())

    company = _parse_company_json(raw)
    breakdown = score(company, cfg)
    print(json.dumps(_result_dict(company.normalized_domain, breakdown),
                     ensure_ascii=False, indent=2))
