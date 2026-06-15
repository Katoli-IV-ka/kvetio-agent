"""Pipeline run worker — polls queued runs, triggers the agent, collects Summary.

Run as a separate process:
    python -m bot.worker

Environment variables:
    SUPABASE_URL, SUPABASE_KEY
    ANTHROPIC_API_KEY
    INTERNAL_API_TOKEN
    KVETIO_LOG_LEVEL (default: INFO)
    WORKER_POLL_INTERVAL_SEC (default: 10)
    WORKER_HEARTBEAT_SEC (default: 30)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from supabase import create_client, Client

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

load_dotenv(ROOT / ".env")

logger = logging.getLogger(__name__)

POLL_INTERVAL = int(os.environ.get("WORKER_POLL_INTERVAL_SEC", "10"))
HEARTBEAT_INTERVAL = int(os.environ.get("WORKER_HEARTBEAT_SEC", "30"))


def _make_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def _build_agent_prompt(config: dict[str, Any], run_id: str) -> str:
    """Inject RunConfig into pipeline_task.md template as a parameter block."""
    template_path = ROOT / "agents" / "prompts" / "pipeline_task.md"
    try:
        template = template_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        template = "Run pipeline with the following configuration."

    segments = ", ".join(config.get("segments", []))
    limit = config.get("limit_per_segment", 30)
    stages = config.get("stages", "full")
    dry_run = config.get("dry_run", False)
    notion_sync = config.get("notion_sync", True)

    if stages == "full":
        stages_str = "full pipeline (all stages)"
    else:
        stages_str = " → ".join(stages)

    header = f"""<!-- INJECTED BY WORKER — run_id: {run_id} -->
PIPELINE RUN CONFIGURATION:
- run_id: {run_id}
- segments: {segments}
- limit_per_segment: {limit}
- stages: {stages_str}
- dry_run: {dry_run}
- notion_sync: {notion_sync}

"""
    return header + template


def _trigger_agent(prompt: str, run_id: str) -> tuple[bool, str]:
    """Trigger Claude Code headless with the pipeline prompt.

    Returns (success, output_or_error).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return False, "ANTHROPIC_API_KEY not set"

    prompt_file = ROOT / "data" / f"run_{run_id}_prompt.md"
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt, encoding="utf-8")

    try:
        result = subprocess.run(
            ["claude", "--print", "--dangerously-skip-permissions", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=3600,  # 1 hour max
            cwd=str(ROOT),
            env={**os.environ, "ANTHROPIC_API_KEY": api_key},
        )
        prompt_file.unlink(missing_ok=True)
        if result.returncode != 0:
            return False, result.stderr[:2000] or "non-zero exit"
        return True, result.stdout
    except subprocess.TimeoutExpired:
        prompt_file.unlink(missing_ok=True)
        return False, "agent timed out after 1 hour"
    except FileNotFoundError:
        prompt_file.unlink(missing_ok=True)
        return False, "claude CLI not found — check PATH"


def _collect_summary(
    client: Client, run_id: str, config: dict[str, Any], started_at: str
) -> dict[str, Any]:
    """Aggregate run results from run_logs and companies tables."""
    from datetime import datetime, timezone, timedelta

    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        started = datetime.now(timezone.utc) - timedelta(hours=1)

    logs = (
        client.table("run_logs")
        .select("stage,segment,status,companies_found,companies_qualified,error")
        .gte("created_at", started.isoformat())
        .execute()
    )
    rows = logs.data or []

    total_found = sum(r.get("companies_found") or 0 for r in rows)
    total_qualified = sum(r.get("companies_qualified") or 0 for r in rows)
    errors = [r for r in rows if r.get("error")]

    hot_leads: list[dict[str, Any]] = []
    try:
        hot_result = (
            client.table("companies")
            .select("name,domain,score,score_bucket,icp_segment")
            .eq("score_bucket", "Hot")
            .order("score", desc=True)
            .limit(5)
            .execute()
        )
        hot_leads = hot_result.data or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("Could not fetch hot leads for summary: %s", exc)

    return {
        "run_id": run_id,
        "found": total_found,
        "qualified": total_qualified,
        "errors": len(errors),
        "error_details": [
            {"stage": e.get("stage"), "segment": e.get("segment"), "error": e.get("error")}
            for e in errors[:5]
        ],
        "hot_leads": hot_leads[:5],
        "segments": config.get("segments", []),
    }


def _notify_summary(client: Client, run: dict[str, Any], summary: dict[str, Any]) -> None:
    """Fan-out pipeline summary to all active bot_users."""
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        return

    users = client.table("bot_users").select("chat_id").eq("active", True).execute()
    chats = [u["chat_id"] for u in (users.data or [])]

    # Also always notify the triggering chat if set
    tg_chat = run.get("tg_chat_id")
    if tg_chat and tg_chat not in chats:
        chats.append(tg_chat)

    if not chats:
        return

    msg = _format_summary_message(run, summary)
    api_url = f"https://api.telegram.org/bot{token}/sendMessage"

    for chat_id in chats:
        tg_msg_id = run.get("tg_message_id") if chat_id == tg_chat else None
        if tg_msg_id:
            # Edit the live message
            edit_url = f"https://api.telegram.org/bot{token}/editMessageText"
            try:
                httpx.post(
                    edit_url,
                    json={
                        "chat_id": chat_id,
                        "message_id": tg_msg_id,
                        "text": msg,
                        "parse_mode": "HTML",
                    },
                    timeout=10,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("editMessageText failed for %s: %s", chat_id, exc)
        else:
            try:
                httpx.post(
                    api_url,
                    json={"chat_id": chat_id, "text": msg, "parse_mode": "HTML"},
                    timeout=10,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("sendMessage failed for %s: %s", chat_id, exc)


def _format_summary_message(run: dict[str, Any], summary: dict[str, Any]) -> str:
    run_id_short = str(run.get("id", "?"))[:8]
    trigger = run.get("trigger_type", "manual")
    triggered_by = run.get("triggered_by", "")
    segments = ", ".join(summary.get("segments", []))
    found = summary.get("found", 0)
    qualified = summary.get("qualified", 0)
    errors = summary.get("errors", 0)
    status_icon = "✅" if errors == 0 else "⚠️"

    started = run.get("started_at", "")
    finished = run.get("finished_at", "")
    duration = ""
    if started and finished:
        try:
            from datetime import datetime
            s = datetime.fromisoformat(started.replace("Z", "+00:00"))
            f = datetime.fromisoformat(finished.replace("Z", "+00:00"))
            secs = int((f - s).total_seconds())
            duration = f" · {secs // 60}m {secs % 60}s"
        except Exception:  # noqa: BLE001
            pass

    lines = [
        f"{status_icon} <b>Pipeline завершён</b> · ран {run_id_short}{duration}",
        f"Триггер: {trigger}" + (f" ({triggered_by})" if triggered_by else ""),
        f"Сегменты: {segments}",
        "",
        f"Найдено: {found} · qualified: {qualified} · ошибок: {errors}",
    ]

    hot_leads = summary.get("hot_leads", [])
    if hot_leads:
        lines.append("")
        lines.append("🔥 <b>Топ Hot:</b>")
        for i, lead in enumerate(hot_leads[:5], 1):
            score = lead.get("score", 0)
            domain = lead.get("domain", "")
            seg = lead.get("icp_segment", "")
            lines.append(f"{i}. {domain} — {score}" + (f" ({seg})" if seg else ""))

    error_details = summary.get("error_details", [])
    if error_details:
        lines.append("")
        lines.append(f"⚠️ <b>Ошибки ({errors}):</b>")
        for e in error_details[:3]:
            stage = e.get("stage", "?")
            seg = e.get("segment", "?")
            err = (e.get("error") or "")[:60]
            lines.append(f"  {stage}/{seg} — {err}")

    lines.append("")
    lines.append(f"🔗 run_id: <code>{run.get('id', '?')}</code> · /last для истории")
    return "\n".join(lines)


def run_worker_loop() -> None:
    """Main worker loop: poll → start → trigger agent → finish."""
    from bot.runs import RunsStore

    client = _make_client()
    store = RunsStore(client)

    logger.info("Worker started (poll=%ds, heartbeat=%ds)", POLL_INTERVAL, HEARTBEAT_INTERVAL)

    while True:
        try:
            run = store.try_start_next()
            if run:
                _process_run(client, store, run)
        except Exception as exc:  # noqa: BLE001
            logger.error("Worker loop error: %s", exc, exc_info=True)
        time.sleep(POLL_INTERVAL)


def _process_run(client: Client, store: "RunsStore", run: dict[str, Any]) -> None:
    run_id = run["id"]
    config = run.get("config") or {}

    logger.info("Processing run %s", run_id)
    _send_live_message(client, run, "🔵 <b>Выполняется...</b>\n" + _run_header(run))

    prompt = _build_agent_prompt(config, run_id)

    # Heartbeat in background thread
    import threading
    stop_event = threading.Event()

    def _heartbeat_loop() -> None:
        while not stop_event.is_set():
            try:
                store.heartbeat(run_id)
            except Exception:  # noqa: BLE001
                pass
            stop_event.wait(HEARTBEAT_INTERVAL)

    hb_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    hb_thread.start()

    try:
        success, output = _trigger_agent(prompt, run_id)
    finally:
        stop_event.set()
        hb_thread.join(timeout=5)

    # Re-fetch run to get accurate started_at
    run_fresh = store.get(run_id) or run

    if success:
        summary = _collect_summary(client, run_id, config, run_fresh.get("started_at", ""))
        store.finish(run_id, summary)
        run_done = store.get(run_id) or run_fresh
        _notify_summary(client, run_done, summary)
    else:
        store.fail(run_id, output)
        _send_live_message(
            client, run, f"❌ <b>Ошибка рана {run_id[:8]}</b>\n<code>{output[:500]}</code>"
        )


def _run_header(run: dict[str, Any]) -> str:
    run_id_short = str(run.get("id", "?"))[:8]
    config = run.get("config") or {}
    segments = ", ".join(config.get("segments", []))
    limit = config.get("limit_per_segment", 30)
    return f"Ран: <code>{run_id_short}</code>\nСегменты: {segments} (limit {limit})"


def _send_live_message(client: Client, run: dict[str, Any], text: str) -> None:
    import httpx

    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = run.get("tg_chat_id")
    if not token or not chat_id:
        return

    msg_id = run.get("tg_message_id")
    if msg_id:
        url = f"https://api.telegram.org/bot{token}/editMessageText"
        payload = {
            "chat_id": chat_id,
            "message_id": msg_id,
            "text": text,
            "parse_mode": "HTML",
        }
    else:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}

    try:
        resp = httpx.post(url, json=payload, timeout=10)
        if msg_id is None and resp.is_success:
            new_msg_id = resp.json().get("result", {}).get("message_id")
            if new_msg_id:
                from bot.runs import RunsStore
                RunsStore(client).set_tg_message_id(run["id"], new_msg_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to send/edit live message: %s", exc)


if __name__ == "__main__":
    level = os.environ.get("KVETIO_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    run_worker_loop()
