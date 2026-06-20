# Design: Bot Update + `/refill` Mode for Existing Companies

**Date:** 2026-06-20  
**Status:** Approved  
**Scope:** `kvetio-agent/bot/`

---

## Context

The bot currently supports four pipeline modes (`icp_segment`, `single_company`,
`startup_research`, `retroactive`) and was recently updated to use the
routines-cleanup architecture: DB-backed dialog state (`bot_dialog_state`),
access control (`bot_users`), and named presets (`bot_presets`).

The goal is to add a fifth mode — `enrich_existing` — exposed via a new `/refill`
command. This mode runs the full pipeline **for companies already in the database
that have incomplete data**, identified by their `status` field.

---

## Data Model Foundation

The `companies` table (schema.sql, migration 018, 2026-06-19) uses a linear
status progression that maps directly to pipeline stages:

| `status`          | Stages already done             | Stages missing                                    |
|-------------------|---------------------------------|---------------------------------------------------|
| `discovered`      | —                               | relevance, scoring, enrichment, analysis, conclusions |
| `relevant`        | relevance                       | scoring, enrichment, analysis, conclusions        |
| `sources_gathered`| relevance, enrichment           | analysis, conclusions                             |
| `analyzed`        | relevance, enrichment, analysis | conclusions                                       |
| `dossier_ready`   | all                             | —                                                 |
| `not_relevant`    | relevance (failed)              | —                                                 |

Additional signal: `dm_enriched_at IS NULL` — DM contacts not yet collected,
regardless of status.

The `icp_segment` column allows filtering companies by ICP segment.

The agent running the routine reads `mode=enrich_existing` from the text payload,
queries companies by segment and non-terminal status, applies the selected stages,
and respects the per-segment limit.

---

## Architecture

### New RunMode

```python
RunMode = Literal[
    "icp_segment", "single_company", "startup_research",
    "retroactive", "enrich_existing"      # ← new
]

ENRICH_DEFAULT_STAGES = [
    "relevance", "scoring", "enrichment", "analysis", "conclusions"
]
# `discovery` is intentionally excluded: companies already exist in DB.
```

### Routine Text Format

```
mode=enrich_existing; segments=robotics-ai,medical-imaging; limit=30;
stages=enrichment,analysis,conclusions; dry_run=false; notion_sync=true
```

- `segments` is optional — empty means all segments in DB
- `stages` is a subset of `ENRICH_DEFAULT_STAGES`
- The agent filters: `status NOT IN ('not_relevant', 'dossier_ready')`

### Dialog State

`draft` dict gains `"run_mode": "enrich_existing"`. Stored in existing
`bot_dialog_state.draft` (JSONB) — no schema changes needed.

---

## Components

### 1. `bot/config.py`

- Add `"enrich_existing"` to `RunMode` literal
- Add `ENRICH_DEFAULT_STAGES` constant
- Add validation branch in `RunConfig.validate()`:
  - `segments` optional (empty list = all segments)
  - `stages` must be non-empty subset of `ENRICH_DEFAULT_STAGES`
  - `limit_per_segment` 1–200
- Add `enrich_existing` to `config_to_text()` in `bot/routine.py`

### 2. `bot/routine.py`

New branch in `config_to_text()`:

```python
if cfg.run_mode == "enrich_existing":
    segs = cfg.segments  # empty = agent takes all
    stages = cfg.stages if cfg.stages == "full" else ",".join(cfg.stages)
    parts = [
        "mode=enrich_existing",
        f"segments={','.join(segs)}" if segs else "segments=",
        f"limit={cfg.limit_per_segment}",
        f"stages={stages}",
        f"dry_run={'true' if cfg.dry_run else 'false'}",
        f"notion_sync={'true' if cfg.notion_sync else 'false'}",
    ]
    return "; ".join(parts)
```

### 3. `bot/dialog.py`

New function `build_enrich_step_message(step, draft)` — mirrors
`build_step_message` with three differences:

**Шаг 1 (segments):**
- Text: «Выберите сегменты для фильтрации. Пустой выбор = все компании в БД.»
- Button «🌐 Все» still works; «Далее →» valid even with empty selection

**Шаг 3 (stages):**
- `discovery` absent from the list
- Default: all 5 `ENRICH_DEFAULT_STAGES` pre-selected
- Text: «`discovery` пропускается — компании уже в базе.»

**Шаг 5 (confirm):**
- Header: «Дозаполнение существующих компаний»
- Shows segments (or «все сегменты» if empty)

Callback routing: in `_handle_callback`, check `draft.get("run_mode")` and
dispatch to `build_enrich_step_message` vs `build_step_message`.

### 4. `bot/gateway.py`

New command `/refill` (admin only):

```python
elif command == "/refill":
    if not is_admin:
        await tg.send(chat_id, "⛔ Только администраторы могут запускать pipeline")
        return
    dialog.clear(chat_id)
    from bot.config import ENRICH_DEFAULT_STAGES
    draft = {
        "run_mode": "enrich_existing",
        "segments": [],
        "limit_per_segment": 30,
        "stages": list(ENRICH_DEFAULT_STAGES),
        "dry_run": False,
        "notion_sync": True,
    }
    dialog.save(chat_id, "segments", draft)
    text_out, keyboard = build_enrich_step_message("segments", draft)
    await tg.send_with_keyboard(chat_id, text_out, keyboard)
```

Import `build_enrich_step_message` at top of file.
Add `/refill` to `/help` admin block.

### 5. `bot/scenarios.py`

New scenario for NLP `/ask`:

```python
"enrich_existing": ScenarioSpec(
    name="Дозаполнение существующих",
    description=(
        "Полный pipeline (без discovery) для компаний, "
        "уже в БД, с пропущенными данными"
    ),
    required_params=[],
    optional_params=["segments", "limit_per_segment", "stages", "dry_run", "notion_sync"],
    param_descriptions={
        "segments": "CSV сегментов; пусто = все сегменты в БД",
        "limit_per_segment": "максимум компаний на сегмент (1-200), по умолчанию 30",
        "stages": "relevance, scoring, enrichment, analysis, conclusions",
        "dry_run": "true/false, по умолчанию false",
        "notion_sync": "true/false, по умолчанию true",
    },
    defaults={
        "segments": [],
        "limit_per_segment": 30,
        "stages": ["relevance", "scoring", "enrichment", "analysis", "conclusions"],
        "dry_run": False,
        "notion_sync": True,
    },
),
```

---

## User Flow

```
/refill
  → Шаг 1/5: Сегменты
      (пустой = все компании в БД)
  → Шаг 2/5: Лимит на сегмент (10 / 30 / 50)
  → Шаг 3/5: Стадии
      (дефолт: все 5; discovery отсутствует)
  → Шаг 4/5: Флаги (dry-run, notion_sync)
  → Шаг 5/5: Подтверждение
      «Дозаполнение существующих компаний»
      → 🚀 Запустить → fire(config_to_text(cfg))
```

---

## What Is NOT in Scope

- Agent-side logic (how it queries companies with missing data from Supabase)
- New Supabase tables — none needed
- Changes to `bot_dialog_state`, `bot_users`, `bot_presets` schema
- Removal of any existing modes (`retroactive` stays as-is)

---

## Files Changed

| File | Change |
|---|---|
| `bot/config.py` | Add `enrich_existing` to `RunMode`; add `ENRICH_DEFAULT_STAGES`; add validation branch |
| `bot/routine.py` | Add `enrich_existing` branch in `config_to_text()` |
| `bot/dialog.py` | Add `build_enrich_step_message()`; update callback routing |
| `bot/gateway.py` | Add `/refill` command; import `build_enrich_step_message`; update `/help` |
| `bot/scenarios.py` | Add `enrich_existing` scenario spec |

---

## Error Handling

- `/refill` with empty segments and stages=[] → `validate()` raises `ValueError`
  (stages must be non-empty), bot responds with `❌ Ошибка конфига`
- Stale session (dialog cleared): same as `/run` — «Сессия истекла. Используйте /refill заново.»
- `fire()` error path: unchanged from existing `/run` flow

---

## Testing

- Unit tests for new `validate()` branch in `test_bot_config.py` (or existing test file)
- Unit tests for `build_enrich_step_message()` step rendering
- Unit tests for `config_to_text()` with `run_mode=enrich_existing`
- Integration: callback routing with `run_mode` in draft
