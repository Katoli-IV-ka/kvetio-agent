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

NOTION_TYPE_SCHEMA = {
    "title": {"title": {}},
    "rich_text": {"rich_text": {}},
    "url": {"url": {}},
    "email": {"email": {}},
    "number": {"number": {}},
    "select": {"select": {}},
    "multi_select": {"multi_select": {}},
    "date": {"date": {}},
}


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


class NotionGateway:
    """Обёртка над notion-client. Изолирует API для тестируемости."""
    def __init__(self, client):
        self._c = client

    def query_database(self, db_id):
        pages, cursor = [], None
        while True:
            resp = self._c.databases.query(database_id=db_id, start_cursor=cursor) \
                if cursor else self._c.databases.query(database_id=db_id)
            pages.extend(resp["results"])
            if not resp.get("has_more"):
                break
            cursor = resp["next_cursor"]
        return pages

    def create_page(self, db_id, properties, children=None):
        payload = {"parent": {"database_id": db_id}, "properties": properties}
        if children:
            payload["children"] = children
        return self._c.pages.create(**payload)

    def update_page(self, page_id, properties):
        return self._c.pages.update(page_id=page_id, properties=properties)

    def append_children(self, page_id, children):
        return self._c.blocks.children.append(block_id=page_id, children=children)

    def retrieve_database(self, db_id):
        return self._c.databases.retrieve(database_id=db_id)

    def update_database(self, db_id, properties):
        return self._c.databases.update(database_id=db_id, properties=properties)


class DbGateway:
    """Обёртка над supabase-клиентом для notion_sync."""
    def __init__(self, client):
        self._c = client

    def fetch(self, table, status_filter=None):
        q = self._c.table(table).select("*")
        if status_filter:
            q = q.in_("status", status_filter)
        return q.execute().data or []

    def update(self, table, key_col, key_val, fields):
        self._c.table(table).update(fields).eq(key_col, key_val).execute()


class NotionSync:
    def __init__(self, notion, db, mapping=None, env=None):
        self.notion = notion
        self.db = db
        self.mapping = mapping if mapping is not None else load_mapping()
        self.env = env if env is not None else os.environ

    def _cfg(self, entity):
        return self.mapping[entity]

    def _db_id(self, entity):
        env_key = self._cfg(entity)["notion_database_id_env"]
        db_id = self.env.get(env_key)
        if not db_id:
            raise RuntimeError(f"{env_key} не задан в окружении")
        return db_id

    def _fields(self, entity, direction):
        return [f for f in self._cfg(entity)["fields"] if f["direction"] == direction]

    def sync_forward(self, entity, dry_run=False) -> dict:
        cfg = self._cfg(entity)
        db_id = self._db_id(entity)
        fields = self._fields(entity, "forward")
        rows = self.db.fetch(cfg["db_table"], cfg.get("db_status_filter"))
        created = updated = errors = 0
        for row in rows:
            try:
                props = {
                    f["notion_property"]: to_notion_property(f["notion_type"],
                                                             row.get(f["db_column"]))
                    for f in fields
                }
                page_id = row.get("notion_page_id")
                if dry_run:
                    updated += 1 if page_id else 0
                    created += 0 if page_id else 1
                    continue
                if page_id:
                    self.notion.update_page(page_id, props)
                    updated += 1
                else:
                    page = self.notion.create_page(db_id, props)
                    self.db.update(cfg["db_table"], cfg["db_key"],
                                   row[cfg["db_key"]],
                                   {"notion_page_id": page["id"],
                                    "notion_synced_at": datetime.utcnow().isoformat()})
                    created += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("forward %s %s: %s", entity, row.get(cfg["db_key"]), exc)
                errors += 1
        return {"entity": entity, "created": created, "updated": updated, "errors": errors}

    def _page_index(self, entity):
        """notion_page_id → row, для записей, у которых он есть."""
        cfg = self._cfg(entity)
        rows = self.db.fetch(cfg["db_table"])
        return {r["notion_page_id"]: r for r in rows if r.get("notion_page_id")}

    def sync_reverse(self, entity, dry_run=False) -> dict:
        cfg = self._cfg(entity)
        fields = self._fields(entity, "reverse")
        if not fields:
            return {"entity": entity, "updated": 0, "errors": 0}
        index = self._page_index(entity)
        updated = errors = 0
        for page_id, row in index.items():
            try:
                props = self._read_page_props(page_id)
                changes = {}
                for f in fields:
                    val = from_notion_property(f["notion_type"],
                                               props.get(f["notion_property"]))
                    if val != row.get(f["db_column"]):
                        changes[f["db_column"]] = val
                if changes and not dry_run:
                    self.db.update(cfg["db_table"], cfg["db_key"],
                                   row[cfg["db_key"]], changes)
                if changes:
                    updated += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("reverse %s %s: %s", entity, page_id, exc)
                errors += 1
        return {"entity": entity, "updated": updated, "errors": errors}

    def _read_page_props(self, page_id):
        """Свойства страницы из закэшированного query_database."""
        db_id = None
        for entity in self.mapping:
            try:
                db_id = self._db_id(entity)
            except RuntimeError:
                continue
            for page in self.notion.query_database(db_id):
                if page["id"] == page_id:
                    return page.get("properties", {})
        return {}

    def sync_all(self, entity, dry_run=False) -> dict:
        rev = self.sync_reverse(entity, dry_run=dry_run)
        fwd = self.sync_forward(entity, dry_run=dry_run)
        return {"entity": entity, "reverse": rev, "forward": fwd}

    def ensure_schema(self, entity, dry_run=False) -> dict:
        cfg = self._cfg(entity)
        db_id = self._db_id(entity)
        existing = self.notion.retrieve_database(db_id)["properties"]
        to_create = {}
        for f in cfg["fields"]:
            name = f["notion_property"]
            if name not in existing and f["notion_type"] != "title":
                # title-свойство в Notion-базе всегда существует; не создаём.
                to_create[name] = NOTION_TYPE_SCHEMA[f["notion_type"]]
        if to_create and not dry_run:
            self.notion.update_database(db_id, to_create)
        return {"entity": entity, "created": len(to_create),
                "created_props": sorted(to_create.keys())}

    def backfill(self, entity, dry_run=False) -> dict:
        """Одноразовый импорт reverse-полей из Notion в БД. Сейчас = sync_reverse,
        выделен отдельной командой для явности при миграции."""
        return self.sync_reverse(entity, dry_run=dry_run)
