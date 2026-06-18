# Kvetio Agent Ecosystem

Дата обновления: 2026-06-17.

This document describes the cleaned target architecture for `kvetio-agent`.

## System Overview

`kvetio-agent` is a Claude Code Routine based lead-generation pipeline. It:

1. discovers candidate companies from source adapters;
2. validates relevance;
3. gathers supporting evidence and source links;
4. writes structured analysis;
5. builds dossiers;
6. syncs selected fields to Notion;
7. sends Telegram summaries.

The Telegram bot is only a trigger and operational reader. Pipeline execution
happens inside the hosted Routine.

## Status Model

Canonical flow:

```text
discovered -> relevant/not_relevant/manual_review -> sources_gathered -> analyzed -> dossier_ready
```

Status meanings:

| Status | Meaning |
|---|---|
| `discovered` | Candidate exists, relevance not decided |
| `relevant` | Fits ICP enough for source expansion |
| `not_relevant` | Rejected from the pipeline |
| `manual_review` | Needs human or later agent review |
| `sources_gathered` | Supporting links/evidence collected |
| `analyzed` | Structured notes written |
| `dossier_ready` | Final dossier exists and can be shown in Notion |

Monitor is a signal refresh loop, not a separate status machine.

## Signal Model

Evidence belongs in `signals`.

Signal type prefixes:

- `primary_*`: signal that first brought the company into the database.
- `verification_*`: supporting signal found during validation or source expansion.
- `monitor_*`: new signal for an already known company.

Latest signal display is derived from `signals`, usually by newest
`signal_date` or `updated_at` depending on the view.

## Main Pipeline Prompts

| Agent | Prompt | Responsibility |
|---|---|---|
| PipelineAgent | `agents/prompts/pipeline_main_task.md` | Orchestrates stages |
| DiscoveryAgent | `agents/prompts/discovery_task.md` | Writes discovered companies and primary signals |
| RelevanceAgent | `agents/prompts/relevance_task.md` | Sets relevance status |
| SourceExpansionAgent | `agents/prompts/source_expansion_task.md` | Gathers supporting links and verification signals |
| EnrichmentAgent | `agents/prompts/enrichment_task.md` | Runs deterministic link resolvers |
| AnalysisAgent | `agents/prompts/analysis_task.md` | Writes structured notes |
| ConclusionAgent | `agents/prompts/conclusions_task.md` | Writes dossiers and runs Notion sync |
| DMEnrichAgent | `agents/prompts/dm_enrich_task.md` | Optional contact discovery |
| MonitorAgent | `agents/prompts/monitor_task.md` | Optional refresh of known companies |

## Python Tools

| Area | Scripts |
|---|---|
| Source adapters | `github.py`, `huggingface.py`, `yc_browser.py`, `greenhouse.py`, `lever.py` |
| Core storage | `supabase_store.py`, `models.py`, `normalize.py` |
| Source links and dossiers | `enrichment.py`, `dossier_store.py` |
| Contacts | `contacts_store.py`, `contact_enricher.py`, `dm_*.py` |
| Notion | `notion_sync.py` |
| Telegram | `notify.py`, `telegram_routines.py`, `bot/*.py` |

## Supabase Tables

Active runtime tables:

| Table | Role |
|---|---|
| `companies` | Lead identity, status, ICP metadata, Notion page id |
| `signals` | Evidence records |
| `run_logs` | Operational history |
| `source_links` | URLs for analysis |
| `analysis_notes` | Section-level facts and audit notes |
| `dossiers` | Final summaries |
| `contacts` | People/company contact paths |

Contacts:

- `contacts.company_id -> companies.id` is canonical.
- `contacts.company_domain` remains transitional compatibility data.
- Contact writes must fail if the company cannot be resolved.

## Notion Sync

Notion sync is script-driven through `scripts/notion_sync.py`.

Companies:

- forward fields are configured in `config/notion_mapping.yaml`;
- Notion is a projection, not the source of pipeline status.

Contacts:

- relation pages are computed from `contacts.company_id -> companies.notion_page_id`;
- new reverse imports must have exactly one related company;
- existing contacts are matched through `contacts.notion_page_id`.

Manual CRM fields removed from the agent database must not be reintroduced in
the Notion mapping.

## Telegram

Telegram bot commands:

| Command | Role |
|---|---|
| `/run` | Stateless launch wizard |
| `/status` | Active run |
| `/last [n]` | Recent runs |
| `/digest [limit]` | Operational digest |
| `/hot [limit]` | Relevant companies ordered by freshness |
| `/stale [limit]` | Review queue |
| `/help`, `/whoami`, `/ping` | Utility |

The bot stores no launch presets. The launch configuration is carried by the
stateless `/run` wizard and passed to Routine `/fire`.

## Database Schema

`sql/schema.sql` is the only active database schema contract. Historical
test-era migrations were removed because they no longer represent production
history and were creating false audit signals.

The baseline schema:

- creates the seven active runtime tables;
- uses the cleaned status model;
- keeps `contacts.company_id -> companies.id` as the canonical contact relation;
- excludes removed score, bot runtime, preset, and contact join-table objects.
