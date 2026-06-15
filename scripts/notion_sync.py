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


def to_notion_property(notion_type: str, value) -> dict:
    """Python-значение → Notion property payload. None очищает поле."""
    if notion_type == "title":
        return {"title": [] if value is None else [{"text": {"content": str(value)}}]}
    if notion_type == "rich_text":
        return {"rich_text": [] if value is None else [{"text": {"content": str(value)}}]}
    if notion_type == "url":
        return {"url": value if value else None}
    if notion_type == "email":
        return {"email": value if value else None}
    if notion_type == "number":
        return {"number": value if value is not None else None}
    if notion_type == "select":
        return {"select": {"name": str(value)} if value else None}
    if notion_type == "multi_select":
        items = value or []
        return {"multi_select": [{"name": str(v)} for v in items]}
    if notion_type == "date":
        return {"date": {"start": str(value)} if value else None}
    raise ValueError(f"unsupported notion_type: {notion_type}")


def from_notion_property(notion_type: str, prop: dict):
    """Notion property payload → Python-значение (для reverse-синка)."""
    if prop is None:
        return None
    if notion_type == "title":
        items = prop.get("title", [])
        return "".join(i.get("plain_text", i.get("text", {}).get("content", "")) for i in items) or None
    if notion_type == "rich_text":
        items = prop.get("rich_text", [])
        return "".join(i.get("plain_text", i.get("text", {}).get("content", "")) for i in items) or None
    if notion_type in ("url", "email", "number"):
        return prop.get(notion_type)
    if notion_type == "select":
        sel = prop.get("select")
        return sel.get("name") if sel else None
    if notion_type == "multi_select":
        return [i["name"] for i in prop.get("multi_select", [])]
    if notion_type == "date":
        d = prop.get("date")
        return d.get("start") if d else None
    raise ValueError(f"unsupported notion_type: {notion_type}")
