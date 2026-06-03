"""Нормализация доменов и имён компаний.

`normalized_domain` — primary key для дедупа. Это registered domain без
поддоменов и без www. Примеры:
    https://www.acme.ai/about        -> acme.ai
    https://research.acme.ai/team   -> acme.ai
    http://ACME.AI                   -> acme.ai

CLI:
    python scripts/normalize.py acme.ai
    python scripts/normalize.py https://www.acme.ai/about
"""

from __future__ import annotations

import re
import sys
from urllib.parse import urlparse

import tldextract

# Без сетевых запросов — используем кешированный PSL.
_extractor = tldextract.TLDExtract(suffix_list_urls=())


def normalize_domain(url_or_domain: str) -> str:
    """Превратить любую форму URL/домена в `registered_domain` lowercase.

    Бросает ValueError если на входе мусор.
    """
    if not url_or_domain or not url_or_domain.strip():
        raise ValueError("normalize_domain: пустой ввод")

    raw = url_or_domain.strip().lower()
    if "://" not in raw:
        raw = "http://" + raw

    parsed = urlparse(raw)
    host = parsed.hostname
    if not host:
        raise ValueError(f"normalize_domain: не могу извлечь host из {url_or_domain!r}")

    extracted = _extractor(host)
    if not extracted.domain or not extracted.suffix:
        raise ValueError(
            f"normalize_domain: не могу определить registered_domain в {url_or_domain!r}"
        )

    return f"{extracted.domain}.{extracted.suffix}"


_NAME_NOISE = re.compile(
    r"\b(inc|inc\.|llc|ltd|ltd\.|gmbh|s\.r\.l\.|s\.a\.|co|co\.|corp|corporation|the)\b",
    re.IGNORECASE,
)


def normalize_company_name(name: str) -> str:
    """Снимает суффиксы юр. формы. Используется для fuzzy-матчинга."""
    cleaned = _NAME_NOISE.sub("", name)
    cleaned = re.sub(r"[^\w\s-]", " ", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip().lower()
    return cleaned


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python normalize.py <url_or_domain>")
        sys.exit(1)
    try:
        print(normalize_domain(sys.argv[1]))
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
