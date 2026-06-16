# Simplify Telegram Bot Storage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove bot user storage and dialog runtime state while keeping database-backed presets for `/quickrun` and preset management.

**Architecture:** `/run` becomes stateless: every inline keyboard callback carries a compact encoded draft using segment and stage bitmasks, so the bot no longer needs `bot_dialog_state`. `/quickrun` and `/presets` continue using `bot_presets`; `/presets save` parses explicit `key=value` launch settings and stores validated `RunConfig` JSON. Access control is handled outside the bot, so `bot_users` and roles are removed completely.

**Tech Stack:** Python, FastAPI, Supabase client, Telegram Bot API inline keyboards, pytest, SQL migrations.

---

## File Structure

- Modify `bot/dialog.py`: remove `DialogStore`, add compact callback encoder/decoder, add `apply_encoded_callback()`, and expand wizard explanations.
- Modify `bot/gateway.py`: remove `AccessStore`, remove role checks, route callbacks through `apply_encoded_callback()`, add `/start`, update `/help`, keep `PresetsStore`, and implement `/presets save/default/delete`.
- Create `bot/preset_args.py`: parse `/presets save <name> key=value...` into a validated preset config.
- Keep `bot/presets.py`: this remains the database-backed preset store.
- Delete `bot/access.py`: no `bot_users` reads or writes.
- Delete `tests/test_bot_access.py`: obsolete role/allowlist tests.
- Modify `tests/test_bot_dialog.py`: cover encoded callbacks and stateless transitions.
- Create `tests/test_bot_preset_args.py`: cover preset save argument parsing.
- Modify `tests/test_migrations.py`: add migration contract for dropping `bot_users` and `bot_dialog_state` while preserving `bot_presets`.
- Create `sql/015_drop_bot_runtime_state.sql`: drop only `bot_users` and `bot_dialog_state`.
- Modify docs: `README.md`, `docs/BOT-SETUP.md`, `docs/RUNBOOK.md`, DB audit docs.

## Target Behavior

- `/start` explains what the bot does and how it launches Claude Code Routine.
- `/help` lists all commands without roles/admin sections.
- `/whoami` returns only `chat_id`.
- `/run` opens the detailed wizard and does not read or write `bot_dialog_state`.
- `/run` callback data stays within Telegram's 64-byte limit.
- `/quickrun` uses the default row from `bot_presets`.
- `/quickrun <preset>` uses the named row from `bot_presets`.
- `/presets` lists presets.
- `/presets save <name> ...` saves a validated config to `bot_presets`.
- `/presets default <name>` changes the default preset.
- `/presets delete <name>` removes a preset.
- No runtime code references `bot_users`, `AccessStore`, or `bot_dialog_state`.

## Callback Encoding

Use a compact versioned callback payload:

```text
r1:s<segment_mask_hex>:l<limit>:g<stage_mask_hex_or_F>:d<0|1>:n<0|1>:a<action>
```

Examples:

```text
r1:s1:l30:gF:d0:n1:ast0
r1:s13:l50:g3:d1:n0:acr
```

Action codes:

- `st<idx>` toggle segment
- `sa` select all segments
- `sn` next from segment step
- `l<n>` choose limit
- `gf` choose full pipeline
- `gt<idx>` toggle stage
- `gn` next from stage step
- `fd` toggle dry-run
- `fn` toggle Notion sync
- `fx` next from flags step
- `cr` confirm run
- `ce` edit from confirmation
- `cc` cancel

## Task 1: Stateless `/run` Callback Codec

**Files:**
- Modify: `bot/dialog.py`
- Test: `tests/test_bot_dialog.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert:

```python
from bot.dialog import apply_encoded_callback, build_step_message, decode_callback


def test_run_buttons_include_compact_state_in_callback_data() -> None:
    _, keyboard = build_step_message("segments", {
        "segments": ["medical-imaging"],
        "limit_per_segment": 30,
        "stages": "full",
        "dry_run": False,
        "notion_sync": True,
    })
    callback_data = keyboard[0][0]["callback_data"]
    assert callback_data.startswith("r1:")
    assert len(callback_data.encode("utf-8")) <= 64
    decoded_draft, action = decode_callback(callback_data)
    assert decoded_draft["segments"] == ["medical-imaging"]
    assert action == "st0"


def test_apply_encoded_callback_can_confirm_run_without_store() -> None:
    _, keyboard = build_step_message("confirm", {
        "segments": ["medical-imaging"],
        "limit_per_segment": 10,
        "stages": ["discovery", "relevance"],
        "dry_run": True,
        "notion_sync": False,
    })
    next_step, draft = apply_encoded_callback(keyboard[0][0]["callback_data"])
    assert next_step == "done"
    assert draft["segments"] == ["medical-imaging"]
```

- [ ] **Step 2: Run test and verify RED**

Run: `pytest tests/test_bot_dialog.py -v`
Expected: FAIL because `apply_encoded_callback` and `decode_callback` are missing.

- [ ] **Step 3: Implement codec and encoded keyboards**

Implement `encode_callback()`, `decode_callback()`, `apply_encoded_callback()`, segment/stage bitmask helpers, and switch all inline keyboard `callback_data` fields to encoded payloads.

- [ ] **Step 4: Run test and verify GREEN**

Run: `pytest tests/test_bot_dialog.py -v`
Expected: PASS.

## Task 2: Gateway Without `bot_users` or `bot_dialog_state`

**Files:**
- Modify: `bot/gateway.py`
- Delete: `bot/access.py`
- Delete: `tests/test_bot_access.py`

- [ ] **Step 1: Remove access imports and dependency construction**

Delete `AccessStore` import. `_deps()` should return `PresetsStore(client)` and `client`, not access or dialog stores.

- [ ] **Step 2: Remove role checks**

Delete `access.is_allowed()`, `access.get_role()`, `is_admin`, and admin-only branches. `/whoami` should return only `chat_id`.

- [ ] **Step 3: Add `/start` and role-free `/help`**

Add `_start_text()` and `_help_text()` covering `/run`, `/quickrun`, `/presets`, `/status`, `/last`, `/digest`, `/hot`, `/stale`, `/settings`, `/whoami`, and `/ping`.

- [ ] **Step 4: Make callback handling stateless**

Replace `dialog.get()` and `dialog.save()` flow with:

```python
try:
    next_step, new_draft = apply_encoded_callback(data)
except ValueError:
    await tg.edit_message(chat_id, message_id, "Сессия устарела. Используйте /run заново.")
    return
```

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_bot_dialog.py tests/test_routine_fire.py -v`
Expected: PASS.

## Task 3: Keep and Improve Presets

**Files:**
- Keep: `bot/presets.py`
- Create: `bot/preset_args.py`
- Modify: `bot/gateway.py`
- Test: `tests/test_bot_preset_args.py`

- [ ] **Step 1: Write failing parser tests**

Add tests for:

```text
/presets save smoke segments=medical-imaging,generative-ai limit=10 stages=discovery,relevance dry_run=true notion_sync=false default=true
```

Expected config:

```python
{
    "segments": ["medical-imaging", "generative-ai"],
    "limit_per_segment": 10,
    "stages": ["discovery", "relevance"],
    "dry_run": True,
    "notion_sync": False,
}
```

- [ ] **Step 2: Run test and verify RED**

Run: `pytest tests/test_bot_preset_args.py -v`
Expected: FAIL because `bot.preset_args` is missing.

- [ ] **Step 3: Implement parser**

Create `parse_preset_save_args(args)` that validates through `RunConfig.validate()` and returns `(name, config, is_default)`.

- [ ] **Step 4: Wire `/presets` commands**

Support:

```text
/presets
/presets use <name>
/presets save <name> segments=<seg1,seg2> limit=<n> stages=<full|stage1,stage2> [dry_run=true|false] [notion_sync=true|false] [default=true|false]
/presets default <name>
/presets delete <name>
```

- [ ] **Step 5: Run focused tests**

Run: `pytest tests/test_bot_preset_args.py tests/test_routine_fire.py -v`
Expected: PASS.

## Task 4: Database Migration

**Files:**
- Create: `sql/015_drop_bot_runtime_state.sql`
- Modify: `sql/014_drop_pipeline_runs.sql`
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Add failing migration contract**

```python
def test_migration_015_drop_bot_runtime_state():
    sql = _read("015_drop_bot_runtime_state.sql")
    assert "DROP TABLE IF EXISTS bot_users" in sql
    assert "DROP TABLE IF EXISTS bot_dialog_state" in sql
    assert "DROP TABLE IF EXISTS bot_presets" not in sql
```

- [ ] **Step 2: Run test and verify RED**

Run: `pytest tests/test_migrations.py::test_migration_015_drop_bot_runtime_state -v`
Expected: FAIL because migration file is missing.

- [ ] **Step 3: Add migration**

```sql
-- 015_drop_bot_runtime_state.sql
-- Remove Telegram bot runtime state that is no longer read by the bot.
-- Keep bot_presets because /presets and /quickrun use it.

DROP TABLE IF EXISTS bot_users;
DROP TABLE IF EXISTS bot_dialog_state;
```

- [ ] **Step 4: Run migration tests**

Run: `pytest tests/test_migrations.py -v`
Expected: PASS.

## Task 5: Documentation

**Files:**
- Modify: `README.md`
- Modify: `docs/BOT-SETUP.md`
- Modify: `docs/RUNBOOK.md`
- Modify: `docs/DB-FIELD-AUDIT.md`
- Modify: `docs/DB-FIELD-AUDIT-2026-06-16.md`

- [ ] **Step 1: Search stale references**

Run:

```bash
rg -n "bot_users|bot_dialog_state|allowlist|admin|viewer|роль|роли" README.md docs
```

- [ ] **Step 2: Update docs**

Document that:

- `bot_users` is removed.
- `bot_dialog_state` is removed because `/run` is stateless.
- `bot_presets` is retained.
- `/presets save/default/delete` manages presets.
- `/quickrun` uses `bot_presets`.

- [ ] **Step 3: Verify references**

Run:

```bash
rg -n "bot_users|bot_dialog_state|allowlist|admin|viewer|роль|роли" README.md docs
```

Expected: no active-behavior references to removed bot runtime state.

## Task 6: Final Verification

**Files:**
- No direct file edits.

- [ ] **Step 1: Run bot-focused tests**

```bash
pytest tests/test_bot_dialog.py tests/test_bot_preset_args.py tests/test_routine_fire.py tests/test_migrations.py -v
```

Expected: PASS.

- [ ] **Step 2: Check removed runtime references**

```bash
rg -n "bot_users|bot_dialog_state|AccessStore|DialogStore" bot tests scripts agents
```

Expected: no matches except historical SQL migration text if the search includes `sql/`.

- [ ] **Step 3: Check preset references remain**

```bash
rg -n "bot_presets|PresetsStore" bot tests
```

Expected: matches in `bot/presets.py`, `bot/gateway.py`, and relevant tests.

- [ ] **Step 4: Run full test suite**

```bash
pytest
```

Expected: PASS.

## Self-Review

- Spec coverage: Covers stateless `/run`, removal of `bot_users`, removal of `bot_dialog_state`, retention of `bot_presets`, preset save/default/delete, `/start`, `/help`, migration and docs.
- Placeholder scan: No unresolved placeholders.
- Type consistency: Encoded callbacks return `(next_step, draft)` through `apply_encoded_callback()`. Preset parser returns `(name, config, is_default)` and stores configs compatible with `RunConfig.from_dict()`.
- Scope decision: This plan does not replace `bot_presets` with static quick-run profiles because the latest requirement explicitly keeps preset storage and management.
