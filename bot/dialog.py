"""Multi-step /run wizard using inline buttons.

State is persisted in bot_dialog_state table so it survives web restarts.
Each step edits the same message (no spam).

Steps: segments → limit → stages → flags → confirm
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

STEPS = ["segments", "limit", "stages", "flags", "confirm"]

ALL_SEGMENTS = [
    "medical-imaging",
    "autonomous-vehicles",
    "speech-and-audio",
    "generative-ai",
    "agriculture-ai",
    "robotics-ai",
    "video-photo-ai",
]

LIMIT_PRESETS = [10, 30, 50]


class DialogStore:
    """Persist /run wizard state in bot_dialog_state table."""

    def __init__(self, client: Any) -> None:
        self._db = client

    def get(self, chat_id: str) -> dict[str, Any] | None:
        result = (
            self._db.table("bot_dialog_state")
            .select("*")
            .eq("chat_id", chat_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def save(self, chat_id: str, step: str, draft: dict[str, Any]) -> None:
        from datetime import datetime, timezone

        self._db.table("bot_dialog_state").upsert(
            {
                "chat_id": chat_id,
                "step": step,
                "draft": draft,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="chat_id",
        ).execute()

    def clear(self, chat_id: str) -> None:
        self._db.table("bot_dialog_state").delete().eq("chat_id", chat_id).execute()


def build_step_message(step: str, draft: dict[str, Any]) -> tuple[str, list[list[dict]]]:
    """Return (text, inline_keyboard) for the given step."""
    if step == "segments":
        return _segments_step(draft)
    if step == "limit":
        return _limit_step(draft)
    if step == "stages":
        return _stages_step(draft)
    if step == "flags":
        return _flags_step(draft)
    if step == "confirm":
        return _confirm_step(draft)
    return "Неизвестный шаг", []


def apply_callback(
    step: str, draft: dict[str, Any], data: str
) -> tuple[str, dict[str, Any]]:
    """Apply a callback_data action to the draft. Returns (next_step, new_draft)."""
    draft = dict(draft)

    if step == "segments":
        if data == "seg_all":
            draft["segments"] = list(ALL_SEGMENTS)
        elif data.startswith("seg_toggle:"):
            seg = data.split(":", 1)[1]
            segs = set(draft.get("segments") or [])
            if seg in segs:
                segs.discard(seg)
            else:
                segs.add(seg)
            draft["segments"] = sorted(segs)
        elif data == "seg_next":
            return "limit", draft

    elif step == "limit":
        if data.startswith("limit:"):
            draft["limit_per_segment"] = int(data.split(":", 1)[1])
            return "stages", draft

    elif step == "stages":
        if data == "stages_full":
            draft["stages"] = "full"
            return "flags", draft
        elif data.startswith("stages_toggle:"):
            stage = data.split(":", 1)[1]
            stages = set(draft.get("stages") or [])
            if isinstance(stages, str):
                stages = set()
            if stage in stages:
                stages.discard(stage)
            else:
                stages.add(stage)
            draft["stages"] = sorted(stages)
        elif data == "stages_next":
            return "flags", draft

    elif step == "flags":
        if data == "flag_dryrun":
            draft["dry_run"] = not draft.get("dry_run", False)
        elif data == "flag_notion":
            draft["notion_sync"] = not draft.get("notion_sync", True)
        elif data == "flags_next":
            return "confirm", draft

    elif step == "confirm":
        if data == "confirm_run":
            return "done", draft
        elif data == "confirm_edit":
            return "segments", draft
        elif data == "confirm_cancel":
            return "cancelled", draft

    return step, draft


# ── Step renderers ─────────────────────────────────────────────────────────────

def _segments_step(draft: dict) -> tuple[str, list[list[dict]]]:
    selected = set(draft.get("segments") or [])
    text = "📋 <b>Шаг 1/5: Выбор сегментов</b>\nВыберите один или несколько сегментов:"
    keyboard = []
    row: list[dict] = []
    for i, seg in enumerate(ALL_SEGMENTS):
        mark = "✅" if seg in selected else "◻️"
        btn = {"text": f"{mark} {seg}", "callback_data": f"seg_toggle:{seg}"}
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([
        {"text": "🌐 Все", "callback_data": "seg_all"},
        {"text": "Далее →", "callback_data": "seg_next"},
    ])
    return text, keyboard


def _limit_step(draft: dict) -> tuple[str, list[list[dict]]]:
    segs = draft.get("segments") or []
    text = (
        f"📋 <b>Шаг 2/5: Лимит на сегмент</b>\n"
        f"Сегментов выбрано: {len(segs)}\n"
        "Выберите лимит компаний на сегмент:"
    )
    keyboard = [[
        {"text": str(n), "callback_data": f"limit:{n}"}
        for n in LIMIT_PRESETS
    ]]
    return text, keyboard


def _stages_step(draft: dict) -> tuple[str, list[list[dict]]]:
    all_stages = ["discovery", "relevance", "scoring", "enrichment", "analysis", "conclusions"]
    selected_stages = draft.get("stages") or []
    if selected_stages == "full":
        selected_stages = []
    selected_set = set(selected_stages)
    text = "📋 <b>Шаг 3/5: Стадии pipeline</b>\nПолный pipeline или выберите подмножество:"
    keyboard = [[{"text": "⚡ Полный pipeline", "callback_data": "stages_full"}]]
    row2: list[dict] = []
    for stage in all_stages:
        mark = "✅" if stage in selected_set else "◻️"
        row2.append({"text": f"{mark} {stage}", "callback_data": f"stages_toggle:{stage}"})
    keyboard.append(row2[:3])
    keyboard.append(row2[3:])
    keyboard.append([{"text": "Далее →", "callback_data": "stages_next"}])
    return text, keyboard


def _flags_step(draft: dict) -> tuple[str, list[list[dict]]]:
    dry_run = draft.get("dry_run", False)
    notion = draft.get("notion_sync", True)
    text = "📋 <b>Шаг 4/5: Флаги</b>\nДополнительные параметры запуска:"
    keyboard = [
        [
            {
                "text": ("✅ Dry-run (без записи)" if dry_run else "◻️ Dry-run"),
                "callback_data": "flag_dryrun",
            }
        ],
        [
            {
                "text": ("✅ Notion sync" if notion else "◻️ Notion sync"),
                "callback_data": "flag_notion",
            }
        ],
        [{"text": "Далее →", "callback_data": "flags_next"}],
    ]
    return text, keyboard


def _confirm_step(draft: dict) -> tuple[str, list[list[dict]]]:
    segs = ", ".join(draft.get("segments") or []) or "—"
    limit = draft.get("limit_per_segment", 30)
    stages = draft.get("stages", "full")
    stages_str = stages if isinstance(stages, str) else " → ".join(stages)
    dry_run = "✅ да" if draft.get("dry_run") else "нет"
    notion = "✅ да" if draft.get("notion_sync", True) else "нет"
    text = (
        f"📋 <b>Шаг 5/5: Подтверждение</b>\n\n"
        f"Сегменты: <b>{segs}</b>\n"
        f"Лимит: <b>{limit}</b>\n"
        f"Стадии: <b>{stages_str}</b>\n"
        f"Dry-run: {dry_run}\n"
        f"Notion sync: {notion}\n\n"
        "Запустить pipeline?"
    )
    keyboard = [
        [
            {"text": "🚀 Запустить", "callback_data": "confirm_run"},
            {"text": "✏️ Изменить", "callback_data": "confirm_edit"},
        ],
        [{"text": "❌ Отмена", "callback_data": "confirm_cancel"}],
    ]
    return text, keyboard
