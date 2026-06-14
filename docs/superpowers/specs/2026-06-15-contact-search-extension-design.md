# Contact Search Extension — Design Spec
**Date:** 2026-06-15  
**Status:** Approved

## Problem

The current DM pipeline (Apollo, GitHub, HuggingFace, Wellfound, team page) produces contacts
that are often empty (no email, no LinkedIn, no Twitter) or limited to senior titles that are
hard to reach. We need more contacts per company with real outreach points so we can approach
companies from multiple angles.

## Goals

- More contacts per company, including mid-level (ML Engineers, Research Scientists, PMs)
- Multiple contact points per person: email + LinkedIn + Twitter + personal site
- Corporate email fallback (`info@`, `contact@`) when no individual contacts are found
- Bесплатные источники first; Hunter.io verify as an optional paid step

## Non-Goals

- LinkedIn scraping (ToS risk, deferred to paid API later)
- Crunchbase people API (tier C stub, out of scope for this iteration)
- Real-time lookup during outreach (all enrichment runs batch, per domain)

---

## Architecture

### Part 1 — New Sources

#### `scripts/dm_contact_page.py`

Scrapes corporate contact emails from the company website.

- Tries paths: `/contact`, `/contact-us`, `/about/contact`, `/reach-us`, `/get-in-touch`
- Extracts emails via `mailto:` links and regex over page text
- Targets: `info@`, `hello@`, `press@`, `founders@`, `team@`, `support@`
- Returns contacts with:
  - `full_name = "[Company] Contact"`
  - `source_vector = "contact_page"`
  - `dm_priority = 3` (lowest — fallback only)
  - `email_status = "scraped"`
- Follows the same `fetch(domain) → list[dict]` interface as all other dm_* fetchers

#### Apollo ICP Expansion (change in `dm_apollo.py`)

Expand `TITLE_KEYWORDS`:
```python
"ml engineer", "machine learning engineer", "research scientist",
"applied scientist", "data scientist", "product manager", "head of product"
```

Expand `SENIORITIES`:
```python
"senior", "manager"
```

Raise `per_page` from 10 → 25.

#### Twitter handle fix in `dm_github.py`

`fetch_user_profile` already pulls `twitter_username` from the GitHub API.
Verify that `dm_github.py` writes `twitter_handle` to `contacts_store` — no new module needed,
just a correctness check + test.

---

### Part 2 — Contact Enricher

**`scripts/contact_enricher.py`** — runs after all dm_* fetchers for a given domain.

Loads all contacts for the domain from Supabase and enriches missing fields in three steps.

#### Step 1: Email Pattern Guesser (free)

1. Collect contacts that already have `email` for the domain → infer pattern
   (e.g., `first.last`, `first`, `flast`, `firstl`)
2. Apply the inferred pattern to contacts without email
3. If no pattern can be inferred, try all three common formats
4. Write with `email_status="guessed"`, `confidence="low"`, `email_source="pattern_guesser"`

#### Step 2: Hunter.io Verify (optional paid)

- Activated only if `HUNTER_API_KEY` is set in `.env`
- Takes contacts with `email_status="guessed"`
- Calls Hunter.io Email Verifier API per address
- Updates `email_status` → `"valid"` / `"invalid"` / `"accept_all"`
- Updates `email_source` → `"hunter_verify"`
- If key not set: step is skipped silently

#### Step 3: Personal Website + Twitter Discovery (free)

- For contacts with `github_username`: fetch GitHub profile API
  → update `twitter_handle` and `personal_website` (from `blog` field)
- For contacts with `hf_username`: fetch HuggingFace overview API
  → parse bio for `@handle` and personal site URL
- All updates go through `contacts_store.upsert_contact`

#### CLI

```bash
python scripts/contact_enricher.py --domain radai.com
python scripts/contact_enricher.py --domain radai.com --skip-hunter
```

---

### Part 3 — Integration

#### Pipeline Order

```
dm_apollo
dm_github
dm_huggingface_contacts
dm_wellfound
dm_team_page
dm_contact_page        ← new
contact_enricher       ← new
contacts_store.mark_enriched
```

#### `config/sources.yaml` additions

```yaml
contact_page:
  enabled: true
  tier: A
  description: "Corporate contact emails from /contact pages"
  script: scripts/dm_contact_page.py

contact_enricher:
  enabled: true
  tier: A
  description: "Email pattern guesser + Hunter.io verify + Twitter/site discovery"
  script: scripts/contact_enricher.py
  hunter_verify: false   # auto-enabled when HUNTER_API_KEY is present
```

#### Database Migration

Add one new column to `contacts`:

```sql
ALTER TABLE contacts ADD COLUMN personal_website TEXT;
```

All other fields (`twitter_handle`, `email`, `email_status`, `email_source`, `github_username`,
`hf_username`) already exist.

#### `dm_priority` Logic

| Priority | Meaning |
|----------|---------|
| 1 | Senior decision-maker with verified email (CTO, Head of ML, VP) |
| 2 | Decision-maker without email OR mid-level with verified email |
| 3 | Mid-level without email; corporate `info@` fallback |

`dm_contact_page` always writes `priority=3`.  
`contact_enricher` upgrades `priority` from 2 → 1 when a valid email is found for a
senior-title contact.

---

## File Checklist

| File | Action |
|------|--------|
| `scripts/dm_contact_page.py` | Create |
| `scripts/contact_enricher.py` | Create |
| `scripts/dm_apollo.py` | Edit — expand ICP keywords + per_page |
| `scripts/dm_github.py` | Fix — ensure twitter_handle written to contacts_store |
| `config/sources.yaml` | Edit — add contact_page + contact_enricher entries |
| `tests/test_dm_contact_page.py` | Create |
| `tests/test_contact_enricher.py` | Create |
| Supabase migration | `ALTER TABLE contacts ADD COLUMN personal_website TEXT` |
