#!/usr/bin/env python3
"""
YC Company Browser — парсер публичного каталога Y Combinator.

Источник данных: yc-oss/api (https://github.com/yc-oss/api)
Публичный JSON API, обновляется ежедневно через GitHub Actions.
Никаких API-ключей не требуется.

Стратегия:
  1. Загружаем yc-oss.github.io/api/companies/all.json (~4000 компаний, ~1-2 MB)
  2. Фильтруем локально по тегам ICP-сегмента
  3. Нормализуем домены и конвертируем в формат сигнала

YC company object structure (yc-oss/api):
  id: int, name: str, slug: str, website: str,
  one_liner: str, long_description: str,
  batch: str ("W24", "S23"), tags: list[str],  # оригинальный формат: "Machine Learning"
  team_size: int, status: str ("Active" / "Inactive" / "Acquired")
  locations: list[str], isHiring: bool, top_company: bool

Использование:
  python scripts/yc_browser.py --segment medical-imaging --dry-run
  python scripts/yc_browser.py --segment autonomous-vehicles --limit 100
  python scripts/yc_browser.py --tags "Machine Learning,Healthcare"
"""

import sys
import os
import json
import argparse
import requests
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from normalize import normalize_domain

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

YC_OSS_ALL_URL = "https://yc-oss.github.io/api/companies/all.json"
YC_COMPANY_BASE_URL = "https://www.ycombinator.com/companies"

# Кеш: храним all.json рядом со скриптом, обновляем раз в сутки
_CACHE_DIR = Path(__file__).parent.parent / "data"
_CACHE_FILE = _CACHE_DIR / "yc_companies_cache.json"
_CACHE_TTL_SECONDS = 86400  # 24 часа

# Маппинг ICP-сегментов → теги YC в оригинальном формате (как в данных yc-oss)
ICP_TAG_MAP: dict[str, list[str]] = {
    "medical-imaging": [
        "Healthcare",
        "Medical Devices",
        "Diagnostics",
        "Biotech",
        "Medical Imaging",
        "Radiology",
        "Bioinformatics",
    ],
    "autonomous-vehicles": [
        "Autonomous Vehicles",
        "Robotics",
        "Drones",
        "Computer Vision",
        "Self-Driving Cars",
        "LIDAR",
    ],
    "speech-and-audio": [
        "Speech Recognition",
        "Voice Assistants",
        "Audio",
        "Natural Language Processing",
        "NLP",
    ],
    "generative-ai": [
        "Generative AI",
        "Large Language Models",
        "Artificial Intelligence",
        "Machine Learning",
        "Natural Language Processing",
        "Foundation Models",
    ],
    "agriculture-ai": [
        "Agriculture",
        "AgTech",
        "Biotech",
        "Machine Learning",
        "Artificial Intelligence",
        "Drones",
        "Climate",
    ],
    "robotics-ai": [
        "Robotics",
        "Hardware",
        "Manufacturing",
        "Computer Vision",
        "Industrial Automation",
        "Autonomous Vehicles",
    ],
    "video-photo-ai": [
        "Generative AI",
        "Video",
        "Machine Learning",
        "Artificial Intelligence",
        "Computer Vision",
        "Photography",
    ],
}

# Базовые AI/ML теги — добавляются к любому сегменту как OR-фильтр
AI_ML_BASE_TAGS: list[str] = [
    "Machine Learning",
    "Artificial Intelligence",
    "Deep Learning",
    "Computer Vision",
    "Natural Language Processing",
    "Data Science",
]

_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "kvetio-agent/1.0 (github.com/kvetio)"})

# ---------------------------------------------------------------------------
# Tag resolution
# ---------------------------------------------------------------------------

def resolve_tags(
    segment: Optional[str] = None,
    tags_str: Optional[str] = None,
) -> list[str]:
    """
    Определяет список тегов для фильтрации (оригинальный формат YC).

    Приоритет: tags_str > segment > AI_ML_BASE_TAGS.
    """
    if tags_str:
        return [t.strip() for t in tags_str.split(",") if t.strip()]
    if segment:
        segment_tags = ICP_TAG_MAP.get(segment, [])
        # Сохраняем порядок, без дублей
        return list(dict.fromkeys(segment_tags + AI_ML_BASE_TAGS))
    return list(AI_ML_BASE_TAGS)

# ---------------------------------------------------------------------------
# yc-oss API
# ---------------------------------------------------------------------------

def _load_cache() -> Optional[list[dict]]:
    """Читает кеш если он существует и не устарел (< 24ч)."""
    if not _CACHE_FILE.exists():
        return None
    age = time.time() - _CACHE_FILE.stat().st_mtime
    if age > _CACHE_TTL_SECONDS:
        print(f"[INFO] Кеш устарел ({age/3600:.1f}ч), обновляю...", file=sys.stderr)
        return None
    print(f"[INFO] Использую кеш ({age/3600:.1f}ч назад): {_CACHE_FILE}", file=sys.stderr)
    with open(_CACHE_FILE, encoding="utf-8") as f:
        return json.load(f)


def _save_cache(data: list[dict]) -> None:
    """Сохраняет данные в кеш."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with open(_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"[INFO] Кеш сохранён: {_CACHE_FILE} ({len(data)} компаний)", file=sys.stderr)


def fetch_all_yc_companies(timeout: int = 30, refresh: bool = False) -> list[dict]:
    """
    Загружает весь каталог YC (~4000 компаний) из yc-oss API.
    Использует локальный кеш (data/yc_companies_cache.json, TTL 24ч).
    """
    if not refresh:
        cached = _load_cache()
        if cached is not None:
            return cached

    print(f"[INFO] Загрузка каталога YC: {YC_OSS_ALL_URL}", file=sys.stderr)
    try:
        resp = _SESSION.get(YC_OSS_ALL_URL, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
        companies = data if isinstance(data, list) else data.get("companies", [])
        _save_cache(companies)
        return companies
    except requests.exceptions.ConnectionError as e:
        print(f"[ERROR] Нет подключения к yc-oss API: {e}", file=sys.stderr)
        raise
    except requests.exceptions.Timeout:
        print(f"[ERROR] Таймаут при загрузке yc-oss API (>{timeout}s)", file=sys.stderr)
        raise
    except Exception as e:
        print(f"[ERROR] Ошибка загрузки yc-oss API: {e}", file=sys.stderr)
        raise


def filter_companies_by_tags(
    companies: list[dict],
    tags: list[str],
    active_only: bool = True,
) -> list[dict]:
    """
    Фильтрует компании по тегам (OR-логика: хотя бы один тег совпадает).
    Нечувствителен к регистру.
    """
    tags_lower = {t.lower() for t in tags}

    result = []
    for company in companies:
        if active_only and company.get("status", "").lower() not in ("active", ""):
            continue
        company_tags = {t.lower() for t in (company.get("tags") or [])}
        if company_tags & tags_lower:  # пересечение множеств
            result.append(company)
    return result


def fetch_yc_companies(tags: list[str], limit: int = 500, refresh: bool = False) -> list[dict]:
    """
    Загружает весь каталог и фильтрует по тегам.
    Возвращает не более `limit` компаний.
    """
    all_companies = fetch_all_yc_companies(refresh=refresh)
    print(f"[INFO] Всего компаний в каталоге: {len(all_companies)}", file=sys.stderr)

    filtered = filter_companies_by_tags(all_companies, tags)
    print(f"[INFO] После фильтрации по тегам: {len(filtered)}", file=sys.stderr)

    if len(filtered) > limit:
        print(f"[INFO] Обрезаем до лимита {limit}", file=sys.stderr)
        filtered = filtered[:limit]

    return filtered

# ---------------------------------------------------------------------------
# Data conversion
# ---------------------------------------------------------------------------

def company_to_signal(company: dict) -> Optional[dict]:
    """
    Конвертирует объект yc-oss API → унифицированный формат сигнала.
    Совместим с форматом greenhouse.py и других источников.
    """
    name = (company.get("name") or "").strip()
    website = (company.get("website") or "").strip()

    if not name and not website:
        return None

    domain = None
    if website:
        try:
            domain = normalize_domain(website)
        except ValueError:
            domain = None

    description = (
        company.get("one_liner")
        or company.get("long_description")
        or ""
    ).strip()

    slug = company.get("slug", "")
    batch = company.get("batch", "")
    tags = company.get("tags") or []

    return {
        "company_name": name,
        "domain": domain,
        "website": website,
        "description": description,
        "source": "yc_browser",
        "signal_type": "yc_company",
        "batch": batch,
        "tags": tags,
        "team_size": company.get("team_size"),
        "evidence_url": f"{YC_COMPANY_BASE_URL}/{slug}" if slug else None,
        "signal_date": datetime.utcnow().strftime("%Y-%m-%d"),
        "confidence": "high",
        "raw_data": {
            "yc_id": company.get("id"),
            "yc_slug": slug,
            "batch": batch,
            "status": company.get("status"),
            "tags": tags,
            "team_size": company.get("team_size"),
            "locations": company.get("locations") or company.get("all_locations"),
            "year_founded": company.get("year_founded"),
            "is_hiring": company.get("isHiring"),
            "top_company": company.get("top_company"),
        },
    }

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="YC Company Browser — фильтрация каталога YC по ICP-сегменту"
    )
    parser.add_argument(
        "--segment",
        choices=list(ICP_TAG_MAP.keys()),
        help="ICP-сегмент (medical-imaging | autonomous-vehicles | speech-and-audio)",
    )
    parser.add_argument(
        "--tags",
        help="Теги через запятую, оригинальный формат (переопределяет --segment). "
             "Пример: 'Machine Learning,Healthcare'",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Максимальное количество компаний на выходе (default: 200)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Только вывод в stdout, без записи в Supabase",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Принудительно обновить локальный кеш компаний",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Проверить подключение к yc-oss API и вывести 3 примера компаний",
    )
    args = parser.parse_args()

    # Режим самодиагностики
    if args.self_test:
        print("[SELF-TEST] Проверяю подключение к yc-oss API...", file=sys.stderr)
        try:
            companies = fetch_all_yc_companies(refresh=True)
            print(f"[SELF-TEST] ✅ Загружено {len(companies)} компаний", file=sys.stderr)
            print("[SELF-TEST] Примеры (первые 3):", file=sys.stderr)
            for c in companies[:3]:
                print(f"  - {c.get('name')} | {c.get('website')} | batch={c.get('batch')} | tags={c.get('tags', [])[:3]}", file=sys.stderr)
            print("[SELF-TEST] Структура первой компании (ключи):", file=sys.stderr)
            print(f"  {list(companies[0].keys())}", file=sys.stderr)
        except Exception as e:
            print(f"[SELF-TEST] ❌ Ошибка: {e}", file=sys.stderr)
            sys.exit(1)
        sys.exit(0)

    tags = resolve_tags(segment=args.segment, tags_str=args.tags)

    print(f"[INFO] Источник: yc-oss/api ({YC_OSS_ALL_URL})", file=sys.stderr)
    print(f"[INFO] Теги для фильтрации ({len(tags)}): {tags}", file=sys.stderr)
    print(f"[INFO] Лимит: {args.limit}", file=sys.stderr)

    try:
        companies = fetch_yc_companies(tags=tags, limit=args.limit, refresh=args.refresh_cache)
    except Exception as e:
        print(f"[ERROR] Не удалось получить данные: {e}", file=sys.stderr)
        sys.exit(1)

    signals = []
    skipped = 0
    for company in companies:
        signal = company_to_signal(company)
        if signal and signal.get("domain"):
            signals.append(signal)
        else:
            skipped += 1

    print(json.dumps(signals, ensure_ascii=False, indent=2))

    print(
        f"[INFO] Итог: {len(signals)} компаний с доменом, пропущено без домена: {skipped}",
        file=sys.stderr,
    )

    if args.dry_run:
        print("[DRY RUN] Данные не записаны в Supabase.", file=sys.stderr)


if __name__ == "__main__":
    main()
