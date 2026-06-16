# Telegram Rich Agent Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the final plain Telegram pipeline summary with segmented Rich Messages where each researched company is an expandable details block.

**Architecture:** Keep the existing routine-owned notification flow: `agents/prompts/pipeline_task.md` calls `scripts/notify.py` as the final step. Add a focused rich-summary builder that turns a structured JSON payload into one or more Telegram Bot API 10.1 `sendRichMessage` payloads, with deterministic splitting by segment, company, character count, and block count.

**Tech Stack:** Python 3.11, `httpx`, `pytest`, Telegram Bot API 10.1 `sendRichMessage`, Supabase data already surfaced by the pipeline agent.

---

## References And Constraints

- Telegram Bot API 10.1 added Rich Messages on 2026-06-11: `sendRichMessage`, `InputRichMessage`, and `RichBlockDetails`.
- Use official docs: `https://core.telegram.org/bots/api#sendrichmessage`, `https://core.telegram.org/bots/api#inputrichmessage`, `https://core.telegram.org/bots/api#richblockdetails`.
- Rich Message limits from Telegram:
  - maximum `32768` UTF-8 characters;
  - maximum `500` blocks, including nested blocks and details blocks;
  - maximum `16` nested levels.
- Use internal conservative budgets:
  - `MAX_RICH_CHARS = 30000`;
  - `MAX_RICH_BLOCKS = 450`;
  - `MAX_COMPANY_SUMMARY_CHARS = 2400`.
- Fallback must keep working: if `sendRichMessage` fails, send a compact `sendMessage` HTML summary.

## File Structure

- Create `scripts/telegram_rich_summary.py`
  - Owns data normalization, HTML escaping, rich HTML rendering, budget calculation, and message splitting.
  - Does not call Telegram directly.
- Modify `scripts/notify.py`
  - Adds `send_rich_html()`.
  - Adds `notify_pipeline_rich_summary()`.
  - Adds CLI input from a JSON file or stdin.
  - Preserves existing `send()`, `notify_run_summary()`, and `notify_pipeline_summary()` behavior.
- Modify `agents/prompts/pipeline_task.md`
  - Changes final notification instructions from a flat `--run-summary` payload to a rich summary JSON payload.
- Create `tests/test_telegram_rich_summary.py`
  - Unit tests for escaping, rendering, truncation, segmentation, and splitting.
- Create `tests/test_notify_rich_summary.py`
  - Tests Telegram API payloads, success counting, and fallback behavior.
- Optionally modify `README.md`
  - Add one short note documenting the new rich final notification path.

---

### Task 1: Add Failing Tests For Rich Summary Rendering

**Files:**
- Create: `tests/test_telegram_rich_summary.py`
- Create later: `scripts/telegram_rich_summary.py`

- [ ] **Step 1: Write tests for HTML escaping, details blocks, and segment heading**

Create `tests/test_telegram_rich_summary.py` with:

```python
from telegram_rich_summary import build_rich_summary_messages


def test_builds_details_per_company_and_escapes_html() -> None:
    payload = {
        "run_id": "1234567890abcdef",
        "trigger_type": "manual",
        "segments": ["medical-imaging"],
        "found": 1,
        "qualified": 1,
        "dossier_ready": 1,
        "errors": 0,
        "companies": [
            {
                "name": "Alpha <Vision>",
                "domain": "alpha.ai",
                "icp_segment": "medical-imaging",
                "score": 84,
                "status": "dossier_ready",
                "summary_md": "Builds AI tools for radiology & triage.",
                "latest_signal": "new FDA workflow",
                "notion_url": "https://notion.so/alpha",
            }
        ],
    }

    messages = build_rich_summary_messages(payload)

    assert len(messages) == 1
    html = messages[0].html
    assert "Pipeline завершён" in html
    assert "<h2>medical-imaging</h2>" in html
    assert "<details>" in html
    assert "<summary>Alpha &lt;Vision&gt; · alpha.ai · 84</summary>" in html
    assert "radiology &amp; triage" in html
    assert "https://notion.so/alpha" in html
```

- [ ] **Step 2: Write tests for splitting by segment**

Append:

```python
def test_splits_messages_by_segment_when_budget_is_small() -> None:
    companies = [
        {
            "name": f"Company {idx}",
            "domain": f"company-{idx}.ai",
            "icp_segment": "medical-imaging" if idx < 3 else "speech-and-audio",
            "score": 70 + idx,
            "status": "dossier_ready",
            "summary_md": "x" * 600,
        }
        for idx in range(6)
    ]
    payload = {
        "run_id": "run-1",
        "segments": ["medical-imaging", "speech-and-audio"],
        "found": 6,
        "qualified": 6,
        "dossier_ready": 6,
        "errors": 0,
        "companies": companies,
    }

    messages = build_rich_summary_messages(payload, max_chars=1700, max_blocks=80)

    assert len(messages) > 1
    assert all(len(message.html.encode("utf-8")) <= 1700 for message in messages)
    assert "medical-imaging" in messages[0].html
    assert any("speech-and-audio" in message.html for message in messages)
```

- [ ] **Step 3: Write tests for oversized single company truncation**

Append:

```python
def test_truncates_single_oversized_company_summary() -> None:
    payload = {
        "run_id": "run-oversized",
        "segments": ["robotics-ai"],
        "found": 1,
        "qualified": 1,
        "dossier_ready": 1,
        "errors": 0,
        "companies": [
            {
                "name": "Huge Robotics",
                "domain": "huge.example",
                "icp_segment": "robotics-ai",
                "score": 91,
                "status": "dossier_ready",
                "summary_md": "long " * 2000,
            }
        ],
    }

    messages = build_rich_summary_messages(
        payload,
        max_chars=1800,
        max_blocks=80,
        max_company_summary_chars=700,
    )

    assert len(messages) == 1
    assert "Summary truncated" in messages[0].html
    assert len(messages[0].html.encode("utf-8")) <= 1800
```

- [ ] **Step 4: Run tests and verify they fail because the module does not exist**

Run:

```bash
pytest tests/test_telegram_rich_summary.py -q
```

Expected: `ModuleNotFoundError: No module named 'telegram_rich_summary'`.

---

### Task 2: Implement Rich Summary Builder

**Files:**
- Create: `scripts/telegram_rich_summary.py`
- Test: `tests/test_telegram_rich_summary.py`

- [ ] **Step 1: Create the module with constants and dataclasses**

Create `scripts/telegram_rich_summary.py`:

```python
"""Build Telegram Bot API 10.1 Rich Message summaries for pipeline results."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from typing import Any

MAX_RICH_CHARS = 30_000
MAX_RICH_BLOCKS = 450
MAX_COMPANY_SUMMARY_CHARS = 2_400


@dataclass(frozen=True)
class RichSummaryMessage:
    html: str
    segment_names: tuple[str, ...]
    company_count: int


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _html(value: object, default: str = "") -> str:
    return escape(_text(value, default), quote=False)


def _truncate(value: str, max_chars: int) -> tuple[str, bool]:
    if len(value) <= max_chars:
        return value, False
    if max_chars <= 32:
        return value[:max_chars], True
    return value[: max_chars - 1].rstrip() + "…", True
```

- [ ] **Step 2: Add company rendering**

Append:

```python
def _company_segment(company: dict[str, Any]) -> str:
    return _text(company.get("icp_segment"), "unknown") or "unknown"


def _company_title(company: dict[str, Any]) -> str:
    name = _text(company.get("name"), "Unknown")
    domain = _text(company.get("domain"), "")
    score = _text(company.get("score"), "n/a")
    parts = [name]
    if domain:
        parts.append(domain)
    parts.append(score)
    return " · ".join(parts)


def _render_company_details(
    company: dict[str, Any],
    *,
    max_company_summary_chars: int,
) -> str:
    summary_raw = _text(
        company.get("summary_md")
        or company.get("summary")
        or company.get("research_summary"),
        "No research summary provided.",
    )
    summary, truncated = _truncate(summary_raw, max_company_summary_chars)

    lines = [
        "<details>",
        f"<summary>{_html(_company_title(company))}</summary>",
    ]

    status = _text(company.get("status"))
    segment = _text(company.get("icp_segment"))
    if status or segment:
        meta = " · ".join(part for part in (status, segment) if part)
        lines.append(f"<p><b>Status:</b> {_html(meta)}</p>")

    latest_signal = _text(company.get("latest_signal"))
    if latest_signal:
        lines.append(f"<p><b>Signal:</b> {_html(latest_signal)}</p>")

    lines.append(f"<p>{_html(summary)}</p>")
    if truncated:
        lines.append("<p><i>Summary truncated for Telegram message size.</i></p>")

    notion_url = _text(company.get("notion_url") or company.get("notion_page_url"))
    if notion_url:
        safe_url = escape(notion_url, quote=True)
        lines.append(f'<p><a href="{safe_url}">Open in Notion</a></p>')

    lines.append("</details>")
    return "\n".join(lines)
```

- [ ] **Step 3: Add header, block counting, and message assembly**

Append:

```python
def _render_header(payload: dict[str, Any], part_label: str | None = None) -> str:
    run_id = _text(payload.get("run_id"))
    run_short = run_id[:8] if run_id else "unknown"
    errors = int(payload.get("errors") or 0)
    status = "✅" if errors == 0 else "⚠️"
    title = f"{status} Pipeline завершён"
    if part_label:
        title = f"{title} · {part_label}"
    return "\n".join(
        [
            f"<h1>{_html(title)}</h1>",
            f"<p>run_id: <code>{_html(run_short)}</code></p>",
            (
                f"<p>Found: <b>{int(payload.get('found') or 0)}</b> · "
                f"Qualified: <b>{int(payload.get('qualified') or 0)}</b> · "
                f"Dossier ready: <b>{int(payload.get('dossier_ready') or 0)}</b> · "
                f"Errors: <b>{errors}</b></p>"
            ),
        ]
    )


def _block_count(html: str) -> int:
    block_tags = (
        "<h1",
        "<h2",
        "<p>",
        "<details>",
        "<summary>",
        "<ul>",
        "<ol>",
        "<li>",
        "<blockquote>",
        "<table",
        "<tr",
    )
    return sum(html.count(tag) for tag in block_tags)


def _fits(html: str, *, max_chars: int, max_blocks: int) -> bool:
    return len(html.encode("utf-8")) <= max_chars and _block_count(html) <= max_blocks


def _message(
    payload: dict[str, Any],
    *,
    segment_names: list[str],
    company_html: list[str],
    company_count: int,
    part_label: str | None,
) -> RichSummaryMessage:
    parts = [_render_header(payload, part_label)]
    for segment_name in segment_names:
        parts.append(f"<h2>{_html(segment_name)}</h2>")
        parts.extend(company_html_by_segment for company_html_by_segment in company_html)
        break
    return RichSummaryMessage(
        html="\n\n".join(parts).strip(),
        segment_names=tuple(segment_names),
        company_count=company_count,
    )
```

- [ ] **Step 4: Replace the temporary `_message` helper with segment-aware assembly**

Edit the bottom helper to this exact implementation:

```python
def _render_message_html(
    payload: dict[str, Any],
    sections: list[tuple[str, list[str]]],
    *,
    part_index: int,
    total_parts: int,
) -> str:
    part_label = f"{part_index}/{total_parts}" if total_parts > 1 else None
    parts = [_render_header(payload, part_label)]
    for segment_name, rendered_companies in sections:
        parts.append(f"<h2>{_html(segment_name)}</h2>")
        parts.extend(rendered_companies)
    return "\n\n".join(parts).strip()
```

- [ ] **Step 5: Add the public splitting function**

Append:

```python
def build_rich_summary_messages(
    payload: dict[str, Any],
    *,
    max_chars: int = MAX_RICH_CHARS,
    max_blocks: int = MAX_RICH_BLOCKS,
    max_company_summary_chars: int = MAX_COMPANY_SUMMARY_CHARS,
) -> list[RichSummaryMessage]:
    companies = payload.get("companies") or []
    if not isinstance(companies, list):
        companies = []

    by_segment: dict[str, list[dict[str, Any]]] = {}
    for company in companies:
        if isinstance(company, dict):
            by_segment.setdefault(_company_segment(company), []).append(company)

    segment_order = [
        _text(segment)
        for segment in (payload.get("segments") or [])
        if _text(segment)
    ]
    for segment in sorted(by_segment):
        if segment not in segment_order:
            segment_order.append(segment)
    if not segment_order:
        segment_order = ["summary"]

    pending: list[tuple[str, list[str]]] = []
    messages_sections: list[list[tuple[str, list[str]]]] = []

    def flush() -> None:
        nonlocal pending
        if pending:
            messages_sections.append(pending)
            pending = []

    for segment in segment_order:
        segment_items = by_segment.get(segment, [])
        if not segment_items:
            continue

        current_segment_html: list[str] = []
        for company in segment_items:
            rendered = _render_company_details(
                company,
                max_company_summary_chars=max_company_summary_chars,
            )
            candidate_segment = current_segment_html + [rendered]
            candidate_sections = pending + [(segment, candidate_segment)]
            candidate_html = _render_message_html(
                payload,
                candidate_sections,
                part_index=1,
                total_parts=1,
            )
            if _fits(candidate_html, max_chars=max_chars, max_blocks=max_blocks):
                current_segment_html = candidate_segment
                continue

            if current_segment_html:
                pending.append((segment, current_segment_html))
                candidate_html = _render_message_html(
                    payload,
                    pending,
                    part_index=1,
                    total_parts=1,
                )
                if not _fits(candidate_html, max_chars=max_chars, max_blocks=max_blocks):
                    pending.pop()
                    flush()
                    pending.append((segment, current_segment_html))
                current_segment_html = []

            single_sections = [(segment, [rendered])]
            single_html = _render_message_html(
                payload,
                single_sections,
                part_index=1,
                total_parts=1,
            )
            if _fits(single_html, max_chars=max_chars, max_blocks=max_blocks):
                pending.extend(single_sections)
            else:
                smaller = dict(company)
                smaller["summary_md"] = _text(company.get("summary_md"))[:max_company_summary_chars]
                truncated = _render_company_details(
                    smaller,
                    max_company_summary_chars=min(max_company_summary_chars, 512),
                )
                flush()
                pending.append((segment, [truncated]))
                flush()

        if current_segment_html:
            candidate_sections = pending + [(segment, current_segment_html)]
            candidate_html = _render_message_html(
                payload,
                candidate_sections,
                part_index=1,
                total_parts=1,
            )
            if _fits(candidate_html, max_chars=max_chars, max_blocks=max_blocks):
                pending = candidate_sections
            else:
                flush()
                pending = [(segment, current_segment_html)]

    flush()

    if not messages_sections:
        messages_sections = [[("summary", ["<p>No companies in final payload.</p>"])]]

    total_parts = len(messages_sections)
    result: list[RichSummaryMessage] = []
    for index, sections in enumerate(messages_sections, start=1):
        html = _render_message_html(
            payload,
            sections,
            part_index=index,
            total_parts=total_parts,
        )
        result.append(
            RichSummaryMessage(
                html=html,
                segment_names=tuple(segment for segment, _ in sections),
                company_count=sum(len(items) for _, items in sections),
            )
        )
    return result
```

- [ ] **Step 6: Run tests and fix only failures in this module**

Run:

```bash
pytest tests/test_telegram_rich_summary.py -q
```

Expected: all tests in `tests/test_telegram_rich_summary.py` pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/telegram_rich_summary.py tests/test_telegram_rich_summary.py
git commit -m "feat: build telegram rich pipeline summaries"
```

---

### Task 3: Add Telegram Rich Sending And Fallback Tests

**Files:**
- Create: `tests/test_notify_rich_summary.py`
- Modify later: `scripts/notify.py`

- [ ] **Step 1: Write successful rich send test**

Create `tests/test_notify_rich_summary.py`:

```python
from unittest.mock import MagicMock

import notify


def test_send_rich_html_posts_send_rich_message(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    response = MagicMock()
    response.raise_for_status.return_value = None
    post = MagicMock(return_value=response)
    monkeypatch.setattr(notify.httpx, "post", post)

    ok = notify.send_rich_html("123", "<h1>Hello</h1>")

    assert ok is True
    url = post.call_args.args[0]
    body = post.call_args.kwargs["json"]
    assert url == "https://api.telegram.org/bottoken/sendRichMessage"
    assert body == {
        "chat_id": "123",
        "rich_message": {"html": "<h1>Hello</h1>"},
    }
```

- [ ] **Step 2: Write fallback test**

Append:

```python
def test_notify_pipeline_rich_summary_falls_back_to_plain_message(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    rich_response = MagicMock()
    rich_response.raise_for_status.side_effect = RuntimeError("bad rich")
    plain_response = MagicMock()
    plain_response.raise_for_status.return_value = None
    post = MagicMock(side_effect=[rich_response, plain_response])
    monkeypatch.setattr(notify.httpx, "post", post)

    sent = notify.notify_pipeline_rich_summary(
        {
            "run_id": "run-1",
            "segments": ["medical-imaging"],
            "found": 1,
            "qualified": 1,
            "dossier_ready": 1,
            "errors": 0,
            "companies": [
                {
                    "name": "Alpha",
                    "domain": "alpha.ai",
                    "icp_segment": "medical-imaging",
                    "score": 84,
                    "summary_md": "Useful company.",
                }
            ],
        }
    )

    assert sent == 1
    assert post.call_args_list[1].args[0] == "https://api.telegram.org/bottoken/sendMessage"
    fallback_body = post.call_args_list[1].kwargs["json"]
    assert fallback_body["parse_mode"] == "HTML"
    assert "Pipeline завершён" in fallback_body["text"]
```

- [ ] **Step 3: Run tests and verify they fail because functions are missing**

Run:

```bash
pytest tests/test_notify_rich_summary.py -q
```

Expected: `AttributeError` for missing `send_rich_html` or `notify_pipeline_rich_summary`.

---

### Task 4: Implement Rich Send In notify.py

**Files:**
- Modify: `scripts/notify.py`
- Test: `tests/test_notify_rich_summary.py`

- [ ] **Step 1: Add imports**

In `scripts/notify.py`, add after existing imports:

```python
from telegram_rich_summary import build_rich_summary_messages
```

- [ ] **Step 2: Add API URL constants**

Replace:

```python
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
```

with:

```python
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
TELEGRAM_RICH_API = "https://api.telegram.org/bot{token}/sendRichMessage"
```

- [ ] **Step 3: Add `send_rich_html`**

Add below `send()`:

```python
def send_rich_html(chat_id: str, html: str) -> bool:
    """Send one Telegram Bot API 10.1 Rich Message HTML payload."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN должен быть в .env")
        return False

    url = TELEGRAM_RICH_API.format(token=token)
    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "rich_message": {"html": html}},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Telegram RichMessage: ошибка отправки — %s", exc)
        return False
```

- [ ] **Step 4: Add direct plain HTML sender and compact fallback renderer**

Add below `send_rich_html()`:

```python
def send_html_to_chat(chat_id: str, text: str) -> bool:
    """Send one plain HTML message to an explicit chat."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN должен быть в .env")
        return False

    url = TELEGRAM_API.format(token=token)
    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        resp.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("Telegram sendMessage to %s failed: %s", chat_id, exc)
        return False


def _pipeline_rich_fallback_text(payload: dict) -> str:
    errors = int(payload.get("errors") or 0)
    status = "✅" if errors == 0 else "⚠️"
    run_id = str(payload.get("run_id") or "unknown")
    run_short = run_id[:8]
    companies = payload.get("companies") or []
    lines = [
        f"{status} <b>Pipeline завершён</b> · ран <code>{run_short}</code>",
        (
            f"Найдено: {int(payload.get('found') or 0)} · "
            f"qualified: {int(payload.get('qualified') or 0)} · "
            f"dossier_ready: {int(payload.get('dossier_ready') or 0)} · "
            f"ошибок: {errors}"
        ),
        "",
        "<b>Компании:</b>",
    ]
    for company in companies[:10]:
        if not isinstance(company, dict):
            continue
        name = str(company.get("name") or "Unknown")
        domain = str(company.get("domain") or "")
        score = str(company.get("score") or "n/a")
        lines.append(f"• {name} — {domain} · {score}")
    if len(companies) > 10:
        lines.append(f"…и ещё {len(companies) - 10}")
    return "\n".join(lines)
```

- [ ] **Step 5: Add `notify_pipeline_rich_summary`**

Add below fallback renderer:

```python
def notify_pipeline_rich_summary(
    payload: dict,
    *,
    chat_ids: list[str] | None = None,
) -> int:
    """Send rich pipeline summary to one or more chats. Returns successful chat count."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN не задан")
        return 0

    fallback_chat = os.environ.get("TELEGRAM_CHAT_ID", "")
    targets = chat_ids if chat_ids else ([fallback_chat] if fallback_chat else [])
    if not targets:
        logger.warning("notify_pipeline_rich_summary: нет получателей")
        return 0

    messages = build_rich_summary_messages(payload)
    sent_targets = 0
    for chat_id in targets:
        target_ok = True
        for message in messages:
            if not send_rich_html(chat_id, message.html):
                target_ok = False
                break
        if target_ok:
            sent_targets += 1
            continue

        if send_html_to_chat(chat_id, _pipeline_rich_fallback_text(payload)):
            sent_targets += 1
    return sent_targets
```

- [ ] **Step 6: Run notify tests**

Run:

```bash
pytest tests/test_notify_rich_summary.py -q
```

Expected: all tests in `tests/test_notify_rich_summary.py` pass.

- [ ] **Step 7: Commit**

```bash
git add scripts/notify.py tests/test_notify_rich_summary.py
git commit -m "feat: send telegram rich pipeline summary"
```

---

### Task 5: Add CLI Entry Point For Rich Summary Payloads

**Files:**
- Modify: `scripts/notify.py`
- Modify: `tests/test_notify_rich_summary.py`

- [ ] **Step 1: Add CLI test for stdin**

Append to `tests/test_notify_rich_summary.py`:

```python
import io
import json


def test_notify_main_reads_pipeline_rich_summary_from_stdin(monkeypatch) -> None:
    payload = {
        "run_id": "run-stdin",
        "segments": ["medical-imaging"],
        "found": 0,
        "qualified": 0,
        "dossier_ready": 0,
        "errors": 0,
        "companies": [],
    }
    called = {}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr(
        notify,
        "notify_pipeline_rich_summary",
        lambda data: called.setdefault("payload", data) or 1,
    )

    assert notify.main(["--pipeline-rich-summary-stdin"]) == 0
    assert called["payload"]["run_id"] == "run-stdin"
```

- [ ] **Step 2: Extract current CLI body into `main(argv)`**

In `scripts/notify.py`, replace the `if __name__ == "__main__":` body with:

```python
def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Telegram-уведомления Kvetio")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--message", help="Произвольный текст")
    group.add_argument("--hot-lead", metavar="JSON",
                       help='JSON: {"name":"...","domain":"...","score":72}')
    group.add_argument("--run-summary", metavar="JSON",
                       help='JSON: {"task":"...","found":N,"enriched":N,"errors":N}')
    group.add_argument("--error", metavar="JSON",
                       help='JSON: {"task":"...","error":"..."}')
    group.add_argument(
        "--pipeline-rich-summary",
        metavar="JSON_FILE",
        help="Path to final pipeline rich summary JSON payload",
    )
    group.add_argument(
        "--pipeline-rich-summary-stdin",
        action="store_true",
        help="Read final pipeline rich summary JSON payload from stdin",
    )
    args = parser.parse_args(argv)

    ok = False
    if args.message:
        ok = send(args.message)
    elif args.hot_lead:
        d = json.loads(args.hot_lead)
        ok = notify_hot_lead(
            d["name"], d["domain"], d["score"], d.get("segment", "")
        )
    elif args.run_summary:
        d = json.loads(args.run_summary)
        ok = notify_run_summary(
            d.get("task", "Task"),
            found=d.get("found", 0),
            enriched=d.get("enriched", 0),
            errors=d.get("errors", 0),
        )
    elif args.error:
        d = json.loads(args.error)
        ok = notify_error(d.get("task", "Task"), d.get("error", ""))
    elif args.pipeline_rich_summary:
        with open(args.pipeline_rich_summary, encoding="utf-8") as fh:
            ok = notify_pipeline_rich_summary(json.load(fh)) > 0
    elif args.pipeline_rich_summary_stdin:
        ok = notify_pipeline_rich_summary(json.load(sys.stdin)) > 0

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Run CLI-focused tests**

Run:

```bash
pytest tests/test_notify_rich_summary.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add scripts/notify.py tests/test_notify_rich_summary.py
git commit -m "feat: add rich summary notify cli"
```

---

### Task 6: Update The Pipeline Routine Prompt

**Files:**
- Modify: `agents/prompts/pipeline_task.md`

- [ ] **Step 1: Replace final notification instructions**

Replace Step 7 in `agents/prompts/pipeline_task.md` with:

```markdown
## Шаг 7 — Финальное Rich-уведомление

Собери финальный JSON payload в файл `/tmp/kvetio_pipeline_rich_summary.json`.

Payload должен иметь структуру:
```json
{
  "run_id": "<stable run id or timestamp>",
  "trigger_type": "manual",
  "triggered_by": "<source if known>",
  "segments": ["medical-imaging"],
  "found": 0,
  "qualified": 0,
  "dossier_ready": 0,
  "errors": 0,
  "error_details": [],
  "companies": [
    {
      "name": "Company name",
      "domain": "company.ai",
      "icp_segment": "medical-imaging",
      "score": 84,
      "status": "dossier_ready",
      "latest_signal": "short factual signal",
      "summary_md": "Final research summary from dossier/conclusions",
      "notion_url": "https://..."
    }
  ]
}
```

В `companies` включай компании, которые дошли до `qualified`, `analyzed` или `dossier_ready`.
Для `summary_md` используй финальное саммари из `dossiers.summary_md`, если оно есть.
Если досье ещё не готово, используй краткое саммари из доступных фактов анализа.
Не включай сырые длинные логи, HTML или Markdown-таблицы.

Отправь уведомление:

```bash
python scripts/notify.py --pipeline-rich-summary /tmp/kvetio_pipeline_rich_summary.json
```
```

- [ ] **Step 2: Run prompt tests**

Run:

```bash
pytest tests/test_pipeline_prompts.py -q
```

Expected: pass. If this test checks for the old `--run-summary`, update that assertion to accept `--pipeline-rich-summary`.

- [ ] **Step 3: Commit**

```bash
git add agents/prompts/pipeline_task.md tests/test_pipeline_prompts.py
git commit -m "docs: instruct pipeline to send rich final summary"
```

---

### Task 7: Add Short Documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update notification path description**

In the repository tree section, change the `scripts/notify.py` line to:

```markdown
│   ├── notify.py                  # уведомления в Telegram, включая Rich final summary
```

- [ ] **Step 2: Add a short note under the routine section**

Add:

```markdown
Финальное уведомление рутины использует Telegram Bot API `sendRichMessage`: каждая компания
рендерится как раскрывающийся `<details>` block. Если rich-отправка не проходит, `notify.py`
автоматически отправляет компактную HTML-сводку через обычный `sendMessage`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document telegram rich final summary"
```

---

### Task 8: Full Verification

**Files:**
- No file edits expected.

- [ ] **Step 1: Run focused tests**

Run:

```bash
pytest tests/test_telegram_rich_summary.py tests/test_notify_rich_summary.py tests/test_pipeline_prompts.py -q
```

Expected: all focused tests pass.

- [ ] **Step 2: Run existing Telegram routine tests**

Run:

```bash
pytest tests/test_telegram_routines.py tests/test_bot_dialog.py tests/test_routine_fire.py -q
```

Expected: pass. These flows should remain unaffected because the rich final summary belongs to `scripts/notify.py`.

- [ ] **Step 3: Run the full test suite**

Run:

```bash
pytest
```

Expected: all tests pass.

- [ ] **Step 4: Manual dry-run payload check**

Run:

```bash
python - <<'PY'
from telegram_rich_summary import build_rich_summary_messages

payload = {
    "run_id": "manual-check-2026-06-16",
    "segments": ["medical-imaging"],
    "found": 1,
    "qualified": 1,
    "dossier_ready": 1,
    "errors": 0,
    "companies": [
        {
            "name": "Alpha Vision",
            "domain": "alpha.ai",
            "icp_segment": "medical-imaging",
            "score": 84,
            "status": "dossier_ready",
            "latest_signal": "new clinical workflow",
            "summary_md": "Builds AI-assisted radiology workflow tooling.",
            "notion_url": "https://notion.so/alpha",
        }
    ],
}
messages = build_rich_summary_messages(payload)
print(len(messages))
print(messages[0].html)
PY
```

Expected:

```text
1
<h1>✅ Pipeline завершён</h1>
...
<details>
...
```

- [ ] **Step 5: Optional real Telegram smoke test**

Only run this when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured for a safe test chat:

```bash
cat >/tmp/kvetio_pipeline_rich_summary_smoke.json <<'JSON'
{
  "run_id": "smoke-2026-06-16",
  "segments": ["medical-imaging"],
  "found": 1,
  "qualified": 1,
  "dossier_ready": 1,
  "errors": 0,
  "companies": [
    {
      "name": "Alpha Vision",
      "domain": "alpha.ai",
      "icp_segment": "medical-imaging",
      "score": 84,
      "status": "dossier_ready",
      "latest_signal": "new clinical workflow",
      "summary_md": "Builds AI-assisted radiology workflow tooling.",
      "notion_url": "https://notion.so/alpha"
    }
  ]
}
JSON
python scripts/notify.py --pipeline-rich-summary /tmp/kvetio_pipeline_rich_summary_smoke.json
```

Expected: exit code `0`; Telegram receives a Rich Message with one expandable company details block.

- [ ] **Step 6: Final commit if verification required edits**

If any verification fix changed files:

```bash
git add scripts/telegram_rich_summary.py scripts/notify.py agents/prompts/pipeline_task.md tests README.md
git commit -m "fix: stabilize telegram rich summary"
```
