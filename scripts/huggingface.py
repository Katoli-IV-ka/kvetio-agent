"""HuggingFace Hub — source-адаптер.

API:
  GET https://huggingface.co/api/models
      ?pipeline_tag={tag}&author_type=organization&sort=downloads&limit=1000&offset=N
  GET https://huggingface.co/api/organizations/{name}

Auth: опциональный HF_TOKEN из .env (расширяет rate limits HF).
Rate: 5 rps — консервативный, работает без токена.

Стратегия: organizations-first.
  1. Для каждого pipeline_tag сегмента — собрать уникальных org-авторов.
  2. Дедуплицировать авторов по всем тегам.
  3. Для каждого уникального автора — GET /api/organizations/{name}.
  4. Yield RawSignal.

CLI:
    python scripts/huggingface.py --segment speech-and-audio --dry-run
    python scripts/huggingface.py --segment speech-and-audio --max-models 200
    python scripts/huggingface.py --segment speech-and-audio --output results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).parent))
from http_client import HttpClient
from models import ICPQuery, RawSignal

logger = logging.getLogger(__name__)

HF_MODELS_URL = "https://huggingface.co/api/models"
HF_ORGS_URL = "https://huggingface.co/api/organizations"
HF_ORGS_OVERVIEW_URL = "https://huggingface.co/api/organizations"  # endpoint: /{name}/overview

# Маппинг ICP-сегмент → pipeline_tags HuggingFace.
# Синхронизировать с config/sources.yaml pipeline_tag_map.
PIPELINE_TAG_MAP: dict[str, list[str]] = {
    "speech-and-audio": [
        "automatic-speech-recognition",
        "text-to-speech",
        "audio-classification",
        "voice-activity-detection",
    ],
    "medical-imaging": [
        "image-classification",
        "image-segmentation",
        "object-detection",
    ],
    "autonomous-vehicles": [
        "object-detection",
        "depth-estimation",
        "image-segmentation",
    ],
    "generative-ai": [
        "text-generation",
        "text2text-generation",
        "conversational",
        "summarization",
    ],
    "agriculture-ai": [
        "image-classification",
        "image-segmentation",
        "object-detection",
    ],
    "robotics-ai": [
        "reinforcement-learning",
        "depth-estimation",
        "image-segmentation",
    ],
    "video-photo-ai": [
        "text-to-video",
        "image-to-video",
        "text-to-image",
        "image-to-image",
    ],
}


class HuggingFaceAdapter:
    name = "huggingface"
    tier = "A"
    parser_version = "2026-05"

    def __init__(
        self,
        *,
        rate_limit_rps: float = 5.0,
        max_models_per_tag: int = 3000,
        hf_token: str | None = None,
    ) -> None:
        self._client = HttpClient(
            rate_limit_rps=rate_limit_rps,
            extra_headers={"Authorization": f"Bearer {hf_token}"} if hf_token else None,
        )
        self._max_models_per_tag = max_models_per_tag

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HuggingFaceAdapter":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _collect_org_names(self, pipeline_tag: str) -> set[str]:
        """Собрать уникальных org-авторов для одного pipeline_tag."""
        authors: set[str] = set()
        offset = 0
        limit = 1000

        while offset < self._max_models_per_tag:
            data = self._client.get_json(HF_MODELS_URL, params={
                "pipeline_tag": pipeline_tag,
                "author_type": "organization",
                "sort": "downloads",
                "limit": limit,
                "offset": offset,
            })
            if not isinstance(data, list) or not data:
                break
            for model in data:
                # API раньше возвращал поле "author", теперь возвращает "id" вида "org/model-name"
                author = model.get("author") or (model.get("id", "").split("/")[0] if "/" in model.get("id", "") else None)
                if author:
                    authors.add(author)
            if len(data) < limit:
                break
            offset += limit

        logger.debug("pipeline_tag=%r → %d unique orgs", pipeline_tag, len(authors))
        return authors

    def _fetch_org(self, name: str) -> dict | None:
        """Загрузить детали организации через /overview. Возвращает None если 404.

        HuggingFace API изменился: старый /api/organizations/{name} → 404.
        Актуальный эндпоинт: /api/organizations/{name}/overview
        Поле website больше не возвращается — domain получается через WebSearch в агенте.
        """
        data = self._client.get_json(f"{HF_ORGS_URL}/{name}/overview")
        if not data or "error" in data:
            return None
        return data  # type: ignore[return-value]

    def fetch(self, query: ICPQuery) -> Iterator[RawSignal]:
        """Yield RawSignal для каждой org, найденной в нужных pipeline_tags."""
        tags = PIPELINE_TAG_MAP.get(query.segment, [])
        if not tags:
            logger.warning("huggingface: нет pipeline_tags для сегмента %r", query.segment)
            return

        org_to_tags: dict[str, list[str]] = {}
        for tag in tags:
            for org_name in self._collect_org_names(tag):
                org_to_tags.setdefault(org_name, []).append(tag)

        logger.info("huggingface: %d уникальных org для lookup", len(org_to_tags))

        for org_name, matched_tags in org_to_tags.items():
            org = self._fetch_org(org_name)
            if org is None:
                continue
            if org.get("isHf"):
                logger.debug("huggingface: пропускаем HF-сотрудников org %r", org_name)
                continue

            # website убран из /overview — domain будет найден агентом через WebSearch
            website = org.get("website") or org.get("websiteUrl") or None

            yield RawSignal(
                source="huggingface",
                signal_type="hf_org",
                company_name=org.get("fullname") or org_name,
                domain=website,  # None для большинства — fallback через WebSearch в агенте
                linkedin_url=None,
                url=f"https://huggingface.co/{org_name}",
                signal_date=date.today(),
                confidence="medium",
                agent="discovery",
                payload={
                    "pipeline_tags": matched_tags,
                    "num_models": org.get("numModels", 0),
                    "num_members": org.get("numMembers", 0),
                },
                raw_payload=org,
            )


# ── CLI ──────────────────────────────────────────────────────────────────


def _build_query(segment: str) -> ICPQuery:
    return ICPQuery(segment=segment, keywords_strong=())


def main() -> None:
    parser = argparse.ArgumentParser(
        description="HuggingFace source adapter — discovery mode"
    )
    parser.add_argument("--segment", required=True, help="ICP-сегмент (speech-and-audio, ...)")
    parser.add_argument("--max-models", type=int, default=3000, dest="max_models",
                        help="Макс. моделей на pipeline_tag (default: 3000)")
    parser.add_argument("--output", help="Сохранить JSON в файл (default: stdout)")
    parser.add_argument("--dry-run", action="store_true", dest="dry_run",
                        help="Только показать результат, не сохранять в БД")
    parser.add_argument("--log-level", default="INFO", dest="log_level")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    hf_token = os.environ.get("HF_TOKEN")
    query = _build_query(args.segment)

    with HuggingFaceAdapter(
        rate_limit_rps=5.0,
        max_models_per_tag=args.max_models,
        hf_token=hf_token,
    ) as adapter:
        signals = list(adapter.fetch(query))

    output = [
        {
            "company_name": s.company_name,
            "domain": s.domain,
            "url": s.url,
            "signal_date": str(s.signal_date),
            "pipeline_tags": s.payload.get("pipeline_tags", []),
            "num_models": s.payload.get("num_models", 0),
            "num_members": s.payload.get("num_members", 0),
        }
        for s in signals
    ]

    if args.output:
        Path(args.output).write_text(json.dumps(output, ensure_ascii=False, indent=2))
        print(f"Сохранено {len(output)} сигналов в {args.output}", file=sys.stderr)
    else:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        print(f"\n--- Итого: {len(output)} сигналов ---", file=sys.stderr)


if __name__ == "__main__":
    main()
