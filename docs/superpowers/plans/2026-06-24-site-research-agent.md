# Site Research Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить в `kvetio-agent` связку «SiteResearchAgent + вложенная проверка релевантности»: разбор сайта компании со `status='new'`, оценка релевантности, извлечение контактов/продукта/прессы/партнёрств/финансов/года/страны в БД, со скрапингом через agent-browser CLI (экономия токенов) и fallback на httpx+BeautifulSoup.

**Architecture:** Один агент-промпт-оркестратор + вложенный промпт релевантности. Весь скрапинг инкапсулирован в `scripts/site_fetch.py` (agent-browser CLI → компактный JSON, fallback httpx+BS). Запись в БД через существующий `contacts_store.upsert_contact` (контакты) и новый `research_notes_store.py` (заметки + category). Новый пайплайн параллелен существующему `discovered→relevant`, таблицу `research_records` не трогает.

**Tech Stack:** Python 3.11, httpx, BeautifulSoup4, Supabase (supabase-py), agent-browser CLI (Rust, опционально), pytest, ruff.

**Спека:** `docs/superpowers/specs/2026-06-23-site-research-agent-design.md`

---

## File Structure

- Create: `sql/migrations/034_site_research.sql` — миграция (новые статусы, `companies.category`, `category_options`, `research_notes`).
- Modify: `sql/schema.sql` — отразить миграцию в каноничной схеме.
- Create: `scripts/site_fetch.py` — скрапинг сайта (agent-browser CLI + fallback), JSON в stdout.
- Create: `scripts/research_notes_store.py` — upsert заметок + управление `category`/`category_options`.
- Create: `agents/prompts/site_research_task.md` — промпт-оркестратор.
- Create: `agents/prompts/relevance_check_task.md` — промпт вложенной проверки релевантности.
- Create: `tests/test_site_fetch.py` — юнит-тесты скрапера.
- Create: `tests/test_research_notes_store.py` — юнит-тесты записи заметок/категорий.
- Modify: `tests/test_migrations.py` — НЕ требуется правок если тест авто-подхватывает все миграции; иначе добавить 034 (проверить в Task 1).
- Modify: `ARCHITECTURE.md` — раздел агентов, схема БД, новые статусы (финальная задача).

---

## Task 1: Миграция БД

**Files:**
- Create: `sql/migrations/034_site_research.sql`
- Modify: `sql/schema.sql`
- Test: `tests/test_migrations.py` (проверить, как он находит миграции)

- [ ] **Step 1: Изучить, как тест миграций обнаруживает файлы**

Run: `sed -n '1,60p' tests/test_migrations.py`
Цель: понять, итерирует ли тест по `sql/migrations/*.sql` автоматически (тогда новый файл подхватится) или содержит явный список. Если список явный — добавить `034_site_research.sql` в него на шаге 5.

- [ ] **Step 2: Посмотреть текущий CHECK-констрейнт статусов**

Run: `sed -n '34,48p' sql/schema.sql`
Expected: увидеть `companies_status_check CHECK (status IN (...))` — записать текущий список значений, чтобы расширить его, а не заменить.

- [ ] **Step 3: Написать миграцию**

Create `sql/migrations/034_site_research.sql`:

```sql
-- 034_site_research.sql
-- Новый пайплайн "разбор сайта": статусы new/site_researched, category + справочник,
-- таблица research_notes. Существующий research_records НЕ трогаем.

BEGIN;

-- 1. Расширяем допустимые статусы компании (добавляем 'new', 'site_researched').
ALTER TABLE companies DROP CONSTRAINT IF EXISTS companies_status_check;
ALTER TABLE companies ADD CONSTRAINT companies_status_check CHECK (status IN (
    'discovered', 'relevant', 'not_relevant', 'manual_review', 'data_partner',
    'new', 'site_researched'
));

-- 2. Справочник категорий (Notion-select).
CREATE TABLE IF NOT EXISTS category_options (
    value      TEXT PRIMARY KEY,
    label      TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO category_options (value, label) VALUES
    ('data_provider',     'Data provider'),
    ('product_builder',   'Builds product'),
    ('llm_wrapper',       'LLM wrapper'),
    ('big_tech_ai',       'Big tech with AI product'),
    ('non_tech_product',  'Non-tech, builds own product'),
    ('startup_own_model', 'Startup building own model'),
    ('closed_project',    'Closed project')
ON CONFLICT (value) DO NOTHING;

-- 3. companies.category (FK на справочник).
ALTER TABLE companies ADD COLUMN IF NOT EXISTS category TEXT
    REFERENCES category_options(value);

-- 4. research_notes — заметки нового пайплайна.
CREATE TABLE IF NOT EXISTS research_notes (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id   UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    note_type    TEXT NOT NULL CONSTRAINT research_notes_type_check CHECK (
                     note_type IN ('product', 'press_release', 'cooperative', 'finance')),
    content      TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    source_url   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (company_id, note_type, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_research_notes_company ON research_notes (company_id);

COMMIT;
```

- [ ] **Step 4: Отразить изменения в schema.sql**

В `sql/schema.sql`: (a) расширить `companies_status_check` теми же значениями `'new'`, `'site_researched'`; (b) добавить столбец `category TEXT REFERENCES category_options(value)` в определение `companies` (после `country`); (c) добавить определения таблиц `category_options` и `research_notes` (тот же DDL без `IF NOT EXISTS`/`BEGIN`). Поместить `category_options` ДО `companies`, если `companies.category` ссылается на неё через inline-FK, иначе оставить FK как отдельный ALTER в конце секции companies.

- [ ] **Step 5: Прогнать тест миграций**

Run: `cd /path/to/kvetio-agent && python -m pytest tests/test_migrations.py -v`
Expected: PASS. Если тест содержал явный список миграций и упал — добавить `034_site_research.sql` в список и перезапустить.

- [ ] **Step 6: Commit**

```bash
git add sql/migrations/034_site_research.sql sql/schema.sql tests/test_migrations.py
git commit -m "feat(db): site-research migration — new statuses, category, research_notes"
```

---

## Task 2: site_fetch.py — парсинг снапшота и классификация ссылок (TDD)

Начинаем с чистых функций (парсинг/классификация), которые не требуют сети и легко тестируются. Subprocess-обёртку добавим в Task 3.

**Files:**
- Create: `scripts/site_fetch.py`
- Test: `tests/test_site_fetch.py`

- [ ] **Step 1: Написать падающий тест на классификацию ссылок**

Create `tests/test_site_fetch.py`:

```python
from scripts.site_fetch import classify_link


def test_classify_link_types():
    assert classify_link("https://www.linkedin.com/company/acme") == "linkedin"
    assert classify_link("https://github.com/acme") == "github"
    assert classify_link("https://huggingface.co/acme") == "huggingface"
    assert classify_link("https://twitter.com/acme") == "x"
    assert classify_link("https://x.com/acme") == "x"
    assert classify_link("https://facebook.com/acme") == "facebook"
    assert classify_link("https://instagram.com/acme") == "instagram"
    assert classify_link("mailto:hello@acme.ai") == "email"
    assert classify_link("https://acme.ai/random") is None
```

- [ ] **Step 2: Запустить тест — убедиться, что падает**

Run: `python -m pytest tests/test_site_fetch.py::test_classify_link_types -v`
Expected: FAIL — `ModuleNotFoundError` или `ImportError: cannot import name 'classify_link'`.

- [ ] **Step 3: Реализовать classify_link**

Create `scripts/site_fetch.py`:

```python
"""Site scraping for SiteResearchAgent.

Wraps the agent-browser CLI to fetch a compact accessibility snapshot of a
company site (token-efficient vs raw HTML), with an httpx+BeautifulSoup
fallback. Outputs a compact JSON the agent consumes; the agent itself never
makes HTTP calls.

CLI: python scripts/site_fetch.py --domain acme.ai [--max-pages 5] [--json]
"""
from __future__ import annotations

import re

_LINK_RULES: list[tuple[str, str]] = [
    ("linkedin", r"linkedin\.com"),
    ("github", r"github\.com"),
    ("huggingface", r"huggingface\.co"),
    ("x", r"(?:twitter\.com|x\.com)"),
    ("facebook", r"facebook\.com"),
    ("instagram", r"instagram\.com"),
]


def classify_link(url: str) -> str | None:
    """Return the external-link type for a URL, or None if not recognized."""
    if url.startswith("mailto:"):
        return "email"
    for kind, pattern in _LINK_RULES:
        if re.search(pattern, url, re.IGNORECASE):
            return kind
    return None
```

- [ ] **Step 4: Запустить тест — убедиться, что проходит**

Run: `python -m pytest tests/test_site_fetch.py::test_classify_link_types -v`
Expected: PASS.

- [ ] **Step 5: Падающий тест на парсинг снапшота**

Append to `tests/test_site_fetch.py`:

```python
from scripts.site_fetch import parse_snapshot


def test_parse_snapshot_extracts_links_emails_text():
    # Shape mirrors `agent-browser snapshot -i --urls --json` data payload.
    snapshot = {
        "snapshot": "- heading \"Acme\"\n- link \"LinkedIn\"\n- link \"Careers\"",
        "refs": {
            "e1": {"role": "heading", "name": "Acme"},
            "e2": {"role": "link", "name": "LinkedIn",
                   "url": "https://linkedin.com/company/acme"},
            "e3": {"role": "link", "name": "Careers",
                   "url": "https://acme.ai/careers"},
            "e4": {"role": "link", "name": "Email",
                   "url": "mailto:hi@acme.ai"},
        },
    }
    parsed = parse_snapshot("https://acme.ai", snapshot)
    assert parsed["text"].startswith("- heading")
    assert {"type": "linkedin", "url": "https://linkedin.com/company/acme"} in parsed["external_links"]
    assert "hi@acme.ai" in parsed["emails"]
    # internal links are kept separately for sub-page crawling
    assert "https://acme.ai/careers" in [l["url"] for l in parsed["internal_links"]]
```

- [ ] **Step 6: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_site_fetch.py::test_parse_snapshot_extracts_links_emails_text -v`
Expected: FAIL — `ImportError: cannot import name 'parse_snapshot'`.

- [ ] **Step 7: Реализовать parse_snapshot**

Append to `scripts/site_fetch.py`:

```python
from urllib.parse import urlparse


def _same_host(base: str, url: str) -> bool:
    return urlparse(base).netloc == urlparse(url).netloc


def parse_snapshot(page_url: str, snapshot: dict) -> dict:
    """Turn an agent-browser snapshot payload into structured page data.

    Returns {url, text, external_links, internal_links, emails}.
    """
    text = snapshot.get("snapshot", "") or ""
    external_links: list[dict] = []
    internal_links: list[dict] = []
    emails: list[str] = []
    seen_ext: set[str] = set()

    for ref in (snapshot.get("refs") or {}).values():
        url = ref.get("url")
        if not url:
            continue
        kind = classify_link(url)
        if kind == "email":
            addr = url[len("mailto:"):].split("?")[0]
            if addr and addr not in emails:
                emails.append(addr)
        elif kind is not None:
            if url not in seen_ext:
                external_links.append({"type": kind, "url": url})
                seen_ext.add(url)
        elif url.startswith("http") and _same_host(page_url, url):
            internal_links.append({"url": url, "name": ref.get("name", "")})

    return {
        "url": page_url,
        "text": text,
        "external_links": external_links,
        "internal_links": internal_links,
        "emails": emails,
    }
```

- [ ] **Step 8: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_site_fetch.py::test_parse_snapshot_extracts_links_emails_text -v`
Expected: PASS.

- [ ] **Step 9: Падающий тест на отбор приоритетных подстраниц**

Append to `tests/test_site_fetch.py`:

```python
from scripts.site_fetch import select_subpages


def test_select_subpages_prioritizes_keywords():
    links = [
        {"url": "https://acme.ai/blog/post-1", "name": "Blog post 1"},
        {"url": "https://acme.ai/about", "name": "About us"},
        {"url": "https://acme.ai/random", "name": "Random"},
        {"url": "https://acme.ai/careers", "name": "Careers"},
        {"url": "https://acme.ai/pricing", "name": "Pricing"},
    ]
    chosen = select_subpages(links, max_pages=3)
    # keyword pages ranked first; non-keyword 'random' excluded when over budget
    assert "https://acme.ai/about" in chosen
    assert "https://acme.ai/careers" in chosen
    assert len(chosen) == 3
    assert "https://acme.ai/random" not in chosen
```

- [ ] **Step 10: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_site_fetch.py::test_select_subpages_prioritizes_keywords -v`
Expected: FAIL — `ImportError: cannot import name 'select_subpages'`.

- [ ] **Step 11: Реализовать select_subpages**

Append to `scripts/site_fetch.py`:

```python
_PRIORITY_KEYWORDS = (
    "about", "team", "career", "job", "blog", "news", "press",
    "pricing", "contact", "company",
)


def select_subpages(internal_links: list[dict], max_pages: int = 5) -> list[str]:
    """Pick up to max_pages internal URLs, prioritizing keyword-bearing ones."""
    def score(link: dict) -> int:
        hay = (link["url"] + " " + link.get("name", "")).lower()
        return sum(1 for kw in _PRIORITY_KEYWORDS if kw in hay)

    ranked = sorted(internal_links, key=score, reverse=True)
    chosen: list[str] = []
    for link in ranked:
        if score(link) == 0:
            continue  # skip non-keyword pages entirely
        if link["url"] not in chosen:
            chosen.append(link["url"])
        if len(chosen) >= max_pages:
            break
    return chosen
```

- [ ] **Step 12: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_site_fetch.py::test_select_subpages_prioritizes_keywords -v`
Expected: PASS.

- [ ] **Step 13: Commit**

```bash
git add scripts/site_fetch.py tests/test_site_fetch.py
git commit -m "feat(site_fetch): link classification, snapshot parsing, subpage selection"
```

---

## Task 3: site_fetch.py — agent-browser обёртка + fallback + CLI (TDD)

**Files:**
- Modify: `scripts/site_fetch.py`
- Test: `tests/test_site_fetch.py`

- [ ] **Step 1: Падающий тест на fallback-парсинг HTML**

Append to `tests/test_site_fetch.py`:

```python
from scripts.site_fetch import parse_html_fallback


def test_parse_html_fallback_extracts_links_text():
    html = """
    <html><head><title>Acme</title></head>
    <body>
      <h1>Acme builds models</h1>
      <a href="https://github.com/acme">GitHub</a>
      <a href="https://acme.ai/team">Team</a>
      <a href="mailto:hi@acme.ai">Email</a>
    </body></html>
    """
    parsed = parse_html_fallback("https://acme.ai", html)
    assert "Acme builds models" in parsed["text"]
    assert {"type": "github", "url": "https://github.com/acme"} in parsed["external_links"]
    assert "hi@acme.ai" in parsed["emails"]
    assert "https://acme.ai/team" in [l["url"] for l in parsed["internal_links"]]
```

- [ ] **Step 2: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_site_fetch.py::test_parse_html_fallback_extracts_links_text -v`
Expected: FAIL — `ImportError: cannot import name 'parse_html_fallback'`.

- [ ] **Step 3: Реализовать parse_html_fallback**

Append to `scripts/site_fetch.py`:

```python
from bs4 import BeautifulSoup


def parse_html_fallback(page_url: str, html: str) -> dict:
    """Fallback parser using BeautifulSoup, same output shape as parse_snapshot."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = " ".join(soup.get_text(separator=" ").split())

    external_links: list[dict] = []
    internal_links: list[dict] = []
    emails: list[str] = []
    seen_ext: set[str] = set()

    for a in soup.find_all("a", href=True):
        url = a["href"]
        kind = classify_link(url)
        if kind == "email":
            addr = url[len("mailto:"):].split("?")[0]
            if addr and addr not in emails:
                emails.append(addr)
        elif kind is not None:
            if url not in seen_ext:
                external_links.append({"type": kind, "url": url})
                seen_ext.add(url)
        elif url.startswith("http") and _same_host(page_url, url):
            internal_links.append({"url": url, "name": a.get_text(strip=True)})

    return {
        "url": page_url,
        "text": text,
        "external_links": external_links,
        "internal_links": internal_links,
        "emails": emails,
    }
```

- [ ] **Step 4: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_site_fetch.py::test_parse_html_fallback_extracts_links_text -v`
Expected: PASS.

- [ ] **Step 5: Падающий тест на выбор движка (agent-browser доступен / нет)**

Append to `tests/test_site_fetch.py`:

```python
from scripts.site_fetch import resolve_engine


def test_resolve_engine_prefers_agent_browser_when_present(monkeypatch):
    monkeypatch.setattr("scripts.site_fetch.shutil.which",
                        lambda name: "/usr/local/bin/agent-browser")
    assert resolve_engine() == "agent-browser"


def test_resolve_engine_falls_back_when_absent(monkeypatch):
    monkeypatch.setattr("scripts.site_fetch.shutil.which", lambda name: None)
    assert resolve_engine() == "fallback"
```

- [ ] **Step 6: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_site_fetch.py::test_resolve_engine_prefers_agent_browser_when_present tests/test_site_fetch.py::test_resolve_engine_falls_back_when_absent -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_engine'`.

- [ ] **Step 7: Реализовать resolve_engine**

Append to `scripts/site_fetch.py`:

```python
import shutil


def resolve_engine() -> str:
    """Return 'agent-browser' if the CLI is on PATH, else 'fallback'."""
    return "agent-browser" if shutil.which("agent-browser") else "fallback"
```

- [ ] **Step 8: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_site_fetch.py -k resolve_engine -v`
Expected: PASS (2 passed).

- [ ] **Step 9: Падающий тест на reachable=false когда обе схемы мертвы (fallback-путь)**

Append to `tests/test_site_fetch.py`:

```python
from scripts.site_fetch import fetch_site


def test_fetch_site_unreachable_via_fallback(monkeypatch):
    monkeypatch.setattr("scripts.site_fetch.resolve_engine", lambda: "fallback")

    def boom(url, timeout=None):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("scripts.site_fetch._http_get", boom)
    result = fetch_site("dead.example", max_pages=3)
    assert result["reachable"] is False
    assert result["engine"] == "fallback"
    assert result["pages"] == []


def test_fetch_site_reachable_via_fallback(monkeypatch):
    monkeypatch.setattr("scripts.site_fetch.resolve_engine", lambda: "fallback")

    def fake_get(url, timeout=None):
        if url == "https://acme.ai":
            return ("<html><body><h1>Acme</h1>"
                    "<a href='https://github.com/acme'>gh</a>"
                    "<a href='https://acme.ai/about'>About</a></body></html>")
        if url == "https://acme.ai/about":
            return "<html><body><h1>About Acme</h1></body></html>"
        raise RuntimeError("404")

    monkeypatch.setattr("scripts.site_fetch._http_get", fake_get)
    result = fetch_site("acme.ai", max_pages=3)
    assert result["reachable"] is True
    assert result["domain"] == "acme.ai"
    assert any(l["type"] == "github" for l in result["external_links"])
    assert len(result["pages"]) >= 1
```

- [ ] **Step 10: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_site_fetch.py -k fetch_site -v`
Expected: FAIL — `ImportError: cannot import name 'fetch_site'` (и `_http_get`).

- [ ] **Step 11: Реализовать _http_get, agent-browser runner и fetch_site**

Append to `scripts/site_fetch.py`:

```python
import json
import subprocess


def _http_get(url: str, timeout: float | None = 15.0) -> str:
    """Minimal GET for the fallback path. Raises on any failure."""
    import httpx

    resp = httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": "kvetio-site-fetch/1.0"})
    resp.raise_for_status()
    return resp.text


def _agent_browser_snapshot(url: str, domain: str, max_output: int) -> dict:
    """Open URL in agent-browser and return the snapshot data payload.

    Raises subprocess.CalledProcessError / json.JSONDecodeError on failure so
    the caller can fall back.
    """
    allowed = f"{domain},*.{domain}"
    cmd = [
        "agent-browser", "--json", "--allowed-domains", allowed,
        "--max-output", str(max_output),
        "batch", f"open {url}", "wait --load networkidle",
        "snapshot -i --urls",
    ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, check=True)
    # batch returns an array of step results; take the last (snapshot) step.
    payload = json.loads(out.stdout)
    steps = payload if isinstance(payload, list) else [payload]
    snap = steps[-1]
    data = snap.get("data", snap)
    return data


def _fetch_one_agent_browser(url: str, domain: str, max_output: int) -> dict | None:
    try:
        snap = _agent_browser_snapshot(url, domain, max_output)
    except (subprocess.SubprocessError, OSError, ValueError):
        return None
    return parse_snapshot(url, snap)


def _fetch_one_fallback(url: str) -> dict | None:
    try:
        html = _http_get(url)
    except Exception:
        return None
    return parse_html_fallback(url, html)


def fetch_site(domain: str, max_pages: int = 5, max_output: int = 50000) -> dict:
    """Fetch a company site and return compact structured data.

    Output: {domain, engine, reachable, pages, external_links, emails}.
    """
    engine = resolve_engine()

    def fetch_one(url: str) -> dict | None:
        if engine == "agent-browser":
            page = _fetch_one_agent_browser(url, domain, max_output)
            if page is not None:
                return page
        return _fetch_one_fallback(url)

    # Try root with and without www.
    home = None
    for candidate in (f"https://{domain}", f"https://www.{domain}"):
        home = fetch_one(candidate)
        if home is not None:
            break

    if home is None:
        return {"domain": domain, "engine": engine, "reachable": False,
                "pages": [], "external_links": [], "emails": []}

    pages = [{"url": home["url"], "text": home["text"]}]
    external = list(home["external_links"])
    emails = list(home["emails"])
    ext_seen = {l["url"] for l in external}

    for sub_url in select_subpages(home["internal_links"], max_pages=max_pages):
        sub = fetch_one(sub_url)
        if sub is None:
            continue
        pages.append({"url": sub["url"], "text": sub["text"]})
        for link in sub["external_links"]:
            if link["url"] not in ext_seen:
                external.append(link)
                ext_seen.add(link["url"])
        for addr in sub["emails"]:
            if addr not in emails:
                emails.append(addr)

    return {"domain": domain, "engine": engine, "reachable": True,
            "pages": pages, "external_links": external, "emails": emails}
```

- [ ] **Step 12: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_site_fetch.py -k fetch_site -v`
Expected: PASS (2 passed).

- [ ] **Step 13: Добавить CLI main()**

Append to `scripts/site_fetch.py`:

```python
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch a company site as compact JSON")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--max-output", type=int, default=50000)
    parser.add_argument("--json", action="store_true", help="Emit JSON (default)")
    args = parser.parse_args()
    result = fetch_site(args.domain, max_pages=args.max_pages, max_output=args.max_output)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 14: Полный прогон файла тестов + ruff**

Run: `python -m pytest tests/test_site_fetch.py -v && ruff check scripts/site_fetch.py tests/test_site_fetch.py`
Expected: все тесты PASS, ruff без ошибок.

- [ ] **Step 15: Commit**

```bash
git add scripts/site_fetch.py tests/test_site_fetch.py
git commit -m "feat(site_fetch): agent-browser runner, httpx fallback, fetch_site + CLI"
```

---

## Task 4: research_notes_store.py — заметки и категории (TDD)

**Files:**
- Create: `scripts/research_notes_store.py`
- Test: `tests/test_research_notes_store.py`

- [ ] **Step 1: Посмотреть, как тесты мокают SupabaseStore**

Run: `sed -n '1,60p' tests/test_contacts_store.py; sed -n '1,40p' tests/conftest.py`
Цель: переиспользовать существующий паттерн фейкового Supabase-клиента (фикстуры в `tests/conftest.py` / `tests/fixtures`), а не изобретать новый мок.

- [ ] **Step 2: Падающий тест на content_hash**

Create `tests/test_research_notes_store.py`:

```python
from scripts.research_notes_store import content_hash


def test_content_hash_stable_and_distinct():
    a = content_hash("Acme builds medical imaging models.")
    b = content_hash("Acme builds medical imaging models.")
    c = content_hash("Different content.")
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hex
```

- [ ] **Step 3: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_research_notes_store.py::test_content_hash_stable_and_distinct -v`
Expected: FAIL — `ImportError`.

- [ ] **Step 4: Реализовать модуль-заголовок + content_hash**

Create `scripts/research_notes_store.py`:

```python
"""Store research notes and manage the category select for SiteResearchAgent."""
from __future__ import annotations

import hashlib

from scripts.supabase_store import SupabaseStore

VALID_NOTE_TYPES = {"product", "press_release", "cooperative", "finance"}


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
```

- [ ] **Step 5: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_research_notes_store.py::test_content_hash_stable_and_distinct -v`
Expected: PASS.

- [ ] **Step 6: Падающий тест на upsert_note (idempotent по хешу)**

Append to `tests/test_research_notes_store.py`. Use the project's fake store fixture if present; otherwise this minimal stand-in:

```python
class _FakeTable:
    def __init__(self, store, name):
        self.store = store
        self.name = name
        self._filters = {}

    def select(self, *_):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def execute(self):
        rows = [r for r in self.store.data.get(self.name, [])
                if all(r.get(k) == v for k, v in self._filters.items())]
        self._filters = {}
        return type("R", (), {"data": rows})()

    def insert(self, row):
        self._pending = ("insert", row)
        return self

    # insert().execute()
    def _do_insert(self):
        row = dict(self._pending[1])
        row.setdefault("id", f"id{len(self.store.data.get(self.name, []))+1}")
        self.store.data.setdefault(self.name, []).append(row)
        return type("R", (), {"data": [row]})()


class _FakeClient:
    def __init__(self):
        self.data = {}

    def table(self, name):
        t = _FakeTable(self, name)
        # route insert().execute() to _do_insert
        orig_execute = t.execute

        def execute():
            if getattr(t, "_pending", None) and t._pending[0] == "insert":
                t._pending = None
                return t._do_insert() if False else _insert_real()
            return orig_execute()

        def _insert_real():
            return None
        return t


class _FakeStore:
    def __init__(self):
        self._client = _FakeClient()


def test_upsert_note_is_idempotent():
    from scripts.research_notes_store import upsert_note
    store = _FakeStore()
    cid = "company-1"
    first = upsert_note(store, company_id=cid, note_type="product",
                        content="Acme builds models.", source_url="https://acme.ai")
    second = upsert_note(store, company_id=cid, note_type="product",
                         content="Acme builds models.", source_url="https://acme.ai")
    assert first == second  # same row id, no duplicate
    rows = store._client.data["research_notes"]
    assert len(rows) == 1
```

> **Note for implementer:** If `tests/conftest.py` provides a reusable fake Supabase store, DELETE the `_Fake*` classes above and use that fixture instead (DRY). The fake client must support `.table("research_notes").select().eq(...).eq(...).execute()` returning `.data`, and `.insert(row).execute()` returning `.data`.

- [ ] **Step 7: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_research_notes_store.py::test_upsert_note_is_idempotent -v`
Expected: FAIL — `ImportError: cannot import name 'upsert_note'`.

- [ ] **Step 8: Реализовать upsert_note**

Append to `scripts/research_notes_store.py`:

```python
def upsert_note(store: SupabaseStore, *, company_id: str, note_type: str,
                content: str, source_url: str | None = None) -> str:
    """Insert a research note unless an identical one exists. Returns row id.

    Identity = (company_id, note_type, content_hash). Idempotent.
    """
    if note_type not in VALID_NOTE_TYPES:
        raise ValueError(f"invalid note_type: {note_type}")
    h = content_hash(content)
    existing = (
        store._client.table("research_notes")
        .select("id")
        .eq("company_id", company_id)
        .eq("note_type", note_type)
        .eq("content_hash", h)
        .execute()
    )
    if existing.data:
        return existing.data[0]["id"]
    row = {
        "company_id": company_id,
        "note_type": note_type,
        "content": content,
        "content_hash": h,
        "source_url": source_url,
    }
    res = store._client.table("research_notes").insert(row).execute()
    return res.data[0]["id"] if res.data else ""
```

- [ ] **Step 9: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_research_notes_store.py::test_upsert_note_is_idempotent -v`
Expected: PASS.

- [ ] **Step 10: Падающий тест на ensure_category (новая категория → INSERT в справочник)**

Append to `tests/test_research_notes_store.py`:

```python
def test_ensure_category_inserts_when_missing():
    from scripts.research_notes_store import ensure_category
    store = _FakeStore()  # or project fixture
    store._client.data["category_options"] = [
        {"value": "data_provider", "label": "Data provider"}
    ]
    # existing -> no insert
    ensure_category(store, "data_provider")
    assert len(store._client.data["category_options"]) == 1
    # new -> insert
    ensure_category(store, "robotics_lab", label="Robotics lab")
    values = [r["value"] for r in store._client.data["category_options"]]
    assert "robotics_lab" in values
```

- [ ] **Step 11: Запустить — убедиться, что падает**

Run: `python -m pytest tests/test_research_notes_store.py::test_ensure_category_inserts_when_missing -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_category'`.

- [ ] **Step 12: Реализовать ensure_category**

Append to `scripts/research_notes_store.py`:

```python
def ensure_category(store: SupabaseStore, value: str,
                    label: str | None = None) -> None:
    """Ensure a category select-option exists before assigning it to a company."""
    existing = (
        store._client.table("category_options")
        .select("value")
        .eq("value", value)
        .execute()
    )
    if existing.data:
        return
    store._client.table("category_options").insert(
        {"value": value, "label": label or value}
    ).execute()
```

- [ ] **Step 13: Запустить — убедиться, что проходит**

Run: `python -m pytest tests/test_research_notes_store.py -v`
Expected: PASS (все тесты файла).

- [ ] **Step 14: ruff**

Run: `ruff check scripts/research_notes_store.py tests/test_research_notes_store.py`
Expected: без ошибок.

- [ ] **Step 15: Commit**

```bash
git add scripts/research_notes_store.py tests/test_research_notes_store.py
git commit -m "feat(research_notes_store): upsert_note + ensure_category"
```

---

## Task 5: Промпт проверки релевантности

**Files:**
- Create: `agents/prompts/relevance_check_task.md`
- Test: `tests/test_pipeline_prompts.py` (проверить, валидирует ли он промпты)

- [ ] **Step 1: Посмотреть, что проверяет test_pipeline_prompts.py**

Run: `sed -n '1,80p' tests/test_pipeline_prompts.py`
Цель: понять, есть ли реестр/список промптов, который надо пополнить, или тест просто проверяет существование файлов по соглашению. Если есть явный список — добавить новый промпт на шаге 3.

- [ ] **Step 2: Написать промпт**

Create `agents/prompts/relevance_check_task.md`:

```markdown
# Relevance Check (вложенный под-шаг SiteResearchAgent)

## Роль

Ты оцениваешь релевантность ОДНОЙ компании на основе уже собранного контента
сайта (вход — JSON от `scripts/site_fetch.py`). Сам по HTTP не ходишь.

## Вход

JSON: `{domain, reachable, pages:[{url,text}], external_links, emails}`.

## Типы компаний и решение

Релевантна (`relevant=true`), если подходит под один из типов:
- поставщик данных (датасеты/разметка) — `category="data_provider"`;
- разрабатывает продукт — `category="product_builder"`;
- big tech с ИИ-продуктом — `category="big_tech_ai"`;
- не из tech, но строит свой продукт — `category="non_tech_product"`;
- стартап строит свою модель — `category="startup_own_model"`.

Не релевантна (`relevant=false`):
- обёртка для стороннего LLM без своей разработки — `category="llm_wrapper"`;
- закрытый/мёртвый проект — `category="closed_project"`.

## Правила

- Если данных мало или случай спорный — ставь `relevant=true` с
  наиболее подходящей категорией-кандидатом (отсев необратим, не отсеивай зря).
- Если на сайте явно новый, не входящий в список тип — предложи новое значение
  `category` в snake_case и человекочитаемый `category_label`; downstream
  добавит его в справочник `category_options`.
- Релевантность определяется ЭТИМ решением, не наоборот: категория сама по себе
  не диктует статус.

## Выход (строгий JSON)

```json
{"relevant": true, "category": "startup_own_model",
 "category_label": "Startup building own model",
 "reason": "Trains own foundation model; ML hiring; HF org present."}
```
```

- [ ] **Step 3: Прогнать prompt-тест**

Run: `python -m pytest tests/test_pipeline_prompts.py -v`
Expected: PASS. Если упал из-за явного реестра — добавить запись о новом промпте и перезапустить.

- [ ] **Step 4: Commit**

```bash
git add agents/prompts/relevance_check_task.md tests/test_pipeline_prompts.py
git commit -m "feat(prompts): relevance_check sub-step prompt"
```

---

## Task 6: Промпт-оркестратор SiteResearchAgent

**Files:**
- Create: `agents/prompts/site_research_task.md`
- Test: `tests/test_pipeline_prompts.py`

- [ ] **Step 1: Написать промпт**

Create `agents/prompts/site_research_task.md`:

```markdown
# Site Research Task — SiteResearchAgent

## Роль

Оркестратор разбора сайта. Берёшь компании со `status='new'`, для каждой:
скрапишь сайт, проверяешь релевантность (вложенный шаг), и при релевантности
раскладываешь данные по сущностям БД.

**Следующий этап:** нет (терминальный для нового пайплайна; финальный статус
`site_researched` или `not_relevant`).

## Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---:|---|
| `batch_size` | 5 | Компаний за итерацию |
| `max_pages` | 5 | Подстраниц сайта на компанию |

## Шаг 1 — Список

```sql
SELECT id, domain, name, website
FROM companies
WHERE status = 'new'
ORDER BY created_at DESC
LIMIT <batch_size>;
```

## Шаг 2 — Скрап сайта

```bash
python scripts/site_fetch.py --domain <domain> --max-pages <max_pages> --json
```

Получаешь `{reachable, pages, external_links, emails, engine}`.

- Если `reachable=false`: поставь `status='not_relevant'`, причину — в
  `run_logs.notes` (`dead_site:<domain>`). Контент НЕ пиши. Перейди к
  следующей компании.

## Шаг 3 — Релевантность

Передай JSON сайта во вложенный под-шаг `relevance_check_task.md`. Получишь
`{relevant, category, category_label, reason}`.

- Если `relevant=false`: убедись, что категория существует
  (`ensure_category`), поставь `status='not_relevant'`, `category=<category>`.
  НЕ пиши `contacts`/`research_notes`. Перейди к следующей компании.

## Шаг 4 — Извлечение (только релевантные)

Из `pages[].text` и `external_links`/`emails` вытащи и запиши:

**Контакты** — через `scripts/contacts_store.py::upsert_contact(store, dict)`:
- руководители/сотрудники: `{"company_id": <id>, "contact_type": "person",
  "name": <name>, "info": <role>, "linkedin_url": <url?>}`;
- внешние ссылки компании: проставь в поля контакта-компании
  (`linkedin_url`/`x_url`/`facebook_url`/`instagram_url`) или передай в
  `other_channels` (github/huggingface/website) — `upsert_contact` нормализует;
- email компании: `{"company_id": <id>, "contact_type": "email",
  "email": <addr>}`.

**Заметки** — через `scripts/research_notes_store.py::upsert_note(store,
company_id=<id>, note_type=<t>, content=<text>, source_url=<url?>)`:
- продукт (позиционирование, проблема, подходы, суть, функционал, аудитория):
  `note_type="product"`;
- пресс-релизы: `note_type="press_release"`;
- сотрудничество с компаниями: `note_type="cooperative"`;
- инвестиции/гранты/финансирование: `note_type="finance"`.

**Поля компании:**
- год основания → `companies.founded_year` (int, распарси год из текста);
- страна офиса → `companies.country`.

## Шаг 5 — Запись статуса

```sql
UPDATE companies
SET status = 'site_researched',
    category = '<category>',
    founded_year = <year_or_null>,
    country = '<country_or_null>',
    updated_at = NOW()
WHERE id = '<id>';
```

Перед проставлением `category` вызови `ensure_category(store, category,
label=category_label)`.

## Шаг 6 — run_log + уведомление

```sql
INSERT INTO run_logs (task_name, companies_found, companies_enriched, errors, notes)
VALUES ('site_research_task', <checked>, <researched>, '[]',
        'not_relevant: <N>, dead_site: <K>');
```

```bash
python scripts/notify.py --run-summary '{"task":"site_research_task","site_researched":<N>,"not_relevant":<M>}'
```

## Обработка сбоев

- Технический сбой скрапа (engine упал И fallback пуст, но это не «мёртвый
  сайт»): НЕ меняй статус (оставь `new`), запиши ошибку в `run_logs.errors`.
- Частичное извлечение (нет контактов у релевантной компании): это норма —
  пиши что есть, статус `site_researched` всё равно ставь.
```

- [ ] **Step 2: Прогнать prompt-тест**

Run: `python -m pytest tests/test_pipeline_prompts.py -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add agents/prompts/site_research_task.md tests/test_pipeline_prompts.py
git commit -m "feat(prompts): site_research orchestrator prompt"
```

---

## Task 7: Документация и установка agent-browser

**Files:**
- Modify: `README.md`
- Modify: `.env.example`
- Modify: `ARCHITECTURE.md`

- [ ] **Step 1: Заметка об установке agent-browser в README**

Добавить в `README.md` (раздел установки/зависимостей):

```markdown
### agent-browser (опционально, для SiteResearchAgent)

`scripts/site_fetch.py` использует CLI `agent-browser` для токен-эффективного
скрапинга (accessibility-снапшот вместо сырого HTML). Без него скрипт
автоматически откатывается на httpx+BeautifulSoup (`engine: "fallback"`).

Установка:

    npm install -g agent-browser
    agent-browser install   # один раз: скачивает Chrome for Testing
```

- [ ] **Step 2: Переменные в .env.example**

Добавить в `.env.example`:

```bash
# SiteResearchAgent / site_fetch.py
# Макс. символов вывода со страницы (защита от раздувания контекста)
SITE_FETCH_MAX_OUTPUT=50000
# Макс. подстраниц сайта на компанию
SITE_FETCH_MAX_PAGES=5
```

> Implementer note: если решено читать эти env в `site_fetch.py`, добавить
> чтение `os.getenv("SITE_FETCH_MAX_OUTPUT")`/`SITE_FETCH_MAX_PAGES` как
> дефолты для argparse в Task 3 Step 13 и обновить тот код. Иначе оставить
> только CLI-флаги и убрать эти строки. Выбрать один вариант, не оба.

- [ ] **Step 3: Обновить ARCHITECTURE.md**

Обновить `ARCHITECTURE.md` (как требует `CLAUDE.md`):
- Раздел «Агенты»: добавить SiteResearchAgent (цель, вход `status='new'`,
  скрипты `site_fetch.py`/`research_notes_store.py`/`contacts_store.py`, выход
  `site_researched`/`not_relevant`) и вложенный relevance-check.
- Раздел «Схема базы данных»: новые статусы `new`/`site_researched`, столбец
  `companies.category`, таблицы `category_options` и `research_notes`.
- Статусный flow: добавить ветку `new → site_researched | not_relevant`.

- [ ] **Step 4: Финальная верификация всего проекта**

Run: `python -m pytest -q && ruff check scripts/ tests/`
Expected: вся сюита PASS, ruff чисто.

- [ ] **Step 5: Commit**

```bash
git add README.md .env.example ARCHITECTURE.md
git commit -m "docs: site-research agent — install notes, env, ARCHITECTURE update"
```

---

## Self-Review (выполнено автором плана)

**Spec coverage:**
- Оркестратор + вложенная релевантность → Task 5, 6. ✓
- not_relevant → стоп без записи контента → Task 6 Шаг 3. ✓
- Category как select + справочник → Task 1 (category_options), Task 4 (ensure_category). ✓
- Релевантность управляется статусом → промпты Task 5/6. ✓
- Postgres источник истины, Notion витрина (существующий синк не трогаем). ✓
- contacts переиспользуем (upsert_contact) → Task 6. ✓
- founded_year/country переиспользуем → Task 6. ✓
- research_notes + note_type + idempotent upsert → Task 1, 4. ✓
- agent-browser интеграция + fallback → Task 2, 3. ✓
- Обработка ошибок (dead site, тех. сбой, частичное извлечение, новая категория) → Task 6, 4. ✓
- Тестирование (site_fetch, store, статусы, миграция) → Task 1–4. ✓

**Placeholder scan:** в плане остались два явных «implementer note» с ВЫБОРОМ (fake-store fixture в Task 4 Step 6; env vs CLI в Task 7 Step 2) — это сознательные развилки, зависящие от того, что обнаружится в коде на Step 1 соответствующих задач, а не пропуски. Код во всех code-степах полный.

**Type consistency:** `fetch_site`, `parse_snapshot`, `parse_html_fallback`, `classify_link`, `select_subpages`, `resolve_engine`, `_http_get`, `upsert_note`, `ensure_category`, `content_hash` — имена согласованы между определением и использованием в тестах и оркестраторе. `upsert_contact(store, dict)` — реальная сигнатура из contacts_store.py.
