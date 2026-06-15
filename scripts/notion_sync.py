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
    "phone_number", "relation",
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
    "phone_number": {"phone_number": {}},
    "relation": {"relation": {}},
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
    if notion_type == "phone_number":
        return {"phone_number": value if value else None}
    if notion_type == "relation":
        page_ids = value or []
        return {"relation": [{"id": pid} for pid in page_ids]}
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
    if notion_type == "phone_number":
        return prop.get("phone_number")
    if notion_type == "relation":
        return [item["id"] for item in prop.get("relation", [])]
    raise ValueError(f"unsupported notion_type: {notion_type}")


def md_to_blocks(heading: str, body: str) -> list[dict]:
    """Минимальный рендер: heading_2 + по абзацу paragraph на каждый блок текста."""
    blocks = [{
        "object": "block", "type": "heading_2",
        "heading_2": {"rich_text": [{"type": "text", "text": {"content": heading}}]},
    }]
    for para in [p.strip() for p in (body or "").split("\n\n") if p.strip()]:
        blocks.append({
            "object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": para}}]},
        })
    return blocks


def enrich_contact_rows(rows: list[dict], db) -> list[dict]:
    """Добавляет company_page_ids к каждой строке контакта.

    Делает два запроса:
      1. contact_companies → строит mapping contact_id -> [domain]
      2. companies -> строит mapping domain -> notion_page_id

    Используется в sync_forward для entity='contacts'.
    """
    contact_companies = db.fetch("contact_companies")
    companies = db.fetch("companies")

    page_id_by_domain: dict[str, str] = {
        c["domain"]: c["notion_page_id"]
        for c in companies
        if c.get("notion_page_id")
    }

    domains_by_contact: dict[str, list[str]] = {}
    for cc in contact_companies:
        cid = cc["contact_id"]
        domains_by_contact.setdefault(cid, []).append(cc["company_domain"])

    enriched = []
    for row in rows:
        domains = domains_by_contact.get(row.get("id", ""), [])
        page_ids = [page_id_by_domain[d] for d in domains if d in page_id_by_domain]
        enriched.append({**row, "company_page_ids": page_ids})
    return enriched


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
        if entity == "contacts":
            rows = enrich_contact_rows(rows, self.db)
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

    def sync_dossiers(self, dry_run=False) -> dict:
        """Пишет summary_md + audit_md в тело страницы компании."""
        companies = {c["domain"]: c for c in self.db.fetch("companies")
                     if c.get("notion_page_id")}
        dossiers = self.db.fetch("dossiers")
        updated = errors = 0
        for d in dossiers:
            company = companies.get(d["company_domain"])
            if not company:
                continue
            try:
                blocks = []
                if d.get("summary_md"):
                    blocks += md_to_blocks("Досье — саммари", d["summary_md"])
                if d.get("audit_md"):
                    blocks += md_to_blocks("Аудит", d["audit_md"])
                if blocks and not dry_run:
                    self.notion.append_children(company["notion_page_id"], blocks)
                if blocks:
                    updated += 1
            except Exception as exc:  # noqa: BLE001
                logger.error("dossier %s: %s", d["company_domain"], exc)
                errors += 1
        return {"entity": "dossiers", "updated": updated, "errors": errors}

    def list_fields(self, entity) -> str:
        lines = [f"# {entity}"]
        for f in self._cfg(entity)["fields"]:
            lines.append(f"  {f['db_column']:<16} -> {f['notion_property']:<18} "
                         f"[{f['notion_type']}, {f['direction']}]")
        return "\n".join(lines)


def _make_notion() -> NotionGateway:
    from notion_client import Client  # noqa: PLC0415
    token = os.environ.get("NOTION_TOKEN")
    if not token:
        raise RuntimeError("NOTION_TOKEN не задан в .env")
    return NotionGateway(Client(auth=token))


def _make_db() -> DbGateway:
    from supabase import create_client  # noqa: PLC0415
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("SUPABASE_URL и SUPABASE_KEY должны быть в .env")
    return DbGateway(create_client(url, key))


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Supabase ↔ Notion sync")
    p.add_argument("--entity", choices=["companies", "contacts", "dossiers"])
    p.add_argument("--forward", action="store_true")
    p.add_argument("--reverse", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--ensure-schema", dest="ensure_schema", action="store_true")
    p.add_argument("--validate", action="store_true")
    p.add_argument("--backfill", action="store_true")
    p.add_argument("--prune", action="store_true",
                   help="(зарезервировано) удалять свойства Notion вне конфига")
    p.add_argument("--list-fields", dest="list_fields", action="store_true")
    p.add_argument("--dry-run", dest="dry_run", action="store_true")
    return p


def main(argv=None) -> int:
    logging.basicConfig(level=os.environ.get("KVETIO_LOG_LEVEL", "INFO"))
    args = build_arg_parser().parse_args(argv)
    mapping = load_mapping()

    if args.validate:
        errors = validate_mapping(mapping)
        if errors:
            print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False))
            return 1
        print(json.dumps({"valid": True}, ensure_ascii=False))
        return 0

    if args.list_fields:
        sync = NotionSync(notion=None, db=None, mapping=mapping)
        print(sync.list_fields(args.entity))
        return 0

    sync = NotionSync(notion=_make_notion(), db=_make_db(), mapping=mapping)

    if args.entity == "dossiers":
        result = sync.sync_dossiers(dry_run=args.dry_run)
    elif args.ensure_schema:
        result = sync.ensure_schema(args.entity, dry_run=args.dry_run)
    elif args.backfill:
        result = sync.backfill(args.entity, dry_run=args.dry_run)
    elif args.reverse:
        result = sync.sync_reverse(args.entity, dry_run=args.dry_run)
    elif args.forward:
        result = sync.sync_forward(args.entity, dry_run=args.dry_run)
    else:  # --all (default)
        result = sync.sync_all(args.entity, dry_run=args.dry_run)

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
