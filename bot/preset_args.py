"""Argument parsing for Telegram preset commands."""

from __future__ import annotations

from bot.config import RunConfig


def parse_preset_save_args(args: list[str]) -> tuple[str, dict, bool]:
    """Parse `/presets save <name> key=value...` arguments."""
    if len(args) < 2 or args[0].lower() != "save":
        raise ValueError(_usage())

    name = args[1]
    values: dict[str, str] = {}
    for token in args[2:]:
        if "=" not in token:
            raise ValueError(_usage())
        key, value = token.split("=", 1)
        values[key.strip().lower()] = value.strip()

    segments = _split_csv(values.get("segments", ""))
    stages_raw = values.get("stages", "full")
    stages: str | list[str] = "full" if stages_raw == "full" else _split_csv(stages_raw)
    limit = int(values.get("limit", values.get("limit_per_segment", "30")))
    dry_run = _parse_bool(values.get("dry_run", "false"))
    notion_sync = _parse_bool(values.get("notion_sync", "true"))
    is_default = _parse_bool(values.get("default", "false"))

    cfg = RunConfig(
        segments=segments,
        limit_per_segment=limit,
        stages=stages,
        dry_run=dry_run,
        notion_sync=notion_sync,
    )
    cfg.validate()
    config = cfg.to_dict()
    config.pop("triggered_by", None)
    config.pop("trigger_type", None)
    return name, config, is_default


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in ("1", "true", "yes", "y", "on"):
        return True
    if normalized in ("0", "false", "no", "n", "off"):
        return False
    raise ValueError(f"invalid boolean value: {value}")


def _usage() -> str:
    return (
        "Usage: /presets save <name> segments=<seg1,seg2> "
        "limit=<n> stages=<full|stage1,stage2> "
        "[dry_run=true|false] [notion_sync=true|false] [default=true|false]"
    )
