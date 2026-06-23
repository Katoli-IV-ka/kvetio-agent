# Spec: Russian-first Notion localization with Gemini fallback

Date: 2026-06-23

## Goal

All human-readable information that lands in Notion should be clear, natural
Russian. The database should not store translated copies. Translation is a
presentation concern for Notion sync only, and new pipeline output should be
generated in Russian at the source.

## Current problem

The repository already has a `translate.py` cache gateway and a
`translations` table, but production `NotionSync` is created without a
translator. Even if wired, that design stores translated text in the database.
The new requirement rejects DB translation storage and prioritizes quality.

## Design choice

Use a hybrid migration:

1. New analysis and conclusion output is generated in Russian by agents.
2. Notion sync performs a last-mile localization guard for legacy English
   prose before writing to Notion.
3. The localization result exists only in memory during the sync run.
4. Gemini is the default translation backend because the project already uses
   `GEMINI_API_KEY` and `google-genai`.
5. OpenAI remains an optional fallback backend for reliability or quality.

This keeps future costs low, improves quality by producing Russian with full
analysis context, and still prevents old English records from reaching Notion.

## Data boundaries

Keep raw/source data in the original language:

- URLs, emails, phones.
- Company, product, person, investor, model, and dataset names.
- Funding stages, dates, amounts, country codes, IDs.
- Controlled Notion option values: `ICP Segment`, `Pipeline Status`,
  `Potential Data`, `Company Size`, `Team Size`.
- Source payloads and evidence snippets where original wording matters.

Generate or localize presentation prose in Russian:

- `companies.description` when rendered as `AI Summary`.
- `contacts.info` when rendered as `Contact Info`.
- `dossiers.summary_md`.
- `dossiers.audit_md`.
- `dossiers.section_summaries` values.
- `dossiers.pain_summary`, `pitch_angle`, `why_interesting`, `outreach_hook`.
- Prose values from `analysis_records.facts` that are rendered in Notion body.
- `research_records.summary` for news body rendering.

## Components

### Prompt language contract

Update agent prompts so that presentation fields are written in natural Russian
by default. The prompts must still preserve original names, URLs, product terms,
metrics, and evidence references.

Affected prompts:

- `agents/prompts/analysis_task.md`
- `agents/prompts/analysis_section_task.md`
- `agents/prompts/analysis_audit_task.md`
- `agents/prompts/conclusions_task.md`
- Any prompt that writes `companies.description`, dossier fields, or
  sales-brief fields.

### NotionTextLocalizer

Add a small localization boundary used only by Notion sync:

```python
class NotionTextLocalizer:
    def localize_text(self, text: str | None, *, field: str) -> str | None: ...
    def localize_mapping(self, value: dict, *, field_prefix: str) -> dict: ...
    def localize_list(self, value: list, *, field_prefix: str) -> list: ...
```

Responsibilities:

- Return `None` and empty strings unchanged.
- Skip structural values.
- Detect whether prose is already Russian.
- Translate only likely-English legacy prose.
- Preserve markdown, URLs, names, numbers, dates, bullets, and headings.
- Never write translations back to Supabase.

### Language detection

Use a deterministic heuristic first:

- If Cyrillic letters are present above a small threshold, treat as Russian.
- If text is mostly URL/email/code/number punctuation, skip.
- If Latin prose dominates and the field is whitelisted, localize.

Avoid calling an LLM just to classify language unless the heuristic is
ambiguous. Ambiguous short strings should be left unchanged unless the field is
known prose.

### Gemini backend

Create a Gemini translation backend that reuses existing environment naming:

- `GEMINI_API_KEY`
- `KVETIO_TRANSLATION_PROVIDER=gemini`
- `KVETIO_TRANSLATION_MODEL=gemini-2.5-flash-lite`

The current `bot/intent_agent.py` default is `gemini-2.0-flash-lite`. For this
new localization path, default to `gemini-2.5-flash-lite`, since it is the
current budget Gemini model family.

Backend output contract:

- Return only translated text, no commentary.
- Preserve markdown structure.
- Preserve URLs exactly.
- Preserve proper nouns and product names unless they have a conventional
  Russian spelling.
- Do not add facts, conclusions, warnings, or explanation.
- Keep B2B/data-services context understandable for a Russian-speaking sales
  and research user.

### Optional OpenAI fallback

OpenAI fallback is optional and disabled unless configured:

- `KVETIO_TRANSLATION_FALLBACK_PROVIDER=openai`
- `KVETIO_TRANSLATION_FALLBACK_MODEL=gpt-5-mini`

Use fallback only when Gemini fails, returns invalid output, or rate limits.
If no fallback is configured, follow the configured failure mode.

## Failure modes

Use explicit policy:

- `KVETIO_TRANSLATION_ON_FAILURE=fail_sync` by default.
- `write_original_with_warning` for permissive runs.
- `skip_field` for non-critical fields.

Recommended default is `fail_sync`, because the requirement is to avoid English
text entering Notion silently.

## Sync integration points

Wire localization before Notion payload construction:

- `NotionSync.sync_forward` for database property payloads.
- `build_company_notion_profile` or its caller for `description`.
- `enrich_contact_rows` or contact forward payload preparation for
  `contacts.info`.
- `NotionSync.sync_dossiers` legacy body path.
- `notion_render.render_and_write_body` modern body renderer.

Do not localize after payloads become Notion block dictionaries unless there is
no cleaner source-level hook. Source-level localization is easier to test and
less likely to corrupt URLs or mentions.

## Configuration

Recommended production env:

```env
KVETIO_NOTION_LOCALIZATION=hybrid
KVETIO_TRANSLATION_PROVIDER=gemini
KVETIO_TRANSLATION_MODEL=gemini-2.5-flash-lite
KVETIO_TRANSLATION_ON_FAILURE=fail_sync
```

Optional quality fallback:

```env
KVETIO_TRANSLATION_FALLBACK_PROVIDER=openai
KVETIO_TRANSLATION_FALLBACK_MODEL=gpt-5-mini
```

Strict free/API-minimal mode:

```env
KVETIO_TRANSLATION_PROVIDER=gemini
KVETIO_TRANSLATION_FALLBACK_PROVIDER=
KVETIO_TRANSLATION_ON_FAILURE=fail_sync
```

## Privacy and cost note

Gemini free-tier usage may be subject to Google free-tier data-use terms.
For public company research this is likely acceptable, but it should be an
explicit product decision. Paid tiers can differ in data-use treatment.

Gemini is the default because it has a free tier and this repo already carries
the required integration surface. OpenAI remains a configured fallback, not a
hard dependency.

## Tests

Add or update tests for:

- Russian text is not sent to the backend.
- English prose is localized before Notion payloads are written.
- URL/email/phone/funding/select/multi-select/relation values are unchanged.
- Markdown headings, bullets, links, and paragraphs survive localization.
- `fail_sync` prevents Notion writes on translation failure.
- `write_original_with_warning` writes original text and logs a warning.
- Gemini backend request and response parsing are unit-tested with mocked HTTP.
- Prompt tests assert Russian-output instructions exist in affected prompts.

## Migration strategy

1. Update prompts first so new data becomes Russian without translation.
2. Add localizer and Gemini backend behind env flags.
3. Wire localizer into Notion sync in dry-run-friendly form.
4. Run sync against a small sample and inspect Notion output.
5. Keep the existing `translations` table unused for now; remove it later in a
   separate cleanup after the new path is stable.

## Non-goals

- Do not translate and store copies in Supabase.
- Do not translate controlled Notion options dynamically.
- Do not redesign the whole pipeline model provider system.
- Do not rewrite source/evidence payloads.
- Do not require OpenAI for the default path.
