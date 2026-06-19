# Signals Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild `signals` into a universal, company-centric research log (one atomic finding per row) and re-key every downstream table to `company_id (uuid)`, with signal→note provenance via a junction table.

**Architecture:** `signals` becomes an append-style log of findings about a company: anchored by `company_id`, classified by a governed `signal_types` vocabulary, with typed columns + a structured `payload` jsonb and an optional `raw_data` jsonb. Interpretation stays in `analysis_notes`, which links to the signals it was built from through `analysis_note_signals`. Agents only *write* signals; downstream interpretation (which table a signal affects) stays in agent logic, not in the DB. Deletion of stale signals is allowed and kept clean via `ON DELETE CASCADE`/`SET NULL`.

**Tech Stack:** Postgres 17 (Supabase), Python 3.11 (supabase-py client), pytest, ruff. Migrations applied through the Supabase MCP (`apply_migration` / `execute_sql`); schema contract mirrored in `sql/schema.sql`.

---

## Design Decisions (locked in conversation 2026-06-18)

- **Anchor key:** every table references `companies.id (uuid)`. `domain`/`normalized_domain`/`company_domain` keys are removed from `signals`, `source_links`, `analysis_notes`, `dossiers`.
- **`signals.evidence_url` UNIQUE is removed.** Idempotency moves to `dedupe_key TEXT UNIQUE`. A URL may appear in many signals.
- **`confidence`** becomes `NUMERIC(3,2)` in `0.00..1.00`. Adapters keep emitting `high/medium/low`; conversion happens at write time via a single map.
- **Atomic signals:** one finding = one row. Conclusions over many signals live in `analysis_notes`, linked through `analysis_note_signals` (junction table, chosen over an array column for referential integrity on delete).
- **`raw_data`** is optional (nullable, default `'{}'`), populated only for volatile/non-refetchable sources. No object storage yet.
- **RLS:** out of scope — do not enable in this plan.
- **Scope boundary:** removing unused/overloaded fields in `companies`/`contacts` (per `docs/DB-FIELD-AUDIT-2026-06-18.md`) is a SEPARATE follow-up plan. This plan touches `contacts`/`companies` only to add provenance FKs.

## Target Schema (reference)

```sql
-- governed vocabulary; new agents add a row, not a migration
CREATE TABLE signal_types (
    code        TEXT PRIMARY KEY,
    category    TEXT NOT NULL,          -- discovery | people | sources | monitoring | financials
    description TEXT
);

CREATE TABLE signals (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id  UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    signal_type TEXT NOT NULL REFERENCES signal_types(code),
    agent       TEXT,                                -- producer: discovery, source_expansion, dm_enrich...
    source      TEXT NOT NULL,                       -- github, huggingface, web, apollo...
    title       TEXT,                                -- short human-readable label
    url         TEXT,                                -- evidence link, NOT unique
    summary     TEXT,                                -- short description of the finding
    confidence  NUMERIC(3,2) NOT NULL DEFAULT 0.50
                CHECK (confidence >= 0 AND confidence <= 1),
    signal_date DATE NOT NULL,
    payload     JSONB NOT NULL DEFAULT '{}'::jsonb,  -- structured extracted fields
    raw_data    JSONB DEFAULT '{}'::jsonb,           -- optional raw snapshot
    run_id      UUID REFERENCES run_logs(id),
    dedupe_key  TEXT NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE analysis_note_signals (
    analysis_note_id UUID NOT NULL REFERENCES analysis_notes(id) ON DELETE CASCADE,
    signal_id        UUID NOT NULL REFERENCES signals(id)        ON DELETE CASCADE,
    role             TEXT NOT NULL DEFAULT 'supports'
                     CHECK (role IN ('supports', 'contradicts', 'context')),
    note             TEXT,
    PRIMARY KEY (analysis_note_id, signal_id)
);
```

Provenance columns added to existing tables:
`companies.created_from_signal_id`, `companies.last_signal_id` (FK signals, `ON DELETE SET NULL`); `contacts.discovered_from_signal_id` (FK signals, `ON DELETE SET NULL`); `source_links.source_signal_id` (FK signals, `ON DELETE SET NULL`). `source_links`, `analysis_notes`, `dossiers` switch `company_domain TEXT` → `company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE`. `analysis_notes.sources JSONB` is dropped (replaced by the junction table). `confidence` switches to `NUMERIC(3,2)` in `signals`, `source_links`, `analysis_notes`.

---

## File Structure

| File | Responsibility | Action |
|---|---|---|
| `sql/schema.sql` | Canonical schema contract | Rewrite signals/signal_types/junction; re-key tables; numeric confidence |
| `scripts/models.py` | Dataclasses `RawSignal`, `Confidence`, `SignalType` | Add fields; numeric confidence map; type list |
| `scripts/supabase_store.py` | `upsert_signal`, `get_signals_for_company`, company-id resolution | Rewrite signal I/O around `company_id` + `dedupe_key` |
| `scripts/dossier_store.py` | CRUD for source_links/analysis_notes/dossiers + junction | Re-key to `company_id`; add `analysis_note_signals` CRUD |
| `scripts/contacts_store.py` | Contact upsert | Add `discovered_from_signal_id` passthrough |
| `scripts/github.py`, `huggingface.py`, `greenhouse.py` | Source adapters building RawSignal | Field renames (`evidence_url`→`url`), set `agent` |
| `scripts/dm_github.py`, `dm_huggingface_contacts.py`, `enrichment.py` | Signal readers | Read `url`/`payload` instead of `evidence_url`/`raw_data` |
| `scripts/yc_browser.py` | YC discovery output | Align emitted dict keys |
| `agents/prompts/*.md` | Pipeline agent prompts | Update field/table references |
| `tests/*.py` | Unit tests + fixtures | Update fixtures to new schema |
| `docs/AGENT-ECOSYSTEM.md`, `docs/context/technical_architecture.md` | Architecture docs | Rewrite Signal Model section |

---

## Phase 0 — Prep & Reconciliation

### Task 0.1: Isolated worktree + live-schema snapshot

**Files:** none (environment + read-only DB)

- [ ] **Step 1: Create a worktree for this work**

Run: `cd kvetio-agent && git worktree add ../kvetio-signals-redesign -b signals-redesign`
Expected: new branch `signals-redesign` checked out in sibling dir.

- [ ] **Step 2: Snapshot the LIVE schema (source of truth, not schema.sql)**

Via Supabase MCP `list_tables` (project `qcfygtxkohopxhsathkv`, schema `public`, verbose) confirm the actual columns of `signals`, `companies`, `contacts`, `source_links`, `analysis_notes`, `dossiers`. Record the live `signals` columns (expected: `id, normalized_domain, source, signal_type, evidence_url, signal_date, confidence, parser_version, raw_data, created_at`).
Expected: written into the worktree as `docs/superpowers/plans/_live-schema-snapshot-2026-06-18.md`.

- [ ] **Step 3: Confirm row counts so backfill scope is known**

Via Supabase MCP `execute_sql`: `SELECT 'signals' t, count(*) FROM signals UNION ALL SELECT 'companies', count(*) FROM companies UNION ALL SELECT 'contacts', count(*) FROM contacts UNION ALL SELECT 'source_links', count(*) FROM source_links UNION ALL SELECT 'analysis_notes', count(*) FROM analysis_notes UNION ALL SELECT 'dossiers', count(*) FROM dossiers;`
Expected: ~74 signals, ~328 companies, others 0. If `source_links`/`analysis_notes`/`dossiers` are non-zero, STOP and add a backfill step for them before re-keying.

- [ ] **Step 4: Commit the snapshot**

```bash
git add docs/superpowers/plans/_live-schema-snapshot-2026-06-18.md
git commit -m "docs: snapshot live schema before signals redesign"
```

---

## Phase 1 — Database Migrations

> Each migration is applied via Supabase MCP `apply_migration` (named) and verified via `execute_sql`. Keep `sql/schema.sql` in lock-step (Task 1.7).

### Task 1.1: Create `signal_types` registry + seed

**Files:**
- DB migration: `signals_redesign_01_signal_types`
- Modify: `sql/schema.sql` (add table near `signals`)

- [ ] **Step 1: Apply the migration**

```sql
CREATE TABLE signal_types (
    code        TEXT PRIMARY KEY,
    category    TEXT NOT NULL,
    description TEXT
);

INSERT INTO signal_types (code, category, description) VALUES
  ('github_repo',          'discovery',  'Company GitHub repo/org found'),
  ('hf_org',               'discovery',  'HuggingFace organization found'),
  ('hf_model',             'discovery',  'HuggingFace model found'),
  ('job_posting',          'discovery',  'Job posting referencing the company'),
  ('papers_with_code',     'discovery',  'PapersWithCode reference'),
  ('funding_announcement',  'financials', 'Funding/round announcement'),
  ('kaggle_sponsor',       'discovery',  'Kaggle competition sponsor'),
  ('scale_customer',       'discovery',  'Listed as customer of a known vendor'),
  ('wandb_run',            'discovery',  'Weights & Biases public run'),
  ('directory_listing',    'discovery',  'Found in a directory listing'),
  ('contact_found',        'people',     'A person/contact discovered for the company'),
  ('source_link',          'sources',    'A curated source URL for analysis'),
  ('news',                 'monitoring', 'News article about the company'),
  ('product_update',       'monitoring', 'Product/release update detected');
```

- [ ] **Step 2: Verify**

`execute_sql`: `SELECT count(*) FROM signal_types;`
Expected: `14`.

- [ ] **Step 3: Mirror into `sql/schema.sql`** (add the `CREATE TABLE signal_types` + seed block immediately above the `signals` definition).

- [ ] **Step 4: Commit**

```bash
git add sql/schema.sql
git commit -m "feat(db): add signal_types governed vocabulary"
```

### Task 1.2: Add new columns to `signals` (additive, non-breaking)

**Files:** DB migration `signals_redesign_02_add_columns`

- [ ] **Step 1: Apply**

```sql
ALTER TABLE signals
  ADD COLUMN company_id  UUID REFERENCES companies(id) ON DELETE CASCADE,
  ADD COLUMN agent       TEXT,
  ADD COLUMN title       TEXT,
  ADD COLUMN url         TEXT,
  ADD COLUMN summary     TEXT,
  ADD COLUMN payload     JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN run_id      UUID REFERENCES run_logs(id),
  ADD COLUMN dedupe_key  TEXT,
  ADD COLUMN confidence_num NUMERIC(3,2),
  ADD COLUMN updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW();
```

- [ ] **Step 2: Verify columns exist**

`execute_sql`: `SELECT column_name FROM information_schema.columns WHERE table_name='signals' ORDER BY 1;`
Expected: includes `company_id, agent, title, url, summary, payload, run_id, dedupe_key, confidence_num, updated_at`.

- [ ] **Step 3: Commit** (no schema.sql change yet — final form written in 1.4)

```bash
git commit --allow-empty -m "feat(db): add new signals columns (additive)"
```

### Task 1.3: Backfill the 74 existing signals

**Files:** DB migration `signals_redesign_03_backfill`

- [ ] **Step 1: Backfill `company_id`, `url`, `confidence_num`, `dedupe_key`**

```sql
-- map old text key -> companies.id
UPDATE signals s
SET company_id = c.id
FROM companies c
WHERE c.domain = s.normalized_domain
  AND s.company_id IS NULL;

-- carry evidence_url into the new url column
UPDATE signals SET url = evidence_url WHERE url IS NULL;

-- text confidence -> numeric
UPDATE signals SET confidence_num = CASE confidence
    WHEN 'high' THEN 0.90 WHEN 'medium' THEN 0.50 WHEN 'low' THEN 0.20
    ELSE 0.50 END
WHERE confidence_num IS NULL;

-- deterministic dedupe key
UPDATE signals
SET dedupe_key = encode(digest(
    coalesce(company_id::text,'') || ':' || signal_type || ':' || coalesce(url, id::text),
    'sha1'), 'hex')
WHERE dedupe_key IS NULL;
```

- [ ] **Step 2: Find orphans (signals whose domain has no company)**

`execute_sql`: `SELECT id, normalized_domain FROM signals WHERE company_id IS NULL;`
Expected: ideally 0 rows. If any: delete them (`DELETE FROM signals WHERE company_id IS NULL;`) — dev data, non-critical, and `company_id` is about to become `NOT NULL`.

- [ ] **Step 3: Verify no NULLs in soon-to-be-required columns**

`execute_sql`: `SELECT count(*) FROM signals WHERE company_id IS NULL OR dedupe_key IS NULL OR confidence_num IS NULL;`
Expected: `0`.

- [ ] **Step 4: Commit**

```bash
git commit --allow-empty -m "chore(db): backfill signals company_id/url/dedupe_key/confidence"
```

### Task 1.4: Drop old columns/constraints, finalize `signals`

**Files:**
- DB migration `signals_redesign_04_finalize_signals`
- Modify: `sql/schema.sql` (replace whole `signals` block + indexes)

- [ ] **Step 1: Apply**

```sql
-- remove the unique that blocked multi-company URLs
ALTER TABLE signals DROP CONSTRAINT IF EXISTS signals_evidence_url_key;

-- swap confidence column
ALTER TABLE signals DROP COLUMN confidence;
ALTER TABLE signals RENAME COLUMN confidence_num TO confidence;
ALTER TABLE signals
  ALTER COLUMN confidence SET DEFAULT 0.50,
  ALTER COLUMN confidence SET NOT NULL,
  ADD CONSTRAINT signals_confidence_range CHECK (confidence >= 0 AND confidence <= 1);

-- drop legacy text keys + unused columns
ALTER TABLE signals
  DROP COLUMN normalized_domain,
  DROP COLUMN evidence_url,
  DROP COLUMN company_name,
  DROP COLUMN domain,
  DROP COLUMN linkedin_url,
  DROP COLUMN parser_version;
-- NOTE: company_name/domain/linkedin_url only exist in schema.sql's drifted
-- version; wrap each in a DO block or run guarded — see Step 2.

-- enforce new invariants
ALTER TABLE signals
  ALTER COLUMN company_id SET NOT NULL,
  ALTER COLUMN dedupe_key SET NOT NULL,
  ADD CONSTRAINT signals_dedupe_key_unique UNIQUE (dedupe_key),
  ADD CONSTRAINT signals_signal_type_fk FOREIGN KEY (signal_type) REFERENCES signal_types(code);

DROP INDEX IF EXISTS idx_signals_normalized_domain;
CREATE INDEX idx_signals_company_id ON signals (company_id);
CREATE INDEX idx_signals_company_type ON signals (company_id, signal_type);
CREATE INDEX IF NOT EXISTS idx_signals_signal_date ON signals (signal_date DESC);

DROP TRIGGER IF EXISTS trg_signals_updated_at ON signals;
CREATE TRIGGER trg_signals_updated_at
BEFORE UPDATE ON signals
FOR EACH ROW EXECUTE FUNCTION update_updated_at();
```

- [ ] **Step 2: Guard columns that may not exist in the live DB**

Because live `signals` lacks `company_name/domain/linkedin_url`, run those drops defensively first:

```sql
ALTER TABLE signals DROP COLUMN IF EXISTS company_name;
ALTER TABLE signals DROP COLUMN IF EXISTS domain;
ALTER TABLE signals DROP COLUMN IF EXISTS linkedin_url;
```

- [ ] **Step 3: Verify final shape**

`execute_sql`: `SELECT column_name, data_type FROM information_schema.columns WHERE table_name='signals' ORDER BY 1;`
Expected: `agent, company_id, confidence(numeric), created_at, dedupe_key, id, payload, raw_data, run_id, signal_date, signal_type, source, summary, title, updated_at, url`.

- [ ] **Step 4: Replace the `signals` block in `sql/schema.sql`** with the Target Schema version (see top of plan) including indexes and trigger.

- [ ] **Step 5: Commit**

```bash
git add sql/schema.sql
git commit -m "feat(db): finalize signals around company_id + dedupe_key"
```

### Task 1.5: Re-key `source_links`, `analysis_notes`, `dossiers` to `company_id`

**Files:**
- DB migration `signals_redesign_05_rekey_domain_tables`
- Modify: `sql/schema.sql` (three table blocks)

Tables are empty (verified in Task 0.1 Step 3), so this is a structural change with no backfill.

- [ ] **Step 1: Apply**

```sql
-- source_links
ALTER TABLE source_links DROP CONSTRAINT IF EXISTS source_links_company_domain_kind_url_key;
ALTER TABLE source_links DROP COLUMN company_domain;
ALTER TABLE source_links ADD COLUMN company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE;
ALTER TABLE source_links ADD COLUMN source_signal_id UUID REFERENCES signals(id) ON DELETE SET NULL;
ALTER TABLE source_links ADD CONSTRAINT source_links_unique UNIQUE (company_id, kind, url);
ALTER TABLE source_links DROP COLUMN confidence;
ALTER TABLE source_links ADD COLUMN confidence NUMERIC(3,2) NOT NULL DEFAULT 0.50
    CHECK (confidence >= 0 AND confidence <= 1);
DROP INDEX IF EXISTS idx_source_links_company;
CREATE INDEX idx_source_links_company ON source_links (company_id);

-- analysis_notes
ALTER TABLE analysis_notes DROP CONSTRAINT IF EXISTS analysis_notes_company_domain_section_version_key;
ALTER TABLE analysis_notes DROP COLUMN company_domain;
ALTER TABLE analysis_notes ADD COLUMN company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE;
ALTER TABLE analysis_notes DROP COLUMN sources;          -- replaced by junction table
ALTER TABLE analysis_notes DROP COLUMN confidence;
ALTER TABLE analysis_notes ADD COLUMN confidence NUMERIC(3,2) NOT NULL DEFAULT 0.50
    CHECK (confidence >= 0 AND confidence <= 1);
ALTER TABLE analysis_notes ADD CONSTRAINT analysis_notes_unique UNIQUE (company_id, section, version);
DROP INDEX IF EXISTS idx_analysis_notes_company;
CREATE INDEX idx_analysis_notes_company ON analysis_notes (company_id);

-- dossiers
ALTER TABLE dossiers DROP CONSTRAINT dossiers_pkey;
ALTER TABLE dossiers DROP COLUMN company_domain;
ALTER TABLE dossiers ADD COLUMN company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE;
ALTER TABLE dossiers ADD CONSTRAINT dossiers_pkey PRIMARY KEY (company_id);
```

- [ ] **Step 2: Verify**

`execute_sql`: `SELECT table_name, column_name FROM information_schema.columns WHERE table_name IN ('source_links','analysis_notes','dossiers') AND column_name IN ('company_id','company_domain','sources','source_signal_id') ORDER BY 1,2;`
Expected: `company_id` present in all three; no `company_domain`; no `sources`; `source_signal_id` in `source_links`.

- [ ] **Step 3: Mirror the three table blocks into `sql/schema.sql`.**

- [ ] **Step 4: Commit**

```bash
git add sql/schema.sql
git commit -m "feat(db): re-key source_links/analysis_notes/dossiers to company_id"
```

### Task 1.6: Junction table + provenance FKs on `companies`/`contacts`

**Files:**
- DB migration `signals_redesign_06_junction_and_provenance`
- Modify: `sql/schema.sql`

- [ ] **Step 1: Apply**

```sql
CREATE TABLE analysis_note_signals (
    analysis_note_id UUID NOT NULL REFERENCES analysis_notes(id) ON DELETE CASCADE,
    signal_id        UUID NOT NULL REFERENCES signals(id)        ON DELETE CASCADE,
    role             TEXT NOT NULL DEFAULT 'supports'
                     CHECK (role IN ('supports', 'contradicts', 'context')),
    note             TEXT,
    PRIMARY KEY (analysis_note_id, signal_id)
);
CREATE INDEX idx_ans_signal ON analysis_note_signals (signal_id);

ALTER TABLE companies
  ADD COLUMN created_from_signal_id UUID REFERENCES signals(id) ON DELETE SET NULL,
  ADD COLUMN last_signal_id         UUID REFERENCES signals(id) ON DELETE SET NULL;

ALTER TABLE contacts
  ADD COLUMN discovered_from_signal_id UUID REFERENCES signals(id) ON DELETE SET NULL;
```

- [ ] **Step 2: Verify**

`execute_sql`: `SELECT to_regclass('public.analysis_note_signals');` → not null; and confirm the three FK columns exist via `information_schema.columns`.

- [ ] **Step 3: Mirror into `sql/schema.sql`.**

- [ ] **Step 4: Commit**

```bash
git add sql/schema.sql
git commit -m "feat(db): add analysis_note_signals junction + provenance FKs"
```

### Task 1.7: Generate fresh types & confirm schema.sql parity

**Files:** none (verification)

- [ ] **Step 1: Diff intent vs reality**

`execute_sql`: dump `information_schema.columns` for all public tables, compare against `sql/schema.sql`. Fix any mismatch by editing `sql/schema.sql` only (DB is source of truth now).

- [ ] **Step 2: Commit any schema.sql corrections**

```bash
git add sql/schema.sql
git commit -m "docs(db): reconcile schema.sql with live DB"
```

---

## Phase 2 — Python Data Layer

### Task 2.1: `models.py` — confidence map + RawSignal fields

**Files:**
- Modify: `scripts/models.py`
- Test: `tests/test_models_signals.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_models_signals.py
from datetime import date
from scripts.models import RawSignal, confidence_to_score


def test_confidence_to_score_maps_labels():
    assert confidence_to_score("high") == 0.9
    assert confidence_to_score("medium") == 0.5
    assert confidence_to_score("low") == 0.2
    assert confidence_to_score(0.73) == 0.73


def test_rawsignal_has_url_and_agent():
    s = RawSignal(
        source="github", signal_type="github_repo", company_name="Acme",
        domain="acme.com", linkedin_url=None, url="https://github.com/acme",
        signal_date=date(2026, 6, 1), confidence="high", agent="discovery",
    )
    assert s.url == "https://github.com/acme"
    assert s.agent == "discovery"
```

- [ ] **Step 2: Run it, verify failure**

Run: `cd kvetio-agent && python -m pytest tests/test_models_signals.py -v`
Expected: FAIL — `confidence_to_score` and `RawSignal.url`/`agent` do not exist.

- [ ] **Step 3: Edit `scripts/models.py`**

Add the score map and helper near the `Confidence` definition:

```python
CONFIDENCE_SCORE: dict[str, float] = {"high": 0.9, "medium": 0.5, "low": 0.2}


def confidence_to_score(value: "Confidence | float") -> float:
    if isinstance(value, (int, float)):
        return float(value)
    return CONFIDENCE_SCORE.get(value, 0.5)
```

Replace the `RawSignal` dataclass body: rename `evidence_url` → `url`, add `agent: str | None = None`, `title: str | None = None`, `summary: str | None = None`. Update `__post_init__` to validate `url`:

```python
@dataclass(frozen=True)
class RawSignal:
    source: str
    signal_type: SignalType
    company_name: str
    domain: str | None
    linkedin_url: str | None
    url: str
    signal_date: date
    confidence: Confidence
    agent: str | None = None
    title: str | None = None
    summary: str | None = None
    raw_payload: dict = field(default_factory=dict)
    payload: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("RawSignal.url обязателен")
        if not self.company_name.strip():
            raise ValueError("RawSignal.company_name не может быть пустым")
```

Add the new `signal_types` to the `SignalType` Literal: `"contact_found", "source_link", "news", "product_update"`.

- [ ] **Step 4: Run the test, verify pass**

Run: `python -m pytest tests/test_models_signals.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/models.py tests/test_models_signals.py
git commit -m "feat(models): RawSignal.url/agent + numeric confidence map"
```

### Task 2.2: `supabase_store.py` — company-id resolution + new `upsert_signal`

**Files:**
- Modify: `scripts/supabase_store.py:141-173`
- Test: `tests/test_dedup.py` (update)

- [ ] **Step 1: Update the failing test**

Replace the signal-upsert test in `tests/test_dedup.py` so it asserts conflict on `dedupe_key` (not `evidence_url`) and that a `company_id` is resolved. Use the existing fake-client fixture pattern in that file:

```python
def test_upsert_signal_uses_dedupe_key(fake_store):
    sig = make_raw_signal(url="https://github.com/acme", signal_type="github_repo")
    fake_store.upsert_signal(sig, company_id="11111111-1111-1111-1111-111111111111")
    call = fake_store._client.table_calls[-1]
    assert call["on_conflict"] == "dedupe_key"
    assert "dedupe_key" in call["row"]
    assert call["row"]["company_id"] == "11111111-1111-1111-1111-111111111111"
    assert call["row"]["url"] == "https://github.com/acme"
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_dedup.py -v`
Expected: FAIL — signature/keys differ.

- [ ] **Step 3: Implement**

Add a resolver and rewrite `upsert_signal` + `get_signals_for_company` in `scripts/supabase_store.py`:

```python
import hashlib
from .models import confidence_to_score  # adjust to existing import style

def resolve_company_id(self, *, company_id: str | None = None, domain: str | None = None) -> str | None:
    if company_id:
        return company_id
    if not domain:
        return None
    res = self._client.table("companies").select("id").eq("domain", domain).limit(1).execute()
    rows = res.data or []
    return rows[0]["id"] if rows else None

@staticmethod
def _dedupe_key(company_id: str, signal_type: str, url: str | None, fallback: str) -> str:
    basis = f"{company_id}:{signal_type}:{url or fallback}"
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()

def upsert_signal(self, signal: "RawSignal", *, company_id: str | None = None,
                  domain: str | None = None, run_id: str | None = None) -> bool:
    cid = self.resolve_company_id(company_id=company_id, domain=domain or signal.domain)
    if not cid:
        raise ValueError(f"upsert_signal: no company for domain={domain or signal.domain}")
    dedupe = self._dedupe_key(cid, signal.signal_type, signal.url, fallback=str(signal.signal_date))
    row = {
        "company_id": cid,
        "signal_type": signal.signal_type,
        "agent": signal.agent,
        "source": signal.source,
        "title": signal.title,
        "url": signal.url,
        "summary": signal.summary,
        "confidence": confidence_to_score(signal.confidence),
        "signal_date": signal.signal_date.isoformat(),
        "payload": signal.payload or {},
        "raw_data": signal.raw_payload or {},
        "run_id": run_id,
        "dedupe_key": dedupe,
    }
    res = (self._client.table("signals")
           .upsert(row, on_conflict="dedupe_key", ignore_duplicates=True)
           .execute())
    return bool(res.data)

def get_signals_for_company(self, domain: str) -> list[dict]:
    cid = self.resolve_company_id(domain=domain)
    if not cid:
        return []
    res = (self._client.table("signals").select("*")
           .eq("company_id", cid).order("signal_date", desc=True).execute())
    return res.data or []
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_dedup.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/supabase_store.py tests/test_dedup.py
git commit -m "feat(store): signals I/O via company_id + dedupe_key"
```

### Task 2.3: `dossier_store.py` — re-key + junction CRUD

**Files:**
- Modify: `scripts/dossier_store.py:26-113`
- Test: `tests/test_dossier_store.py` (update)

- [ ] **Step 1: Update failing tests** in `tests/test_dossier_store.py` so source-link/analysis-note/dossier helpers take `company_id` and assert the new conflict keys; add a test for `link_note_to_signals`.

```python
def test_upsert_source_link_keyed_by_company_id(fake_store):
    upsert_source_link(fake_store, {
        "company_id": "cid-1", "kind": "github_org",
        "url": "https://github.com/acme", "source": "resolver"})
    call = fake_store._client.table_calls[-1]
    assert call["on_conflict"] == "company_id,kind,url"
    assert call["row"]["company_id"] == "cid-1"

def test_link_note_to_signals_inserts_rows(fake_store):
    link_note_to_signals(fake_store, "note-1", ["sig-1", "sig-2"], role="supports")
    call = fake_store._client.table_calls[-1]
    assert call["table"] == "analysis_note_signals"
    assert len(call["rows"]) == 2
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_dossier_store.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement** — change every `company_domain` parameter/key to `company_id`, drop the `sources` field from `upsert_analysis_note`, convert `confidence` through `confidence_to_score`, and add the junction helper:

```python
from models import confidence_to_score

def upsert_source_link(store, link: dict) -> None:
    row = {
        "company_id": link["company_id"],
        "kind": link["kind"], "url": link["url"],
        "source": link.get("source", "unknown"),
        "confidence": confidence_to_score(link.get("confidence", "medium")),
        "found_via": link.get("found_via"),
        "source_signal_id": link.get("source_signal_id"),
        "raw": link.get("raw", {}),
        "fetched_at": datetime.utcnow().isoformat(),
    }
    store._client.table("source_links").upsert(row, on_conflict="company_id,kind,url").execute()

def upsert_analysis_note(store, note: dict) -> str:
    row = {
        "company_id": note["company_id"], "section": note["section"],
        "facts": note.get("facts", {}),
        "confidence": confidence_to_score(note.get("confidence", "medium")),
        "model": note.get("model"), "version": note.get("version", "v1"),
        "created_at": datetime.utcnow().isoformat(),
    }
    res = store._client.table("analysis_notes").upsert(
        row, on_conflict="company_id,section,version").execute()
    return (res.data or [{}])[0].get("id")

def link_note_to_signals(store, note_id: str, signal_ids: list[str],
                         role: str = "supports") -> None:
    rows = [{"analysis_note_id": note_id, "signal_id": sid, "role": role}
            for sid in signal_ids]
    if rows:
        store._client.table("analysis_note_signals").upsert(
            rows, on_conflict="analysis_note_id,signal_id").execute()

def get_source_links(store, company_id: str) -> list[dict]: ...   # .eq("company_id", company_id)
def get_analysis_notes(store, company_id: str) -> list[dict]: ... # .eq("company_id", company_id)
def upsert_dossier(store, dossier: dict) -> None: ...             # key company_id, on_conflict="company_id"
def get_dossier(store, company_id: str) -> dict | None: ...       # .eq("company_id", company_id)
```

Update the CLI `_build_parser`/`_run` arg help text from `company_domain` to `company_id`.

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_dossier_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/dossier_store.py tests/test_dossier_store.py
git commit -m "feat(dossier-store): company_id keying + note->signal linking"
```

### Task 2.4: `contacts_store.py` — provenance passthrough

**Files:**
- Modify: `scripts/contacts_store.py:145-175`
- Test: `tests/test_contacts_store.py` (update)

- [ ] **Step 1: Add failing assertion** that `upsert_contact` forwards `discovered_from_signal_id` when present.

```python
def test_upsert_contact_forwards_signal_provenance(fake_store):
    upsert_contact(fake_store, {
        "company_id": "cid-1", "first_name": "Sam", "last_name": "Lee",
        "discovered_from_signal_id": "sig-9"})
    row = fake_store._client.table_calls[-1]["row"]
    assert row["discovered_from_signal_id"] == "sig-9"
```

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_contacts_store.py -v`
Expected: FAIL — key not forwarded.

- [ ] **Step 3: Implement** — in `upsert_contact`, add to the `row` dict:

```python
    if contact.get("discovered_from_signal_id"):
        row["discovered_from_signal_id"] = contact["discovered_from_signal_id"]
```

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_contacts_store.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/contacts_store.py tests/test_contacts_store.py
git commit -m "feat(contacts-store): forward discovered_from_signal_id"
```

---

## Phase 3 — Adapters & Agents

### Task 3.1: Source adapters emit new RawSignal shape

**Files:**
- Modify: `scripts/github.py:162,249`, `scripts/huggingface.py:182,240-242`, `scripts/greenhouse.py:199,244`, `scripts/yc_browser.py:284`
- Test: `tests/test_github.py`, `tests/test_huggingface.py`, `tests/test_greenhouse.py`

- [ ] **Step 1: Update tests first** — in each adapter test, change `evidence_url=` to `url=`, add `agent="discovery"` to expected RawSignal, and assert `payload` (not only `raw_payload`) is populated.

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_github.py tests/test_huggingface.py tests/test_greenhouse.py -v`
Expected: FAIL — keyword `evidence_url` no longer accepted.

- [ ] **Step 3: Implement** — in each adapter, rename the `RawSignal(evidence_url=...)` kwarg to `url=...`, pass `agent="discovery"`, and move the structured fields that were stuffed into `raw_payload` (e.g. huggingface `pipeline_tags/num_models/num_members`) into `payload=`, leaving `raw_payload` for the untouched raw API response (or `{}`). In `yc_browser.py:284` rename the emitted dict key `raw_data` → `payload` to match.

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_github.py tests/test_huggingface.py tests/test_greenhouse.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/github.py scripts/huggingface.py scripts/greenhouse.py scripts/yc_browser.py tests/
git commit -m "feat(adapters): emit RawSignal.url/agent/payload"
```

### Task 3.2: Signal readers use new field names

**Files:**
- Modify: `scripts/dm_github.py:61-66`, `scripts/dm_huggingface_contacts.py:35-40`, `scripts/enrichment.py:55-65`
- Test: `tests/test_dm_github.py`, `tests/test_dm_huggingface_contacts.py`, `tests/test_enrichment.py`

- [ ] **Step 1: Update tests** — fixtures returned by `get_signals_for_company` must use `url`/`payload` keys instead of `evidence_url`/`raw_data`; and `resolve` outputs `company_id` instead of `company_domain`.

- [ ] **Step 2: Run, verify failure**

Run: `python -m pytest tests/test_dm_github.py tests/test_dm_huggingface_contacts.py tests/test_enrichment.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement** — replace `sig.get("evidence_url")` with `sig.get("url")` in `dm_github.py` and `enrichment.py`; in `dm_huggingface_contacts.py` read the org from `sig.get("payload", {})` / `sig.get("url")`. In `enrichment.py` `GithubOrgResolver.resolve`, change the returned dict key `company_domain` → `company_id` (resolve via `company["id"]`).

- [ ] **Step 4: Run, verify pass**

Run: `python -m pytest tests/test_dm_github.py tests/test_dm_huggingface_contacts.py tests/test_enrichment.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/dm_github.py scripts/dm_huggingface_contacts.py scripts/enrichment.py tests/
git commit -m "feat(readers): consume signals via url/payload/company_id"
```

### Task 3.3: Update pipeline agent prompts

**Files:**
- Modify: `agents/prompts/*.md` (only those referencing schema)

- [ ] **Step 1: Find references**

Run: `grep -rln "evidence_url\|company_domain\|normalized_domain\|analysis_notes.sources\|signals(" agents/prompts`
Expected: a list of prompt files mentioning old field/table names.

- [ ] **Step 2: Edit each hit** — replace `company_domain`/`normalized_domain` references with `company_id`; describe that the analyst writes `analysis_notes` and links supporting signals via `analysis_note_signals` (role `supports`/`contradicts`/`context`); state that `signals` now carries `payload` (structured) + optional `raw_data`, keyed by `company_id`, deduped by `dedupe_key`.

- [ ] **Step 3: Sanity check no stale refs remain**

Run: `grep -rn "evidence_url\|company_domain\|normalized_domain" agents/prompts; echo "exit:$?"`
Expected: no matches.

- [ ] **Step 4: Commit**

```bash
git add agents/prompts
git commit -m "docs(prompts): align pipeline prompts with signals redesign"
```

---

## Phase 4 — Test Suite Sweep

### Task 4.1: Migrations & schema tests

**Files:**
- Modify: `tests/test_migrations.py`

- [ ] **Step 1: Update expectations** — if `test_migrations.py` asserts column/constraint names, update to the new `signals` shape and presence of `signal_types`, `analysis_note_signals`.

- [ ] **Step 2: Run**

Run: `python -m pytest tests/test_migrations.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_migrations.py
git commit -m "test: update schema/migration expectations"
```

### Task 4.2: Full suite green + lint

**Files:** none

- [ ] **Step 1: Run the whole suite**

Run: `python -m pytest -q`
Expected: all pass. Fix any straggler fixtures still using `evidence_url`/`company_domain` (search: `grep -rn "evidence_url\|company_domain\|normalized_domain" tests`).

- [ ] **Step 2: Lint**

Run: `ruff check scripts tests`
Expected: no errors.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A && git commit -m "test: full suite green after signals redesign"
```

---

## Phase 5 — Documentation

### Task 5.1: Rewrite the Signal Model docs

**Files:**
- Modify: `docs/AGENT-ECOSYSTEM.md` (Signal Model section, ~lines 100-120)
- Modify: `docs/context/technical_architecture.md:79,168`

- [ ] **Step 1: Edit `AGENT-ECOSYSTEM.md`** — replace the "Signal Model" section: signals are atomic findings anchored by `company_id`, typed via the `signal_types` registry (categories discovery/people/sources/monitoring/financials), carrying `payload` + optional `raw_data`, deduped by `dedupe_key`; provenance flows `signals → companies/contacts/source_links` via FK columns and `signals → analysis_notes` via `analysis_note_signals`. Note deletion of stale signals is allowed and cascades.

- [ ] **Step 2: Edit `technical_architecture.md`** — update line 79 storage list and line 168 ("normalized signals") to reflect `company_id` anchoring + payload/raw split.

- [ ] **Step 3: Add a changelog note** to `docs/DB-FIELD-AUDIT-2026-06-18.md` pointing to this redesign and the new schema.

- [ ] **Step 4: Commit**

```bash
git add docs
git commit -m "docs: document redesigned signals architecture"
```

---

## Phase 6 — Verification & Handoff

### Task 6.1: End-to-end smoke against the live DB

**Files:** none

- [ ] **Step 1: Insert one real signal through the store** (temporary script or REPL) for an existing company domain; confirm row lands with `company_id`, numeric `confidence`, `dedupe_key`.

`execute_sql`: `SELECT company_id, signal_type, confidence, dedupe_key FROM signals ORDER BY created_at DESC LIMIT 1;`
Expected: one well-formed row.

- [ ] **Step 2: Re-insert the same signal; confirm idempotency** (no duplicate; `upsert_signal` returns False).

`execute_sql`: `SELECT count(*) FROM signals WHERE dedupe_key = '<key from step 1>';`
Expected: `1`.

- [ ] **Step 3: Delete that signal; confirm provenance FKs go NULL not error.**

`execute_sql`: `DELETE FROM signals WHERE dedupe_key='<key>'; SELECT 1;`
Expected: success, no FK violation.

- [ ] **Step 4: Run advisors** (Supabase MCP `get_advisors`) and note (do not fix here) the pre-existing RLS warning — RLS is out of scope.

- [ ] **Step 5: Final commit + push**

```bash
git add -A && git commit -m "chore: signals redesign complete" && git push -u origin signals-redesign
```

### Task 6.2: Merge

Use superpowers:finishing-a-development-branch to choose merge/PR and clean up the worktree.

---

## Self-Review Notes

- **Spec coverage:** signals redesign (Tasks 1.1–1.4, 2.1–2.2), company_id re-keying (1.5, 2.3), junction table (1.6, 2.3), provenance FKs (1.6, 2.4), confidence numeric (1.4/1.5, 2.1), agents/scripts updates (3.1–3.3), tests (Phase 4), docs (Phase 5). ✅
- **Out of scope, flagged:** `companies`/`contacts` field-bloat cleanup → separate plan; RLS → deliberately deferred.
- **Type consistency:** `confidence_to_score`, `RawSignal.url`, `upsert_signal(company_id=…/domain=…)`, `link_note_to_signals(note_id, signal_ids, role)` used consistently across Tasks 2.x and 3.x.
- **Risk:** schema.sql ↔ live DB drift — handled by treating the live DB as source of truth (Task 0.1, 1.7) and using `DROP COLUMN IF EXISTS` guards (Task 1.4 Step 2).
