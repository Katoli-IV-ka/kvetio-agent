# Site Research For Relevant Companies Task - SiteResearchAgent (Relevant Track)

## Role

You orchestrate site research for already-qualified `relevant` companies. Scrape
the company site to extract structured contacts, product information, founding
year, and country. Write findings back to Supabase.

**Scope:** This is NOT a relevance gate. Companies are already `relevant`. Goal is
to enrich with site-scraped data.

**Status:** After successful site scrape, company status changes `relevant` →
`site_researched`. If the site is unreachable or scraping fails, status stays `relevant`.

## Run Parameters

| Parameter | Default | Description |
|---|---:|---|
| `batch_size` | 20 | Companies per batch |
| `max_pages` | 5 | Site subpages per company |

## Step 1 - List

```sql
SELECT id, domain, name, website
FROM companies
WHERE status = 'relevant'
ORDER BY created_at DESC
LIMIT <batch_size>;
```

## Step 2 - Scrape Site

```bash
python scripts/site_fetch.py --domain <domain> --max-pages <max_pages> --json
```

The result is `{reachable, pages, external_links, emails, engine}`.

- If `reachable=false`, write note `dead_site:<domain>` to `run_logs.notes` and
  skip to next company. **Do not change status.**
- If scraping fails technically and fallback is empty, log error in
  `run_logs.errors` and skip to next company.

## Step 3 - Extract Data

Use `pages[].text`, `external_links`, and `emails`.

### 3a. Contacts

Through `scripts/contacts_store.py::upsert_contact(store, dict)`:

- **People**: `{"company_id": <id>, "contact_type": "person", "name": <name>,
  "info": <role/title>, "linkedin_url": <url_if_found>}`;
- **Company channels**: Parse `external_links` for:
  - GitHub org → `{"company_id": <id>, "contact_type": "organization",
    "name": "<company_name> GitHub", "other_channels": [{"type": "github",
    "url": "..."}]}`;
  - HuggingFace org → similar structure with `type: "huggingface"`;
  - Social links (LinkedIn company, Twitter/X, etc.) → primary fields
    (`linkedin_url`, `x_url`, etc.) when available;
- **Company email**: If general company email found in pages or emails list →
  `{"company_id": <id>, "contact_type": "organization", "name": <company_name>,
  "email": <addr>}`.

Partial extraction is OK. If no contacts found for a company, skip contacts.

### 3b. Product Information

Write to `research_records` via `store.upsert_research_record(record, company_id=<id>)`:

```python
record = ResearchRecord(
    source="website",
    record_type="product_update",
    record_role="source",
    agent="site_research",
    company_name=<name>,
    domain=<domain>,
    linkedin_url=None,
    url=<homepage_url>,
    observed_at=date.today(),
    confidence="medium",
    title="<company_name> — product description",
    summary=<product_text[:500]>,
)
store.upsert_research_record(record, company_id=<id>)
```

- Extract from: homepage copy, `/product` or `/solutions` pages, feature lists,
  documentation.
- If no clear product description found, skip this record.
- Do NOT use `research_notes` or `upsert_note()` — always use `research_records`.

### 3c. Company Fields

- `founded_year` → search pages for "founded", "established", "since" patterns,
  or extract from About page.
- `country` → extract from HQ location mentioned on site (About, Contact pages).
- These are updates to `companies` table.

## Step 4 - Batch Write

After processing each company, immediately write and then update status:

```python
# For each company with extracted data:
if contacts:
    for contact in contacts:
        upsert_contact(store, contact)

if product_note:
    upsert_note(store, {
        "company_id": <id>,
        "note_type": "product",
        "content": <product_note>,
        "source_url": <primary_source_url>
    })

# Update company fields + status
update_company(store, id, {
    "founded_year": <year_or_null>,
    "country": <country_or_null>,
    "status": "site_researched",
    "updated_at": "NOW()"
})
```

## Step 5 - Run Log And Notification

After batch:

```sql
INSERT INTO run_logs (task_name, companies_found, companies_enriched, errors, notes)
VALUES ('site_research_for_relevant', <batch_size>, <enriched_count>, 
        '<error_json>', '<summary_notes>');
```

Summary notes example: `"contacts_found: 45, products_found: 18, dead_sites: 2"`.

```bash
python scripts/notify.py --run-summary '{
  "task": "site_research_for_relevant",
  "batch_size": <batch_size>,
  "enriched": <enriched_count>,
  "contacts_found": <total_contacts>,
  "products_found": <total_products>,
  "founded_years_found": <count>,
  "countries_found": <count>
}'
```

## Failure Handling

- Dead site: skip, log note, continue to next company. **No status change.**
- Technical scrape failure: log error, continue to next company.
- Thin data but some found: write partial data (contacts or product or founding
  info). Incomplete extraction is normal.
- New category/location format: use best effort to classify or extract.

## Important Notes

- **Status changes.** `relevant` → `site_researched` after successful scrape.
  Dead or unreachable sites keep status `relevant`.
- **Idempotent.** Repeat runs update the same records (contact and record
  deduplication handles re-runs). Status re-set to `site_researched` on re-run
  is harmless.
- **No filtering.** All reachable companies in the batch are processed equally.
