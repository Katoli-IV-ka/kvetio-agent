# kvetio-agent

Pipeline лидогенерации Kvetio: Claude Code Routine ищет компании по ICP,
проверяет релевантность, собирает evidence, строит досье, синхронизирует
витрину в Notion и отправляет операционные уведомления в Telegram.

## Architecture

```text
Telegram / Schedule
  -> Claude Code Routine /fire
  -> agents/prompts/pipeline_task.md
  -> agents/prompts/pipeline_main_task.md
  -> scripts/*.py
  -> Supabase
  -> Notion
  -> Telegram notification
```

Key constraints:

- The routine runs in Anthropic's hosted Claude Code environment.
- The Telegram bot does not execute pipeline work. It only collects `/run`
  parameters and calls Routine `/fire`.
- Supabase is the runtime source of truth.
- Notion is a projection, configured through `config/notion_mapping.yaml`.
- Evidence display is derived from `signals`.

## Pipeline

Canonical company status flow:

```text
discovered -> relevant/not_relevant/manual_review -> sources_gathered -> analyzed -> dossier_ready
```

Pipeline stages:

1. `discovery_task.md` writes discovered companies and `primary_*` signals.
2. `relevance_task.md` sets `relevant`, `not_relevant`, or `manual_review`.
3. `source_expansion_task.md` and `enrichment_task.md` gather supporting links.
4. `analysis_task.md` writes structured `analysis_notes`.
5. `conclusions_task.md` writes `dossiers` and runs Notion sync.

Signal type convention:

- `primary_*`: first evidence that brought a company into the database.
- `verification_*`: supporting evidence from validation or source expansion.
- `monitor_*`: new evidence for an already known company.

## Repository Layout

```text
kvetio-agent/
├── agents/
│   ├── context/icp_summary.md
│   └── prompts/
│       ├── pipeline_task.md
│       ├── pipeline_main_task.md
│       ├── discovery_task.md
│       ├── relevance_task.md
│       ├── source_expansion_task.md
│       ├── enrichment_task.md
│       ├── analysis_task.md
│       ├── analysis_section_task.md
│       ├── analysis_audit_task.md
│       ├── conclusions_task.md
│       ├── dm_enrich_task.md
│       └── monitor_task.md
├── bot/
│   ├── gateway.py
│   ├── dialog.py
│   ├── routine.py
│   └── set_webhook.py
├── config/
│   ├── icp.yaml
│   ├── sources.yaml
│   └── notion_mapping.yaml
├── scripts/
│   ├── models.py
│   ├── supabase_store.py
│   ├── contacts_store.py
│   ├── contact_enricher.py
│   ├── dossier_store.py
│   ├── enrichment.py
│   ├── notion_sync.py
│   ├── telegram_routines.py
│   └── source adapters such as github.py, huggingface.py, yc_browser.py
├── sql/
├── tests/
└── requirements.txt
```

## Telegram Bot

The bot is a FastAPI webhook deployed as a web service.

Commands:

| Command | Purpose |
|---|---|
| `/start` | Short intro |
| `/run` | Stateless wizard that builds a Routine launch config |
| `/status` | Active run from `run_logs` |
| `/last [n]` | Recent runs |
| `/digest [limit]` | Operational digest |
| `/hot [limit]` | Relevant companies ordered by freshness |
| `/stale [limit]` | Review queue |
| `/whoami`, `/help`, `/ping` | Utility commands |

Local bot run:

```bash
uvicorn bot.gateway:app --host 0.0.0.0 --port 8000
curl localhost:8000/healthz
python -m bot.set_webhook
```

## Routine Setup

1. Create a Claude Code Routine.
2. Use `agents/prompts/pipeline_task.md` as the hosted bootstrap prompt.
3. Point the Routine at this repository.
4. Configure environment variables and network access.
5. Add Schedule and API triggers.

Manual Routine fire example:

```bash
curl -X POST "$ROUTINE_FIRE_URL" \
  -H "Authorization: Bearer $ROUTINE_TOKEN" \
  -H "anthropic-beta: experimental-cc-routine-2026-04-01" \
  -H "anthropic-version: 2023-06-01" \
  -H "Content-Type: application/json" \
  -d '{"text": "segments=medical-imaging,robotics-ai; limit=5; stages=full"}'
```

## Environment

Routine environment:

- `SUPABASE_URL`, `SUPABASE_KEY`
- `NOTION_TOKEN`, `NOTION_COMPANIES_DB_ID`, `NOTION_CONTACTS_DB_ID`
- `GITHUB_TOKEN`, `HF_TOKEN`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`

Railway bot environment:

- `SUPABASE_URL`, `SUPABASE_KEY`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `BOT_WEBHOOK_URL`
- `ROUTINE_FIRE_URL`, `ROUTINE_TOKEN`

## Database Cleanup

The cleanup migration is `sql/017_agent_database_cleanup.sql`.

Important runtime contracts after cleanup:

- `contacts.company_id` is the canonical relation to `companies.id`.
- `contacts.company_domain` remains transitional denormalized data.
- Contact writes must resolve an existing company first.
- Telegram launch is stateless through `/run`.
- Notion contact relation is computed from `contacts.company_id`.
- Evidence summaries come from `signals`, not stored company summary columns.

Do not run destructive SQL against live Supabase until local tests pass and
preflight live checks confirm all contacts can resolve to companies.

## Local Development

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest -q
ruff check .
```

Useful commands:

```bash
python scripts/supabase_store.py --coverage
python scripts/yc_browser.py --segment medical-imaging --limit 100
python scripts/notion_sync.py --validate --dry-run
python scripts/telegram_routines.py daily_digest --dry-run
```

## Principles

1. Scripts are CLI tools: args/stdin in, JSON/text out.
2. Side effects are explicit and testable.
3. Supabase is the source of truth for runtime data.
4. Prompts define agent behavior; scripts provide deterministic operations.
5. Repeated runs should avoid duplicate companies, signals, contacts, and source links.
