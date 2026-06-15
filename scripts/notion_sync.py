"""Детерминированный слой синхронизации Supabase ↔ Notion.

БД — источник истины. forward: БД→Notion (курируемые поля).
reverse: Notion→БД (whitelist ручных полей).

Маппинг — в config/notion_mapping.yaml. Клиенты (Notion, БД) инжектируются
через gateways, поэтому логика юнит-тестируется без сети.

CLI:
    python scripts/notion_sync.py --entity companies --all
    python scripts/notion_sync.py --entity companies --forward
    python scripts/notion_sync.py --entity companies --reverse
    python scripts/notion_sync.py --ensure-schema --entity companies
    python scripts/notion_sync.py --validate --dry-run
    python scripts/notion_sync.py --backfill --entity companies
    python scripts/notion_sync.py --list-fields --entity companies
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent
load_dotenv(_REPO_ROOT / ".env")

MAPPING_PATH = _REPO_ROOT / "config" / "notion_mapping.yaml"

VALID_NOTION_TYPES = {
    "title", "rich_text", "url", "email", "number", "select", "multi_select", "date",
}
VALID_DIRECTIONS = {"forward", "reverse"}


def load_mapping(path: Path = MAPPING_PATH) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def validate_mapping(mapping: dict) -> list[str]:
    """Возвращает список ошибок конфига (пустой = валиден)."""
    errors: list[str] = []
    for entity, cfg in mapping.items():
        if "notion_database_id_env" not in cfg:
            errors.append(f"{entity}: отсутствует notion_database_id_env")
        for f in cfg.get("fields", []):
            col = f.get("db_column", "<?>")
            nt = f.get("notion_type")
            direction = f.get("direction")
            if nt not in VALID_NOTION_TYPES:
                errors.append(f"{entity}.{col}: недопустимый notion_type '{nt}'")
            if direction not in VALID_DIRECTIONS:
                errors.append(f"{entity}.{col}: недопустимый direction '{direction}'")
    return errors
