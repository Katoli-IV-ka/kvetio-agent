# Аудит полей БД Kvetio Agent

Дата аудита: 2026-06-17  
Проект Supabase: `Kvetio Project` / `qcfygtxkohopxhsathkv`  
База: Postgres 17.6, схема `public`  
Источник live-схемы: Supabase `_list_tables(verbose=true)` и advisors  
Источник code-flow: `docs/AGENT-ECOSYSTEM.md`, `agents/prompts/*`, `scripts/*`, `config/notion_mapping.yaml`, `sql/*.sql`

Cleanup decision 2026-06-17:
- Score fields are removed.
- companies.sources, latest_signal, reject_reason are removed.
- bot_presets and contact_companies are removed.
- contacts.company_id is canonical; contacts.company_domain remains transitional legacy data.
- Notion CRM reverse fields are removed from the agent database.

## 1. Краткое резюме

Live DB сейчас содержит 9 runtime-таблиц:

| Таблица | Строки | RLS | Роль |
|---|---:|---:|---|
| `companies` | 328 | on | Главная сущность лида и статус-машина pipeline |
| `signals` | 74 | on | Первичные discovery/verification evidence |
| `run_logs` | 9 | on | Легкий журнал этапов и источник `/status`, `/last` |
| `contacts` | 0 | off | Контакты/ЛПР для отдельного контура DM |
| `contact_companies` | 0 | off | Many-to-many связь контактов и компаний |
| `source_links` | 0 | off | URL-источники для глубокого анализа |
| `analysis_notes` | 0 | off | Секционные AI-факты и audit notes |
| `dossiers` | 0 | off | Финальное досье для Notion |
| `bot_presets` | 3 | off | Telegram `/quickrun` и `/presets` |

Критичные выводы:

1. Live DB не полностью совпадает с локальными миграциями и prompt/code expectations.
2. `signals` в live DB не имеет `company_name`, `domain`, `linkedin_url`, `source_page_url`, хотя `scripts/supabase_store.py` и prompts ожидают часть этих полей.
3. `companies` в live DB не имеет `source_page_url`, хотя `discovery_task.md`, `relevance_task.md` и `pipeline_main_task.md` читают/пишут это поле.
4. Advisors показывают live views `public.pipeline_stats` и `public.recent_leads` как `security_definer_view`, хотя локальная миграция `sql/015_drop_unused_db_objects.sql` должна их удалить.
5. RLS выключен на 6 public-таблицах: `contacts`, `source_links`, `analysis_notes`, `dossiers`, `bot_presets`, `contact_companies`. Это риск безопасности, если схема `public` доступна через Supabase Data API.
6. На `companies`, `signals`, `run_logs` RLS включен, но advisors сообщают, что policies отсутствуют. Это может ломать доступ для anon/authenticated ключей или маскироваться service-role ключом.
7. Контуры `contacts`, `source_links`, `analysis_notes`, `dossiers` существуют, но live rows = 0. Основной pipeline еще не дошел до deep stages или записи туда не выполняются.

## 2. Типы Данных По Источнику

### 2.1. Основные данные, на которых строится дальнейшая работа

Это поля, которые стоит считать опорными для pipeline state и маршрутизации:

| Таблица | Поля | Почему основные |
|---|---|---|
| `companies` | `domain`, `name`, `website`, `status`, `icp_segment` | Идентификация компании, дедупликация, выбор этапа |
| `signals` | `normalized_domain`, `source`, `signal_type`, `evidence_url`, `signal_date`, `confidence`, `raw_data` | База evidence для relevance/scoring/enrichment |
| `source_links` | `company_domain`, `kind`, `url`, `confidence` | Источники для analysis |
| `contacts` | `company_domain`, `full_name`, `source_vector`, `source_url`, `confidence` | Контактная база контура DM |
| `contact_companies` | `contact_id`, `company_domain` | Relation для Notion contacts |

### 2.2. Данные, полученные анализом или вычислением

Это не исходная фактура, а результат интерпретации, score, LLM/agent synthesis или ручного решения:

| Таблица | Поля | Кто генерирует |
|---|---|---|
| `companies` | `description`, `website_snippet`, `reject_reason`, `site_note`, `last_verified` | Relevance/Monitor |
| `companies` | `score`, `score_bucket`, `score_version`, `ai_direction` | ScoringAgent + `scripts/score.py` + LLM adjustment |
| `companies` | `latest_signal`, `last_signal_date` | Discovery/Relevance/Monitor summary |
| `analysis_notes` | `facts`, `sources`, `confidence`, `model`, `version` | Analysis section sub-agents |
| `dossiers` | `summary_md`, `sections`, `audit_md`, `table_fields`, `version` | ConclusionAgent |
| `contacts` | `title_normalized`, `dm_priority`, `email_status`, `info` | DM enrichment / contact enricher / agent |

### 2.3. Ручные CRM-данные

| Таблица | Поля | Source of truth |
|---|---|---|
| `companies` | `outreach_status`, `outreach_note` | Notion reverse sync |
| `contacts` | `contact_result` | Notion reverse sync |
| `contacts` | `outreach_status` | Будущий CRM/ручной контур; сейчас не в Notion mapping |

### 2.4. Runtime/system поля

| Таблица | Поля | Назначение |
|---|---|---|
| all | `id`, `created_at`, `updated_at` где есть | Техническая идентификация и аудит изменений |
| `companies`/`contacts`/`dossiers` | `notion_page_id`, `notion_synced_at` | Связка с проекцией Notion |
| `run_logs` | all | Операционный журнал этапов |
| `bot_presets` | all | Конфигурация запуска через Telegram |

## 3. Поток данных

```text
Telegram / Schedule
  -> Claude Code Routine
  -> agents/prompts/pipeline_main_task.md
  -> source adapters: huggingface/github/yc/greenhouse
  -> companies + signals
  -> relevance: company website + HF/jobs/funding/search
  -> companies + signals
  -> scoring: score.py + LLM adjustment
  -> companies.score/*
  -> enrichment.py + WebSearch/MCP
  -> source_links
  -> analysis sub-agents
  -> analysis_notes
  -> conclusion synthesis
  -> dossiers
  -> notion_sync.py
  -> Notion pages + reverse CRM fields
  -> Telegram notify / ops routines
```

## 4. Аудит таблиц

### 4.1. `companies`

Назначение: главный реестр компаний, статус pipeline и бизнес-профиль лида.  
Primary key: `id`; бизнес-ключ unique: `domain`.  
Строки: 328. RLS: включен, но advisors сообщают об отсутствии policies.  
Пишут: Discovery, Relevance, Scoring, Enrichment, Analysis, Conclusions, Notion sync, Contacts marker, Monitor.  
Читают: все stages, scoring, enrichment, Notion sync, Telegram routines.

| Поле | Тип | Источник | Куда идет дальше / использование |
|---|---|---|---|
| `id` | uuid | DB default `gen_random_uuid()` | Технический PK; почти весь код работает по `domain`, не по `id` |
| `domain` | text unique | Discovery/domain normalization | Главный бизнес-ключ; FK target для `signals.normalized_domain`; join key для `dossiers`, `source_links`, `analysis_notes`, `contacts.company_domain`, `contact_companies.company_domain` |
| `name` | text | Discovery source adapters, sometimes verification | Notion `Company name`; Telegram lists; analysis/conclusion context |
| `website` | text nullable live | Discovery domain resolve / Relevance correction | Relevance WebFetch; Notion `Website`; analysis context |
| `linkedin_url` | text | Relevance WebSearch / manual enrichment | Notion `LinkedIn`; company profile context |
| `description` | text | Relevance analysis from website/HF/search | Scoring context, Notion hidden/detail context, conclusions |
| `status` | text default `new` | Переходы между stages | Главный selector очереди для каждого pipeline stage; текущий канонический путь ожидает `discovered -> relevant -> qualified -> sources_gathered -> analyzed -> dossier_ready` |
| `icp_segment` | text | Discovery из run config / `config/icp.yaml` | Coverage, фильтрация stages, Notion `ICP Segment`, scoring context |
| `score` | int | ScoringAgent / `score.py` + LLM adjustment | Ranking for enrichment/analysis/conclusions; Telegram hot leads |
| `score_bucket` | text | ScoringAgent | Gate display `Hot/Warm/Cold`; Telegram hot leads filters `Hot` |
| `score_version` | text | `config/scoring.yaml.version` | Rescore/audit reproducibility |
| `ai_direction` | text | LLM scoring explanation | Notion/reporting context; explains why score was assigned |
| `funding_stage` | text | Relevance WebSearch / funding data | Scoring commercial readiness; analysis/conclusions |
| `funding_amount` | text | Legacy/возможное ручное enrichment | Текущие main prompts активно не пишут это поле; потенциальный funding context |
| `funding_date` | date | Relevance WebSearch | Scoring commercial readiness and recency |
| `team_size` | text | Relevance LinkedIn/site/search | Scoring/context; not currently mapped to Notion |
| `latest_signal` | text | Discovery/Relevance/Monitor summary | Notion `Latest Signal`; Telegram hot leads |
| `last_signal_date` | date | Discovery/Relevance/Monitor | Notion `Signal Date`; freshness checks |
| `last_verified` | date | Relevance/Monitor | Stale review queue and verification audit |
| `notion_page_id` | text | `notion_sync.py` after page create | Forward/reverse sync key; dossier append target; contacts relation builder |
| `created_at` | timestamptz | DB default | Сортировка recent candidates/runs; audit |
| `updated_at` | timestamptz | Stage updates / DB trigger | Operational recency |
| `reject_reason` | text | Relevance quick reject | Audit of `not_relevant` decisions; manual review |
| `site_note` | text | Relevance technical note | Explains Cloudflare/captcha/no-site/manual-review cases |
| `sources` | jsonb default `[]` | Discovery source merge | Relevance context; provenance обнаружения кандидата |
| `website_snippet` | text | Relevance quick filter | Audit evidence for relevance decisions |
| `dm_enriched_at` | timestamptz | `contacts_store.py --mark-enriched` | DM enrichment queue dedupe |
| `outreach_status` | text | Notion reverse sync | Manual CRM state; Notion authoritative |
| `outreach_note` | text | Notion reverse sync | Manual CRM note; Notion authoritative |
| `notion_synced_at` | timestamptz | `notion_sync.py` | Sync freshness marker |

Расхождения:

- В live DB нет `source_page_url`, но prompts читают/пишут его.
- Live default `status='new'` конфликтует с текущим default path основного prompt, который начинается с `discovered`.
- Старый код все еще читает `status='enriched'` в hot leads и DM flow; текущий main pipeline пишет `qualified/sources_gathered/analyzed/dossier_ready`.

### 4.2. `signals`

Назначение: отдельные evidence-события, найденные discovery/relevance/monitor.  
Primary key: `id`; unique: `evidence_url`.  
Строки: 74. RLS: включен, но advisors сообщают об отсутствии policies.  
Пишут: DiscoveryAgent, RelevanceAgent, MonitorAgent, `SupabaseStore.upsert_signal()`.  
Читают: ScoringAgent, Enrichment `GithubOrgResolver`, DM HuggingFace contact flow, analysis.

| Поле | Тип | Источник | Куда идет дальше / использование |
|---|---|---|---|
| `id` | uuid | DB default | Технический PK |
| `normalized_domain` | text | Discovery/Relevance domain normalization | Join к `companies.domain`; выборка для scoring и enrichment |
| `source` | text | Имя source adapter | Source mix, scoring evidence, audit |
| `signal_type` | text | Классификация adapter/stage | Scoring rules, фильтрация analysis |
| `evidence_url` | text unique | Proof URL от adapter/stage | Dedup key; provenance для scoring/enrichment |
| `signal_date` | date | Дата adapter/stage | Freshness scoring и monitoring |
| `confidence` | text default `medium` | Confidence от adapter/stage | Уровень доверия для scoring/audit |
| `parser_version` | text | Версия adapter | Воспроизводимость и аудит parser drift |
| `raw_data` | jsonb default `{}` | Raw payload adapter/stage | Детальный provenance; может содержать поля, отсутствующие как колонки |
| `created_at` | timestamptz | DB default | Audit timestamp |

Расхождения:

- `scripts/supabase_store.py` пишет `company_name` и `domain`, но в live DB таких колонок нет.
- Локальный `sql/001_init.sql` определяет `company_name`, `domain`, `linkedin_url`; в live DB их нет.
- Локальный `sql/004_signals_source_page_url.sql` добавляет `source_page_url`; в live DB его нет.
- `scripts/enrichment.py` пробует `sig.get("source_page_url")`; с live DB он откатывается к `evidence_url`, что все еще может работать для GitHub org URLs, но слабее для Greenhouse/job URLs.

### 4.3. `run_logs`

Назначение: легкий операционный журнал по этапам.  
Строки: 9. RLS: включен, но advisors сообщают об отсутствии policies.  
Пишут: stage prompts и `SupabaseStore.log_run()`.  
Читают: Telegram `/status`, `/last`.

| Поле | Тип | Источник | Куда идет дальше / использование |
|---|---|---|---|
| `id` | uuid | DB default | Технический PK |
| `task_name` | text | Имя stage/pipeline | `/last`, группировка audit |
| `started_at` | timestamptz default now | Время insert или явный start stage | Сортировка и определение active run |
| `finished_at` | timestamptz nullable | Должно задаваться при завершении stage | `/status` считает последнюю строку с `finished_at IS NULL` активной |
| `companies_found` | int default 0 | Stage count | Pipeline metrics |
| `companies_enriched` | int default 0 | Stage count, legacy name | Pipeline metrics; неоднозначно для не-enrichment stages |
| `errors` | jsonb default `[]` | Сбор ошибок stage | Debugging, final summary |
| `notes` | text | Stage summary | Свободные audit notes |

Риск:

- Многие текущие prompts вставляют logs, но не обновляют `finished_at`. Telegram `/status` может показывать устаревшие active runs.
- `companies_enriched` перегружен по смыслу: для discovery он означает записанные discovered-компании, а для других stages менее точен.

### 4.4. `contacts`

Назначение: контакты/ЛПР для DM enrichment.  
Строки: 0. RLS: выключен.  
Пишут: `contacts_store.py --upsert`, `contact_enricher.py`, DM prompts.  
Читают: `notion_sync.py --entity contacts`, `contacts_store.py --list`, contact enricher.

| Поле | Тип | Источник | Куда идет дальше / использование |
|---|---|---|---|
| `id` | uuid | DB default | PK; ключ контакта Notion и `contact_companies.contact_id` |
| `company_domain` | text | Вход DM source | Обратно совместимая основная связь с компанией; список контактов по компании |
| `full_name` | text | DM sources / parser | Dedup вместе с `company_domain`; title в Notion |
| `first_name` | text | Parser split/enrichment | Удобство для outreach |
| `last_name` | text | Parser split/enrichment | Удобство для outreach |
| `title` | text | Raw title из DM source | Audit роли |
| `title_normalized` | text | Contact enrichment / agent normalization | DM priority and targeting |
| `dm_priority` | int default 2 | Agent/heuristic | Сортировка контактов |
| `email` | text | Apollo/GitHub/team/contact page/guesser | Notion `Email`, outreach |
| `email_status` | text default `unknown` | Verifier/heuristic | Уровень доверия для outreach |
| `email_source` | text | Contact source/enricher | Email provenance |
| `linkedin_url` | text | Contact source/search | Notion `LinkedIn` |
| `twitter_handle` | text | Contact source/enricher | Outreach/social context |
| `github_username` | text | GitHub DM source | Enrichment/provenance |
| `source_vector` | text default `github` | Имя DM source | Аналитика качества источников |
| `source_url` | text | Evidence URL | Notion `Источник`, audit |
| `confidence` | text default `medium` | DM source/agent | Уровень доверия к контакту |
| `outreach_status` | text default `not_contacted` | Manual/future CRM | Сейчас не входит в Notion mapping |
| `raw_payload` | jsonb default `{}` | Raw payload источника | Audit и re-enrichment |
| `created_at` | timestamptz | DB default | Audit |
| `updated_at` | timestamptz | Store update/trigger | Audit |
| `personal_website` | text | Contact search extension/enricher | Outreach context |
| `hf_username` | text | HuggingFace contact flow | HF provenance |
| `notion_page_id` | text | `notion_sync.py` after contact page create | Reverse sync key |
| `contact_type` | text default `Person` | DM source/manual | Notion `Тип контакта`; ограничено `Person/Company/Other` |
| `phone` | text | DM source/manual | Notion `Phone` |
| `instagram_url` | text | DM source/manual | Notion `Instagram` |
| `facebook_url` | text | DM source/manual | Notion `Facebook` |
| `info` | text | DM source/agent | Notion `Информация о контакте` |
| `contact_result` | text nullable | Notion reverse sync | Manual outreach result |

Риск:

- RLS выключен.
- Main pipeline не вызывает `dm_enrich_task.md`; таблица пустая.
- `contacts_store.py` делает upsert по `company_domain,full_name`; live schema выглядит совместимой с этим, но case-insensitive dedup зависит от индексов, которые не видны в `_list_tables`.

### 4.5. `contact_companies`

Назначение: many-to-many связь контакта с компаниями.  
Строки: 0. RLS: выключен.  
Primary key: (`contact_id`, `company_domain`).  
FK: `contact_id -> contacts.id`.

| Поле | Тип | Источник | Куда идет дальше / использование |
|---|---|---|---|
| `contact_id` | uuid | `contacts_store.link_contact_to_companies()` | Получение relation для Notion contacts |
| `company_domain` | text | DM contact JSON `company_domains` | Resolves company Notion page ids через `companies.notion_page_id` |

Риск:

- Нет FK на `companies.domain`; в локальном SQL связь намеренно мягкая.
- RLS выключен.
- Остается пустой, если DM flow не передает `company_domains`.

### 4.6. `source_links`

Назначение: источники для глубокого анализа. Это URL для последующей проверки, а не интерпретированные факты.  
Строки: 0. RLS: выключен.  
Пишут: `scripts/enrichment.py`, `dossier_store.py --upsert-source-link`, EnrichmentAgent.  
Читают: AnalysisAgent и section sub-agents.

| Поле | Тип | Источник | Куда идет дальше / использование |
|---|---|---|---|
| `id` | uuid | DB default | Технический PK |
| `company_domain` | text | Enrichment input | Выбор source links по компании |
| `kind` | text | Resolver/agent classification | Направляет analysis: `github_org`, `wayback`, `hf_org`, `news_feed` и т. д. |
| `url` | text | Resolver/WebSearch/MCP | Входные данные WebFetch/MCP для analysis |
| `source` | text default `unknown` | Имя resolver | Provenance |
| `confidence` | text default `medium` | Resolver/agent | Уровень доверия |
| `found_via` | text | Опциональная заметка о происхождении | Audit |
| `raw` | jsonb default `{}` | Raw metadata resolver | Reprocessing/audit |
| `fetched_at` | timestamptz default now | Время записи store | Свежесть/порядок |

Риск:

- RLS выключен.
- Пустая таблица означает, что у deep analysis пока нет устойчиво сохраненных источников.

### 4.7. `analysis_notes`

Назначение: промежуточные структурированные факты по секциям досье.  
Строки: 0. RLS: выключен.  
Пишут: analysis section sub-agents и audit sub-agent через `dossier_store.py --upsert-analysis-note`.  
Читают: ConclusionAgent, dossier sync context.

| Поле | Тип | Источник | Куда идет дальше / использование |
|---|---|---|---|
| `id` | uuid | DB default | Технический PK |
| `company_domain` | text | Analysis input | Выбор notes для conclusion |
| `section` | text | Секция analysis sub-agent | Ограничено значениями `company/product/collaboration/financials/news/audit` |
| `facts` | jsonb default `{}` | AI analysis из source links/WebFetch/search | Основной структурированный payload анализа для conclusion |
| `sources` | jsonb default `[]` | Supporting URLs, выбранные AI | Provenance для claims |
| `confidence` | text default `medium` | Section agent | Маркер качества для conclusion/audit |
| `model` | text | Метка agent/model | Воспроизводимость |
| `version` | text default `v1` | Версия prompt/output | Ключ upsert/versioning |
| `created_at` | timestamptz default now | Время записи store | Audit |

Риск:

- RLS выключен.
- Таблица пустая; нет live-доказательств, что analysis stage уже сохранял notes.

### 4.8. `dossiers`

Назначение: финальное досье компании, собранное из `analysis_notes`.  
Строки: 0. RLS: выключен.  
Primary key: `company_domain`.  
Пишет: ConclusionAgent через `dossier_store.py --upsert-dossier`.  
Читает: `notion_sync.py --entity dossiers`.

| Поле | Тип | Источник | Куда идет дальше / использование |
|---|---|---|---|
| `company_domain` | text PK | Conclusion input | Join к `companies.domain`; одно досье на компанию |
| `summary_md` | text | Синтез ConclusionAgent | Добавляется на страницу компании в Notion |
| `sections` | jsonb default `{}` | ConclusionAgent из analysis notes | Структурированные финальные секции |
| `audit_md` | text | ConclusionAgent/audit note | Добавляется на страницу компании в Notion |
| `table_fields` | jsonb default `{}` | Временные структурированные поля ConclusionAgent | Будущие поля таблицы/проекции |
| `version` | text default `v1` | Версия вывода досье | Воспроизводимость |
| `generated_at` | timestamptz default now | Время записи store | Свежесть |
| `notion_page_id` | text | Есть в схеме, но текущий `upsert_dossier()` не пишет это поле | В основном не используется; текущая синхронизация добавляет досье в `companies.notion_page_id` |

Риск:

- RLS выключен.
- `notion_page_id` является багажом схемы, если будущий дизайн не будет создавать отдельные страницы досье.
- Таблица пустая; conclusions пока не сохраняются или еще не запускались.

### 4.9. `bot_presets`

Назначение: сохраненные конфигурации запусков из Telegram.  
Строки: 3. RLS: выключен.  
Пишут: `bot/presets.py`, `/presets save`, seed presets.  
Читают: `/quickrun`, `/presets`, bot UI.

| Поле | Тип | Источник | Куда идет дальше / использование |
|---|---|---|---|
| `id` | uuid | DB default | Технический PK |
| `name` | text unique | User/seed | `/quickrun [preset]`, preset CRUD |
| `config` | jsonb | Bot wizard/user/seed | Преобразуется в текст Routine `/fire` через `bot/routine.py` |
| `owner` | text | Telegram user/chat context | Audit/display |
| `is_default` | bool default false | User/seed | Default preset для `/quickrun` |
| `created_at` | timestamptz default now | DB default | Audit |

Риск:

- RLS выключен. Если роли Data API могут обращаться к этой таблице, любой с опубликованным ключом сможет читать/изменять run configs.

## 5. Live-объекты вне списка таблиц

Supabase advisors сообщают:

| Объект | Вывод | Интерпретация |
|---|---|---|
| view `public.pipeline_stats` | `security_definer_view` ERROR | В live DB все еще есть старое dashboard view или миграция не применена |
| view `public.recent_leads` | `security_definer_view` ERROR | То же самое |
| function `public.update_updated_at` | mutable `search_path` WARN | Если функция остается, ей нужно задать стабильный `search_path` |

Локальная миграция `sql/015_drop_unused_db_objects.sql` удаляет `pipeline_stats`, `recent_leads`, `github_org_cache`. Результат live advisor указывает, что миграция не была применена к подключенному проекту или views были созданы заново.

## 6. Матрица расхождений code/prompt

| Расхождение | Подтверждение | Влияние |
|---|---|---|
| Ожидается `companies.source_page_url`, но в live его нет | `discovery_task.md`, `relevance_task.md`, `pipeline_main_task.md`, локальный `sql/003_source_page_url.sql` | SQL write/read могут падать или выборка вернет missing column |
| Ожидаются `signals.company_name/domain/source_page_url`, но в live их нет | `SupabaseStore.upsert_signal()`, `discovery_task.md`, `sql/001_init.sql`, `sql/004_signals_source_page_url.sql` | Insert сигналов discovery/relevance через store может падать |
| Старый статус `enriched` все еще используется | `SupabaseStore.list_hot_leads()`, `dm_enrich_task.md`, docs drift section | Telegram `/hot` и DM queue могут пропускать текущие лиды `qualified/dossier_ready` |
| `run_logs.finished_at` часто не задается | prompts только вставляют записи; бот читает null как active | `/status` может показывать ложный active run |
| `contacts/source_links/analysis_notes/dossiers` пустые | live row counts 0 | Deep stages/DM не запускались или падают до persistence |
| `pipeline_stats/recent_leads` есть в live, несмотря на локальную drop migration | advisors | Security finding и расхождение схемы |
| RLS неконсистентен | advisors | Доступ может быть слишком открытым на одних таблицах и слишком закрытым на других в зависимости от key/policy |

## 7. Рекомендуемый порядок очистки

1. Определить каноническую live-схему для `companies.source_page_url` и identity columns в `signals`.
   - Либо добавить недостающие колонки в live и оставить prompts/code как есть.
   - Либо убрать ожидания колонок и хранить опциональную идентификацию источника внутри `raw_data`.
2. Нормализовать словарь статусов.
   - Текущий основной путь: `discovered`, `relevant`, `qualified`, `sources_gathered`, `analyzed`, `dossier_ready`.
   - Обновить `list_hot_leads()` и `dm_enrich_task.md`, убрав зависимость от `enriched`, если этот статус выведен из использования.
3. Исправить lifecycle `run_logs`.
   - Либо сделать так, чтобы каждый stage обновлял `finished_at`, либо заменить active-run semantics полноценной таблицей run/session.
4. Применить/удалить устаревшие DB objects.
   - Проверить и удалить `pipeline_stats` и `recent_leads` в live DB, если они больше не нужны.
5. Спроектировать модель RLS/policy перед слепым включением.
   - `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` без policies может сломать API-доступ.
   - Оставить service-role-only writes на серверной стороне; при необходимости открыть только нужные read endpoints.
6. Решить, нужен ли `dossiers.notion_page_id`.
   - Если dossiers только добавляются в страницы компаний, удалить/игнорировать это поле.
7. Рассматривать пустые deep tables как health checks этапов.
   - Запустить контролируемый сегмент pipeline и проверить появление строк в `source_links`, `analysis_notes`, `dossiers`.

## 8. Security findings от Supabase Advisors

Безопасность:

- `RLS Enabled No Policy`: `companies`, `run_logs`, `signals`.
- `RLS Disabled in Public`: `contacts`, `source_links`, `analysis_notes`, `dossiers`, `bot_presets`, `contact_companies`.
- `Security Definer View`: `pipeline_stats`, `recent_leads`.
- `Function Search Path Mutable`: `update_updated_at`.

Производительность:

- Сообщается о нескольких unused indexes на `signals`, `run_logs`, `companies`, `contacts`, `source_links`, `analysis_notes`, `contact_companies`.
- Так как большинство deep tables пустые, unused-index findings пока сами по себе не actionable. Вернуться к ним после появления реального pipeline traffic.

Документация Supabase по исправлениям:

- RLS: https://supabase.com/docs/guides/database/postgres/row-level-security
- Database lints: https://supabase.com/docs/guides/database/database-linter
