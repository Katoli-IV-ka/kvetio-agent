"""Multi-step /run wizard using inline buttons.

State is encoded into compact Telegram callback_data payloads.
Each step edits the same message (no spam).

Steps: segments → limit → stages → flags → confirm
"""

from __future__ import annotations

import logging
from typing import Any

from bot.config import DEFAULT_LIMIT_PER_SEGMENT

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

ALL_STAGES = ["discovery", "relevance", "scoring", "enrichment", "analysis", "conclusions"]
LIMIT_PRESETS = [5, 10, 30]


def encode_callback(draft: dict[str, Any], action: str) -> str:
    """Encode current /run draft and action into Telegram's 64-byte callback limit."""
    segments_mask = _segments_to_mask(draft.get("segments") or [])
    stages = draft.get("stages", "full")
    stages_value = "F" if stages == "full" else format(_stages_to_mask(stages or []), "x")
    limit = int(draft.get("limit_per_segment", DEFAULT_LIMIT_PER_SEGMENT))
    dry_run = "1" if draft.get("dry_run", False) else "0"
    notion_sync = "1" if draft.get("notion_sync", True) else "0"
    payload = (
        f"r1:s{segments_mask:x}:l{limit}:g{stages_value}:"
        f"d{dry_run}:n{notion_sync}:a{action}"
    )
    if len(payload.encode("utf-8")) > 64:
        raise ValueError("callback payload is too large")
    return payload


def decode_callback(data: str) -> tuple[dict[str, Any], str]:
    """Decode a compact /run callback payload into (draft, action)."""
    try:
        parts = data.split(":")
        if parts[0] != "r1":
            raise ValueError("unsupported callback version")
        values = {part[0]: part[1:] for part in parts[1:] if part}
        action = values["a"]
        stages_raw = values["g"]
        stages: str | list[str]
        if stages_raw == "F":
            stages = "full"
        else:
            stages = _mask_to_stages(int(stages_raw, 16))
        draft = {
            "segments": _mask_to_segments(int(values["s"], 16)),
            "limit_per_segment": int(values["l"]),
            "stages": stages,
            "dry_run": values["d"] == "1",
            "notion_sync": values["n"] == "1",
        }
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError("invalid run callback data") from exc
    return draft, action


def apply_encoded_callback(data: str) -> tuple[str, dict[str, Any]]:
    """Apply encoded callback_data from a /run inline button."""
    draft, action = decode_callback(data)
    step, legacy_action = _decode_action(action)
    return apply_callback(step, draft, legacy_action)


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


def _decode_action(action: str) -> tuple[str, str]:
    if action == "sa":
        return "segments", "seg_all"
    if action == "sn":
        return "segments", "seg_next"
    if action.startswith("st"):
        idx = int(action[2:])
        return "segments", f"seg_toggle:{ALL_SEGMENTS[idx]}"
    if action.startswith("l"):
        return "limit", f"limit:{int(action[1:])}"
    if action == "gf":
        return "stages", "stages_full"
    if action == "gn":
        return "stages", "stages_next"
    if action.startswith("gt"):
        idx = int(action[2:])
        return "stages", f"stages_toggle:{ALL_STAGES[idx]}"
    if action == "fd":
        return "flags", "flag_dryrun"
    if action == "fn":
        return "flags", "flag_notion"
    if action == "fx":
        return "flags", "flags_next"
    if action == "cr":
        return "confirm", "confirm_run"
    if action == "ce":
        return "confirm", "confirm_edit"
    if action == "cc":
        return "confirm", "confirm_cancel"
    raise ValueError("unknown run callback action")


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
            current_stages = draft.get("stages") or []
            if isinstance(current_stages, str):
                stages = set()
            else:
                stages = set(current_stages)
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
    text = (
        "📋 <b>Шаг 1/5: Выбор сегментов</b>\n"
        "Сегменты — это ICP-направления и рынки, по которым агент будет искать и квалифицировать компании.\n"
        "Выберите один или несколько сегментов:"
    )
    keyboard = []
    row: list[dict] = []
    for i, seg in enumerate(ALL_SEGMENTS):
        mark = "✅" if seg in selected else "◻️"
        btn = {"text": f"{mark} {seg}", "callback_data": encode_callback(draft, f"st{i}")}
        row.append(btn)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([
        {"text": "🌐 Все", "callback_data": encode_callback(draft, "sa")},
        {"text": "Далее →", "callback_data": encode_callback(draft, "sn")},
    ])
    return text, keyboard


def _limit_step(draft: dict) -> tuple[str, list[list[dict]]]:
    segs = draft.get("segments") or []
    text = (
        f"📋 <b>Шаг 2/5: Лимит на сегмент</b>\n"
        f"Сегментов выбрано: {len(segs)}\n"
        "Лимит задает максимум компаний на каждый выбранный сегмент. Чем выше лимит, тем дольше прогон и тем больше записей может попасть в обработку.\n"
        "Выберите лимит компаний на сегмент:"
    )
    keyboard = [[
        {"text": str(n), "callback_data": encode_callback(draft, f"l{n}")}
        for n in LIMIT_PRESETS
    ]]
    return text, keyboard


def _stages_step(draft: dict) -> tuple[str, list[list[dict]]]:
    selected_stages = draft.get("stages") or []
    if selected_stages == "full":
        selected_stages = []
    selected_set = set(selected_stages)
    text = (
        "📋 <b>Шаг 3/5: Стадии pipeline</b>\n"
        "Полный pipeline запускает все этапы. Можно выбрать подмножество, если нужен частичный прогон.\n\n"
        "discovery — найти компании и первичные сигналы\n"
        "relevance — проверить соответствие ICP\n"
        "scoring — рассчитать приоритет\n"
        "enrichment — собрать источники и контакты\n"
        "analysis — подготовить аналитические заметки\n"
        "conclusions — собрать выводы и витрину\n\n"
        "Выберите режим:"
    )
    keyboard = [[{"text": "⚡ Полный pipeline", "callback_data": encode_callback(draft, "gf")}]]
    row2: list[dict] = []
    for i, stage in enumerate(ALL_STAGES):
        mark = "✅" if stage in selected_set else "◻️"
        row2.append({"text": f"{mark} {stage}", "callback_data": encode_callback(draft, f"gt{i}")})
    keyboard.append(row2[:3])
    keyboard.append(row2[3:])
    keyboard.append([{"text": "Далее →", "callback_data": encode_callback(draft, "gn")}])
    return text, keyboard


def _flags_step(draft: dict) -> tuple[str, list[list[dict]]]:
    dry_run = draft.get("dry_run", False)
    notion = draft.get("notion_sync", True)
    text = (
        "📋 <b>Шаг 4/5: Флаги</b>\n"
        "Dry-run — проверочный запуск без боевых записей там, где этап поддерживает сухой режим.\n"
        "Notion sync — обновлять Notion-витрину после обработки данных.\n"
        "Выберите дополнительные параметры запуска:"
    )
    keyboard = [
        [
            {
                "text": ("✅ Dry-run (без записи)" if dry_run else "◻️ Dry-run"),
                "callback_data": encode_callback(draft, "fd"),
            }
        ],
        [
            {
                "text": ("✅ Notion sync" if notion else "◻️ Notion sync"),
                "callback_data": encode_callback(draft, "fn"),
            }
        ],
        [{"text": "Далее →", "callback_data": encode_callback(draft, "fx")}],
    ]
    return text, keyboard


def _confirm_step(draft: dict) -> tuple[str, list[list[dict]]]:
    segs = ", ".join(draft.get("segments") or []) or "—"
    limit = draft.get("limit_per_segment", DEFAULT_LIMIT_PER_SEGMENT)
    stages = draft.get("stages", "full")
    stages_str = stages if isinstance(stages, str) else " → ".join(stages)
    dry_run = "✅ да" if draft.get("dry_run") else "нет"
    notion = "✅ да" if draft.get("notion_sync", True) else "нет"
    text = (
        f"📋 <b>Шаг 5/5: Подтверждение</b>\n\n"
        "Проверьте параметры перед отправкой запуска в Claude Code Routine.\n\n"
        f"Сегменты: <b>{segs}</b>\n"
        f"Лимит: <b>{limit}</b>\n"
        f"Стадии: <b>{stages_str}</b>\n"
        f"Dry-run: {dry_run}\n"
        f"Notion sync: {notion}\n\n"
        "Запустить pipeline?"
    )
    keyboard = [
        [
            {"text": "🚀 Запустить", "callback_data": encode_callback(draft, "cr")},
            {"text": "✏️ Изменить", "callback_data": encode_callback(draft, "ce")},
        ],
        [{"text": "❌ Отмена", "callback_data": encode_callback(draft, "cc")}],
    ]
    return text, keyboard


def _segments_to_mask(segments: list[str]) -> int:
    selected = set(segments)
    mask = 0
    for i, segment in enumerate(ALL_SEGMENTS):
        if segment in selected:
            mask |= 1 << i
    return mask


def _mask_to_segments(mask: int) -> list[str]:
    return [segment for i, segment in enumerate(ALL_SEGMENTS) if mask & (1 << i)]


def _stages_to_mask(stages: list[str]) -> int:
    selected = set(stages)
    mask = 0
    for i, stage in enumerate(ALL_STAGES):
        if stage in selected:
            mask |= 1 << i
    return mask


def _mask_to_stages(mask: int) -> list[str]:
    return [stage for i, stage in enumerate(ALL_STAGES) if mask & (1 << i)]
