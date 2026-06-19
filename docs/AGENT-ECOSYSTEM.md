# Kvetio Agent Ecosystem

Дата обновления: 2026-06-19.

This document describes the active `kvetio-agent` runtime architecture after
the database cleanup.

## System Overview

`kvetio-agent` is a Claude Code Routine based lead-generation pipeline. It:

1. discovers candidate companies from source adapters;
2. validates relevance;
3. stores raw observations as research records;
4. writes structured analysis with explicit provenance;
5. builds typed dossiers;
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
| `sources_gathered` | Supporting evidence collected |
| `analyzed` | Structured interpretation exists |
| `dossier_ready` | Final dossier exists and can be shown in Notion |

Monitor is a research refresh loop, not a separate status machine.

## Research Record Model

Every raw observation about a company is one row in `research_records`. The
table is company-centric: every row carries `company_id UUID` as the canonical
foreign key to `companies.id`.

Key fields:

- `company_id` — canonical FK; all joins go through this UUID.
- `record_type` — validated against the `record_types` vocabulary table.
- `record_role` — stage intent: `primary`, `verification`, `source`,
  `monitor`, or `evidence`.
- `dedupe_key TEXT UNIQUE` — deterministic upsert key for repeatable runs.
- `url` and `summary` — human-readable evidence surface.
- `confidence NUMERIC(3,2)` — stored as a float from `0.00` to `1.00`.
- `observed_at DATE` — date the observation belongs to.
- `payload JSONB` — structured, agent-specific fields.
- `raw_data JSONB` — optional raw API snapshot.

Agents write research records. Interpretation stays in `analysis_records`, and
the `analysis_links` table records which observations support each conclusion.

Latest evidence display is derived from `research_records`, usually by newest
`observed_at` or `updated_at` depending on the view.

## Main Pipeline Prompts

| Agent | Prompt | Responsibility |
|---|---|---|
| PipelineAgent | `agents/prompts/pipeline_main_task.md` | Orchestrates stages |
| DiscoveryAgent | `agents/prompts/discovery_task.md` | Writes companies and primary research records |
| RelevanceAgent | `agents/prompts/relevance_task.md` | Sets relevance status |
| SourceExpansionAgent | `agents/prompts/source_expansion_task.md` | Gathers supporting evidence records |
| EnrichmentAgent | `agents/prompts/enrichment_task.md` | Runs deterministic link resolvers |
| AnalysisAgent | `agents/prompts/analysis_task.md` | Writes section analysis and provenance links |
| ConclusionAgent | `agents/prompts/conclusions_task.md` | Writes dossiers and runs Notion sync |
| DMEnrichAgent | `agents/prompts/dm_enrich_task.md` | Optional contact discovery |
| MonitorAgent | `agents/prompts/monitor_task.md` | Optional refresh of known companies |

## Python Tools

| Area | Scripts |
|---|---|
| Source adapters | `github.py`, `huggingface.py`, `yc_browser.py`, `greenhouse.py`, `lever.py` |
| Core storage | `supabase_store.py`, `models.py`, `normalize.py` |
| Analysis and dossiers | `enrichment.py`, `dossier_store.py` |
| Contacts | `contacts_store.py`, `contact_enricher.py`, `dm_*.py` |
| Notion | `notion_sync.py` |
| Telegram | `notify.py`, `telegram_routines.py`, `bot/*.py` |

## Supabase Tables

Active runtime tables are grouped by ownership role.

### Данные
| Таблица | Роль |
|---|---|
| companies | Идентичность компании и статус в пайплайне |
| contacts  | Контакты и каналы — люди и орг-уровень |
| dossiers  | Финализированный профиль: структурные поля + саммари + нарратив |

### Процессные
| Таблица | Роль |
|---|---|
| research_records | Сырые наблюдения: всё что агент нашёл |
| analysis_records | Интерпретации: выводы агента на основе research_records |

### Технические
| Таблица | Роль |
|---|---|
| analysis_links | Какие research_records стоят за каждым analysis_record |
| dossier_links  | Какие analysis_records стоят за каждым полем dossiers |
| record_types   | Словарь допустимых типов для research_records |
| run_logs       | История запусков агентов, ошибки, диагностика |

Contacts:

- `contacts.company_id -> companies.id` is canonical.
- `contacts.name` stores the display name for people and organizations.
- `contacts.contact_type` is `person` or `organization`.
- Contact writes must fail if the company cannot be resolved.

## Notion Sync

Notion sync is script-driven through `scripts/notion_sync.py`.

Companies:

- forward fields are configured in `config/notion_mapping.yaml`;
- Notion is a projection, not the source of pipeline status.

Contacts:

- relation pages are computed from `contacts.company_id -> companies.notion_page_id`;
- new reverse imports must have exactly one related company;
- existing contacts are matched through `contacts.notion_page_id`;
- contact display uses `contacts.name` and `contacts.contact_type`.

Dossiers:

- Notion receives typed dossier fields, section summaries, and narrative text;
- dossier provenance remains in Supabase through `dossier_links`;
- Notion does not own derived analysis state.

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

`sql/schema.sql` is the only active database schema contract for fresh
environments. Numbered files under `sql/migrations/` are live upgrade history.

The baseline schema:

- creates the nine active runtime tables listed above;
- uses the cleaned status model;
- keeps `contacts.company_id -> companies.id` as the canonical contact relation;
- keeps raw observations, interpretations, final dossiers, and provenance in
  separate tables.
