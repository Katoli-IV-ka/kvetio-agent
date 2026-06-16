# Drop Unused DB Objects Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the unused `github_org_cache` cache layer and drop the unused `recent_leads` and `pipeline_stats` database views without changing lead, scoring, bot, or Notion behavior.

**Architecture:** Treat this as a narrow cleanup. `github_org_cache` is removed from code and local SQL because the live database does not contain it and the user chose deletion. `recent_leads` and `pipeline_stats` are removed only as database views; their underlying `companies` fields stay intact because scripts and prompts may still use them directly.

**Tech Stack:** Python 3.11, pytest, ruff, Supabase/Postgres SQL, existing flat SQL migration files in `sql/`.

---

## Scope

Remove:

- `public.recent_leads` view from live DB.
- `public.pipeline_stats` view from live DB.
- `public.github_org_cache` table if it exists anywhere.
- Local `github_org_cache` runtime integration: `scripts/org_cache.py`, import/use in `scripts/github.py`, cache-specific tests, README mention, bootstrap comment.
- Local SQL file `sql/002_github_org_cache.sql`.

Do not remove:

- `companies.score`, `companies.score_bucket`, `companies.ai_direction`, `companies.last_signal_date`.
- `scripts/telegram_routines.py` hot/stale behavior.
- `SupabaseStore.list_hot_leads()` or coverage/status methods.
- `run_logs`.

## File Map

- Modify: `scripts/github.py`
  - Remove Supabase-backed `OrgCache` dependency.
  - Fetch GitHub organization metadata directly through `HttpClient`.
- Delete: `scripts/org_cache.py`
  - Entire removed cache implementation.
- Modify: `tests/test_github.py`
  - Remove `OrgCache` tests and fixtures.
  - Update adapter tests to instantiate `GitHubAdapter(rate_limit_rps=0)`.
  - Add a regression test that GitHub source does not require `SUPABASE_URL`/`SUPABASE_KEY`.
- Add: `sql/015_drop_unused_db_objects.sql`
  - Idempotently drops `recent_leads`, `pipeline_stats`, and `github_org_cache`.
- Delete: `sql/002_github_org_cache.sql`
  - Local-only cache table definition.
- Modify: `sql/001_init.sql`
  - Remove bootstrap note saying `github_org_cache` intentionally lives in migration 002.
- Modify: `tests/test_migrations.py`
  - Add a contract test for migration 015.
- Modify: `README.md`
  - Remove `org_cache.py` from the script map.
- Modify: `docs/DB-FIELD-AUDIT-2026-06-16.md`
  - Mark the selected objects as planned/removed after implementation.

---

### Task 1: Add Migration Contract Test

**Files:**
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Add the failing migration test**

Append this test to `tests/test_migrations.py`:

```python
def test_migration_015_drop_unused_db_objects():
    sql = _read("015_drop_unused_db_objects.sql")
    assert "DROP VIEW IF EXISTS recent_leads" in sql
    assert "DROP VIEW IF EXISTS pipeline_stats" in sql
    assert "DROP TABLE IF EXISTS github_org_cache" in sql
    assert "DROP TABLE IF EXISTS companies" not in sql
    assert "DROP TABLE IF EXISTS signals" not in sql
    assert "DROP TABLE IF EXISTS run_logs" not in sql
```

- [ ] **Step 2: Run the test and confirm it fails because the migration does not exist**

Run:

```bash
pytest tests/test_migrations.py::test_migration_015_drop_unused_db_objects -q
```

Expected: fail with `FileNotFoundError` for `015_drop_unused_db_objects.sql`.

- [ ] **Step 3: Commit the failing contract test**

```bash
git add tests/test_migrations.py
git commit -m "test(sql): specify unused db object cleanup migration"
```

---

### Task 2: Add Idempotent SQL Cleanup Migration

**Files:**
- Create: `sql/015_drop_unused_db_objects.sql`

- [ ] **Step 1: Create the migration file**

Create `sql/015_drop_unused_db_objects.sql` with:

```sql
-- Migration 015: drop selected unused DB objects.
--
-- User decision 2026-06-16:
-- - github_org_cache is not present in live DB and the cache layer is being removed.
-- - recent_leads and pipeline_stats are dashboard-only views with no live code consumers.
--
-- This migration intentionally does not drop companies scoring/status columns.
-- Idempotent: all drops use IF EXISTS.

DROP VIEW IF EXISTS recent_leads;
DROP VIEW IF EXISTS pipeline_stats;
DROP TABLE IF EXISTS github_org_cache;
```

- [ ] **Step 2: Run the migration test**

Run:

```bash
pytest tests/test_migrations.py::test_migration_015_drop_unused_db_objects -q
```

Expected: pass.

- [ ] **Step 3: Commit the migration**

```bash
git add sql/015_drop_unused_db_objects.sql tests/test_migrations.py
git commit -m "chore(sql): drop unused cache table and dashboard views"
```

---

### Task 3: Remove GitHub Adapter Dependency on `OrgCache`

**Files:**
- Modify: `scripts/github.py`
- Modify: `tests/test_github.py`

- [ ] **Step 1: Add a failing regression test for no Supabase dependency**

In `tests/test_github.py`, add this test near the other `GitHubAdapter` tests:

```python
def test_github_adapter_does_not_require_supabase_env(
    monkeypatch: pytest.MonkeyPatch,
    query_dicom: ICPQuery,
) -> None:
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_KEY", raising=False)
    code_payload = _load("github_code_search_sample.json")
    org_payload = _load("github_org_sample.json")

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(return_value=Response(200, json=code_payload))
        mock.get(f"{ORGS_API}/orgs/MedVision-AI").mock(
            return_value=Response(200, json=org_payload)
        )

        with GitHubAdapter(rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query_dicom))

    assert len(signals) == 1
    assert signals[0].company_name == "MedVision AI"
```

- [ ] **Step 2: Run the new test and confirm it fails on current code**

Run:

```bash
pytest tests/test_github.py::test_github_adapter_does_not_require_supabase_env -q
```

Expected: fail with `RuntimeError: SUPABASE_URL и SUPABASE_KEY должны быть в .env`.

- [ ] **Step 3: Update `scripts/github.py` docstring and imports**

Change the module docstring top section from:

```python
"""GitHub Code Search source adapter.

Finds organizations with recent Python training scripts for ICP keywords,
fetches organization metadata through a Supabase-backed TTL cache, and yields
RawSignal objects compatible with the other Kvetio source adapters.
"""
```

to:

```python
"""GitHub Code Search source adapter.

Finds organizations with recent Python training scripts for ICP keywords,
fetches organization metadata from the GitHub API, and yields RawSignal objects
compatible with the other Kvetio source adapters.
"""
```

Remove:

```python
from org_cache import OrgCache
```

- [ ] **Step 4: Update `GitHubAdapter.__init__` signature and body**

Replace the constructor:

```python
    def __init__(
        self,
        *,
        org_cache: OrgCache | None = None,
        parser_version: str = "2026-05",
        rate_limit_rps: float = 0.5,
        github_token: str | None = None,
        active_within_days: int = ACTIVE_WITHIN_DAYS,
    ) -> None:
        self.parser_version = parser_version
        self._cache = org_cache if org_cache is not None else OrgCache()
        self._active_within_days = active_within_days
```

with:

```python
    def __init__(
        self,
        *,
        parser_version: str = "2026-05",
        rate_limit_rps: float = 0.5,
        github_token: str | None = None,
        active_within_days: int = ACTIVE_WITHIN_DAYS,
    ) -> None:
        self.parser_version = parser_version
        self._active_within_days = active_within_days
```

- [ ] **Step 5: Update `_build_signal` to fetch org metadata directly**

Replace:

```python
    def _build_signal(self, org_login: str, last_pushed: datetime) -> RawSignal | None:
        org_data = self._cache.get(org_login)
        if org_data is None:
            raw = self._http.get_json(f"{ORGS_API}/orgs/{org_login}")
            if not isinstance(raw, dict) or not raw:
                logger.debug("github: org %s returned empty metadata", org_login)
                return None
            self._cache.set(org_login, raw)
            org_data = raw
```

with:

```python
    def _build_signal(self, org_login: str, last_pushed: datetime) -> RawSignal | None:
        org_data = self._http.get_json(f"{ORGS_API}/orgs/{org_login}")
        if not isinstance(org_data, dict) or not org_data:
            logger.debug("github: org %s returned empty metadata", org_login)
            return None
```

- [ ] **Step 6: Run the new regression test**

Run:

```bash
pytest tests/test_github.py::test_github_adapter_does_not_require_supabase_env -q
```

Expected: pass.

- [ ] **Step 7: Commit the runtime change**

```bash
git add scripts/github.py tests/test_github.py
git commit -m "refactor(github): remove Supabase org metadata cache"
```

---

### Task 4: Remove Cache-Specific Tests and Update GitHub Tests

**Files:**
- Modify: `tests/test_github.py`
- Delete: `scripts/org_cache.py`

- [ ] **Step 1: Remove cache imports and helper functions**

In `tests/test_github.py`, remove:

```python
from unittest.mock import MagicMock
from org_cache import OrgCache
```

Remove helper functions:

```python
def _make_cache(ttl_days: int = 30) -> OrgCache:
    """Return OrgCache with mocked Supabase client."""
    cache = OrgCache.__new__(OrgCache)
    cache._client = MagicMock()
    cache._ttl = timedelta(days=ttl_days)
    return cache


def _stub_supabase_get(cache: OrgCache, data: dict | None) -> None:
    """Wire mock chain: table().select().eq().maybe_single().execute().data."""
    (
        cache._client
        .table.return_value
        .select.return_value
        .eq.return_value
        .maybe_single.return_value
        .execute.return_value
        .data
    ) = data


def _cache_miss() -> OrgCache:
    cache = _make_cache()
    _stub_supabase_get(cache, None)
    cache._client.table.return_value.upsert.return_value.execute.return_value = MagicMock()
    return cache
```

Remove the `fixed_now` patch for `org_cache._utcnow`:

```python
monkeypatch.setattr("org_cache._utcnow", lambda: FIXED_NOW)
```

- [ ] **Step 2: Remove `OrgCache` unit tests**

Delete these tests from `tests/test_github.py`:

```python
def test_cache_miss_returns_none() -> None: ...
def test_cache_hit_returns_data() -> None: ...
def test_stale_entry_returns_none() -> None: ...
def test_entry_just_within_ttl_returns_data() -> None: ...
def test_cache_set_calls_upsert() -> None: ...
```

- [ ] **Step 3: Replace adapter constructor calls**

Replace every occurrence of:

```python
GitHubAdapter(org_cache=_cache_miss(), rate_limit_rps=0)
```

with:

```python
GitHubAdapter(rate_limit_rps=0)
```

Replace:

```python
GitHubAdapter(org_cache=cache, rate_limit_rps=0)
```

with a direct GitHub API mock and:

```python
GitHubAdapter(rate_limit_rps=0)
```

- [ ] **Step 4: Replace the cache-hit behavior test**

Delete `test_cache_hit_skips_org_api_call`.

Add this direct-fetch behavior test:

```python
def test_org_metadata_is_fetched_from_github_api(query_dicom: ICPQuery) -> None:
    code_payload = {
        "total_count": 1,
        "incomplete_results": False,
        "items": [
            {
                "name": "train.py",
                "path": "train.py",
                "repository": {
                    "id": 1,
                    "name": "ml",
                    "full_name": "FetchedCo/ml",
                    "owner": {"login": "FetchedCo", "type": "Organization"},
                    "pushed_at": "2026-04-01T00:00:00Z",
                },
            }
        ],
    }
    org_payload = {
        "login": "FetchedCo",
        "name": "Fetched Company",
        "blog": "https://fetchedco.com",
        "email": None,
        "description": "Fetched",
        "public_repos": 3,
        "followers": 5,
    }

    with respx.mock() as mock:
        mock.get(SEARCH_API).mock(return_value=Response(200, json=code_payload))
        org_route = mock.get(f"{ORGS_API}/orgs/FetchedCo").mock(
            return_value=Response(200, json=org_payload)
        )

        with GitHubAdapter(rate_limit_rps=0) as adapter:
            signals = list(adapter.fetch(query_dicom))

    assert org_route.called
    assert len(signals) == 1
    assert signals[0].company_name == "Fetched Company"
```

- [ ] **Step 5: Delete the cache implementation file**

Delete:

```bash
git rm scripts/org_cache.py
```

- [ ] **Step 6: Run GitHub tests**

Run:

```bash
pytest tests/test_github.py -q
```

Expected: all GitHub tests pass.

- [ ] **Step 7: Commit test cleanup and file deletion**

```bash
git add tests/test_github.py scripts/github.py
git rm scripts/org_cache.py
git commit -m "test(github): remove org cache test coverage"
```

---

### Task 5: Remove Local SQL and Documentation References

**Files:**
- Delete: `sql/002_github_org_cache.sql`
- Modify: `sql/001_init.sql`
- Modify: `README.md`
- Modify: `docs/DB-FIELD-AUDIT-2026-06-16.md`

- [ ] **Step 1: Delete local cache SQL**

Run:

```bash
git rm sql/002_github_org_cache.sql
```

- [ ] **Step 2: Remove bootstrap note from `sql/001_init.sql`**

Remove these lines from the bottom of `sql/001_init.sql`:

```sql
-- NOTE: `github_org_cache` intentionally lives in sql/002_github_org_cache.sql.
-- Keep it split from runtime bootstrap schema to isolate GitHub-specific cache lifecycle.
```

- [ ] **Step 3: Update README script map**

In `README.md`, remove this line:

```text
│   ├── org_cache.py               # TTL-кэш GitHub org metadata в Supabase
```

- [ ] **Step 4: Update the fresh DB audit**

In `docs/DB-FIELD-AUDIT-2026-06-16.md`:

Replace:

```markdown
### `pipeline_stats`
```

with:

```markdown
### `pipeline_stats` — selected for removal
```

Replace:

```markdown
### `recent_leads`
```

with:

```markdown
### `recent_leads` — selected for removal
```

Replace:

```markdown
### `github_org_cache`
```

with:

```markdown
### `github_org_cache` — selected for removal
```

Add this note under the `github_org_cache` section:

```markdown
Decision 2026-06-16: remove this cache layer instead of applying the missing table. GitHub org metadata will be fetched directly by `scripts/github.py`.
```

- [ ] **Step 5: Verify no live references remain outside historical/audit text**

Run:

```bash
rg -n "org_cache|github_org_cache|recent_leads|pipeline_stats" scripts tests config agents bot README.md sql
```

Expected output after this task:

```text
sql/015_drop_unused_db_objects.sql:... DROP VIEW IF EXISTS recent_leads;
sql/015_drop_unused_db_objects.sql:... DROP VIEW IF EXISTS pipeline_stats;
sql/015_drop_unused_db_objects.sql:... DROP TABLE IF EXISTS github_org_cache;
```

- [ ] **Step 6: Commit local reference cleanup**

```bash
git add README.md sql/001_init.sql docs/DB-FIELD-AUDIT-2026-06-16.md
git rm sql/002_github_org_cache.sql
git commit -m "docs: remove unused cache and dashboard view references"
```

---

### Task 6: Full Local Verification

**Files:**
- No file changes expected.

- [ ] **Step 1: Run targeted tests**

Run:

```bash
pytest tests/test_github.py tests/test_migrations.py -q
```

Expected: all targeted tests pass.

- [ ] **Step 2: Run full test suite**

Run:

```bash
pytest
```

Expected: all tests pass.

- [ ] **Step 3: Run linter**

Run:

```bash
ruff check .
```

Expected: no lint errors.

- [ ] **Step 4: Inspect git diff**

Run:

```bash
git diff --stat HEAD
git status --short
```

Expected:

- only intended files are changed or deleted;
- no generated cache files are staged;
- `scripts/__pycache__/` remains untracked/ignored.

---

### Task 7: Apply Supabase Cleanup Migration

**Files:**
- No local file changes expected after migration file already exists.

Apply this only after local tests pass and the change is approved for the live project.

- [ ] **Step 1: Apply migration in Supabase**

Use the Supabase connector `apply_migration` or SQL Editor with migration name:

```text
015_drop_unused_db_objects
```

SQL:

```sql
DROP VIEW IF EXISTS recent_leads;
DROP VIEW IF EXISTS pipeline_stats;
DROP TABLE IF EXISTS github_org_cache;
```

- [ ] **Step 2: Verify objects are gone**

Run this SQL in Supabase:

```sql
select
  to_regclass('public.github_org_cache') is null as github_org_cache_absent,
  not exists (
    select 1
    from pg_views
    where schemaname = 'public'
      and viewname in ('recent_leads', 'pipeline_stats')
  ) as selected_views_absent;
```

Expected result:

```text
github_org_cache_absent = true
selected_views_absent = true
```

- [ ] **Step 3: Verify remaining core tables still exist**

Run:

```sql
select
  to_regclass('public.companies') is not null as companies_exists,
  to_regclass('public.signals') is not null as signals_exists,
  to_regclass('public.run_logs') is not null as run_logs_exists;
```

Expected result:

```text
companies_exists = true
signals_exists = true
run_logs_exists = true
```

- [ ] **Step 4: Re-run Supabase security advisor**

Run the Supabase security advisor.

Expected:

- no `security_definer_view` findings for `public.recent_leads`;
- no `security_definer_view` findings for `public.pipeline_stats`;
- existing RLS findings for unrelated public tables may remain and are not part of this task.

---

### Task 8: Final Cleanup Commit

**Files:**
- Commit whatever remains from Tasks 1-6 if earlier commits were squashed or skipped.

- [ ] **Step 1: Final status check**

Run:

```bash
git status --short
```

Expected: only intended changes are present.

- [ ] **Step 2: Final commit if needed**

If any intended changes remain unstaged:

```bash
git add README.md docs/DB-FIELD-AUDIT-2026-06-16.md tests/test_github.py tests/test_migrations.py scripts/github.py sql/001_init.sql sql/015_drop_unused_db_objects.sql
git rm -f scripts/org_cache.py sql/002_github_org_cache.sql
git commit -m "chore(db): remove unused cache table and dashboard views"
```

---

## Rollback

If code removal causes issues:

```bash
git revert <cleanup_commit_sha>
```

If the live DB migration needs to be reversed, recreate only the views if still wanted:

```sql
CREATE VIEW pipeline_stats AS
SELECT status, count(*) AS count
FROM companies
GROUP BY status
ORDER BY status;

CREATE VIEW recent_leads AS
SELECT
  domain,
  name,
  score,
  score_bucket,
  icp_segment,
  latest_signal,
  last_signal_date,
  ai_direction,
  notion_page_id
FROM companies
WHERE score_bucket = ANY (ARRAY['Hot'::text, 'Warm'::text])
  AND (last_signal_date IS NULL OR last_signal_date >= now() - interval '30 days')
ORDER BY score DESC NULLS LAST
LIMIT 50;
```

Do not recreate `github_org_cache` unless the project explicitly decides to restore the cache layer. Restoring it requires restoring `scripts/org_cache.py`, `sql/002_github_org_cache.sql`, and the `OrgCache` integration in `scripts/github.py`.

## Self-Review

- Spec coverage: covers all three selected objects: `github_org_cache`, `recent_leads`, `pipeline_stats`.
- Data safety: no `companies`, `signals`, or `run_logs` data is dropped.
- Runtime safety: removes the local `OrgCache` dependency so `scripts/github.py` no longer depends on a missing live table.
- Verification: includes targeted tests, full pytest, ruff, Supabase object checks, and advisor check.
- Rollback: includes SQL to restore views and git revert path for code.
