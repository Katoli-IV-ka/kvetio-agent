# Site Research Task - SiteResearchAgent

## Role

You orchestrate site research. Take companies with `status='new'`, scrape the
company site, run the nested relevance check, and for relevant companies write
structured contacts, notes, category, founding year, and country back to
Supabase.

**Next stage:** none. This is terminal for the new site-research pipeline.
Final status is `site_researched` or `not_relevant`.

## Run Parameters

| Parameter | Default | Description |
|---|---:|---|
| `batch_size` | 5 | Companies per iteration |
| `max_pages` | 5 | Site subpages per company |

## Step 1 - List

```sql
SELECT id, domain, name, website
FROM companies
WHERE status = 'new'
ORDER BY created_at DESC
LIMIT <batch_size>;
```

## Step 2 - Scrape Site

```bash
python scripts/site_fetch.py --domain <domain> --max-pages <max_pages> --json
```

The result is `{reachable, pages, external_links, emails, engine}`.

- If `reachable=false`, set `status='not_relevant'`, put `dead_site:<domain>`
  into `run_logs.notes`, write no content, and continue with the next company.
- If scraping fails technically and fallback is empty, leave status as `new` and
  write the error to `run_logs.errors`.

## Step 3 - Relevance

Pass the site JSON to `relevance_check_task.md`. It returns
`{relevant, category, category_label, reason}`.

- If `relevant=false`, call `ensure_category`, set `status='not_relevant'` and
  `category=<category>`, write no `contacts` or `research_notes`, and continue.

## Step 4 - Extract Relevant Data

Use `pages[].text`, `external_links`, and `emails`.

Contacts go through `scripts/contacts_store.py::upsert_contact(store, dict)`:
- people: `{"company_id": <id>, "contact_type": "person", "name": <name>,
  "info": <role>, "linkedin_url": <url?>}`;
- company external links: write primary social fields when available, or pass
  GitHub/HuggingFace/website links in `other_channels`;
- company email: `{"company_id": <id>, "contact_type": "organization",
  "name": <company_name>, "email": <addr>}`.

Notes go through `scripts/research_notes_store.py::upsert_note(...)`:
- product positioning, problem, approach, functionality, audience:
  `note_type="product"`;
- press releases: `note_type="press_release"`;
- partnerships and cooperation: `note_type="cooperative"`;
- investments, grants, funding: `note_type="finance"`.

Company fields:
- founding year -> `companies.founded_year`;
- office country -> `companies.country`.

Partial extraction is normal. If no contacts are found for a relevant company,
write what is available and still set `site_researched`.

## Step 5 - Write Status

Before assigning category, call:

```python
ensure_category(store, category, label=category_label)
```

Then update:

```sql
UPDATE companies
SET status = 'site_researched',
    category = '<category>',
    founded_year = <year_or_null>,
    country = '<country_or_null>',
    updated_at = NOW()
WHERE id = '<id>';
```

## Step 6 - Run Log And Notification

```sql
INSERT INTO run_logs (task_name, companies_found, companies_enriched, errors, notes)
VALUES ('site_research_task', <checked>, <researched>, '[]',
        'not_relevant: <N>, dead_site: <K>');
```

```bash
python scripts/notify.py --run-summary '{"task":"site_research_task","site_researched":<N>,"not_relevant":<M>}'
```

## Failure Handling

- Dead site: set `not_relevant`, write no content.
- Technical scrape failure: keep status `new`, log error.
- Thin data but relevant: write partial data and set `site_researched`.
- New category: call `ensure_category` with the proposed value and label.
