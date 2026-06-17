# Kvetio Agent Ecosystem

Информационный документ по архитектуре, запуску и хронологии работы агента.

Дата составления: 2026-06-16.  
Назначение: дать целостную карту проекта `kvetio-agent`: кто запускает агента, какой промпт его оркестрирует, какие инструменты используются на каждом этапе, откуда берутся данные, как они обрабатываются и куда записываются.

Этот документ не является планом миграции и не меняет поведение системы. Он описывает текущую целевую архитектуру репозитория и отмечает места, где в коде остались старые или дополнительные контуры.

## 1. Краткая картина системы

`kvetio-agent` - это pipeline лидогенерации для Kvetio. Агент ищет компании, которые потенциально покупают датасеты и услуги разметки данных для обучения AI/ML-моделей. Он собирает сигналы из внешних источников, проверяет релевантность компаний, скорит их, собирает источники для глубокого анализа, строит досье и синхронизирует результат в Notion.

Главная идея архитектуры:

- Claude Code Routine в облаке Anthropic является runtime, который запускает агентный цикл.
- Главный оркестратор - промпт `agents/prompts/pipeline_task.md`.
- Python-скрипты в `scripts/` - детерминированные инструменты, которые агент вызывает через shell.
- Supabase - источник истины для runtime-данных.
- Notion - пользовательская витрина и место ручных CRM-полей.
- Telegram-бот - только триггер запуска и интерфейс для статуса/дайджестов.

Высокоуровневый поток:

```text
Telegram / Schedule
  -> Claude Code Routine /fire or scheduled run
  -> PipelineAgent from agents/prompts/pipeline_task.md
  -> Stage prompts in agents/prompts/
  -> Python CLI tools in scripts/
  -> Supabase tables
  -> Notion sync
  -> Telegram notification
  -> stop
```

Важно: в новой целевой схеме нет локального worker, очереди `pipeline_runs` и запуска `claude -p` по Anthropic API. Бот не выполняет pipeline сам. Он только вызывает routine.

## 2. Источники истины в репозитории

Основные файлы, через которые надо понимать систему:

| Слой | Файлы | Роль |
|---|---|---|
| Главный README | `README.md` | Общее описание целевой архитектуры, запуска, секретов и команд |
| Runbook миграции | `docs/RUNBOOK.md` | Объясняет переход от старого worker/queue к Claude Code Routines |
| Главный промпт | `agents/prompts/pipeline_task.md` | Последовательность полного pipeline |
| Промпты этапов | `agents/prompts/*.md` | Инструкции для агентов и под-агентов |
| Конфиги | `config/icp.yaml`, `config/sources.yaml`, `config/scoring.yaml`, `config/notion_mapping.yaml` | ICP, registry источников, scoring, маппинг Notion |
| Скрипты | `scripts/*.py` | Детерминированные CLI-инструменты |
| Telegram-бот | `bot/*.py` | FastAPI webhook, wizard, presets, client routine `/fire` |
| БД | `sql/*.sql` | Supabase schema и миграции |
| Аудит БД | `docs/DB-FIELD-AUDIT-2026-06-16.md` | Живое состояние Supabase и drift относительно локальных миграций |

## 3. Базовые сущности и контуры ответственности

### 3.1. Claude Code Routine

Routine - это внешний runtime в Anthropic. В нем задаются:

- prompt: содержимое `agents/prompts/pipeline_task.md`;
- repository: `kvetio-agent`;
- setup script: `pip install -r requirements.txt`;
- environment variables: Supabase, Notion, Telegram, GitHub, HuggingFace;
- network access: доступ к Supabase, Notion, Telegram и внешним источникам;
- triggers: schedule и API `/fire`.

Routine запускает агентный цикл: читает prompt, вызывает shell-команды, делает WebSearch/WebFetch/MCP-вызовы, записывает данные и в конце вызывает уведомление.

### 3.2. PipelineAgent

`PipelineAgent` - роль, заданная в `agents/prompts/pipeline_task.md`. Это не Python-класс. Это инструкция для Claude Code Routine.

Он отвечает за:

- чтение параметров запуска;
- выбор ICP-сегментов;
- последовательный запуск этапов;
- обработку ошибок на уровне сегмента или компании;
- запуск Notion sync;
- финальное уведомление.

Главная цепочка:

```text
discovery
  -> relevance
  -> scoring
  -> enrichment
  -> analysis
  -> conclusions
  -> notion_sync
  -> notify
```

### 3.3. Stage agents

Каждый stage prompt описывает роль отдельного агента:

| Агент | Prompt | Основная задача |
|---|---|---|
| `DiscoveryAgent` | `agents/prompts/discovery_task.md` | Найти компании-кандидаты, резолвить домены, записать `discovered` |
| `RelevanceAgent` | `agents/prompts/relevance_task.md` | Проверить сайт и факты, записать `relevant/not_relevant/manual_review` |
| `ScoringAgent` | `agents/prompts/scoring_task.md` | Посчитать score и принять triage-решение |
| `EnrichmentAgent` | `agents/prompts/enrichment_task.md` | Собрать ссылки-источники в `source_links` |
| `AnalysisAgent` | `agents/prompts/analysis_task.md` | Запустить секционных под-агентов и аудит |
| Section sub-agents | `agents/prompts/analysis_section_task.md` | Собрать факты по одной секции досье |
| Audit sub-agent | `agents/prompts/analysis_audit_task.md` | Синтезировать критическую оценку |
| `ConclusionAgent` | `agents/prompts/conclusions_task.md` | Собрать финальное досье, синкнуть Notion, поставить `dossier_ready` |
| `MonitorAgent` | `agents/prompts/monitor_task.md` | Отдельный мониторинг новых сигналов, не вызывается главным pipeline |
| `DMEnrichAgent` | `agents/prompts/dm_enrich_task.md` | Отдельный поиск ЛПР, сейчас не вызывается главным pipeline |

### 3.4. Python tools

Python scripts - это инструменты, которые агент вызывает через shell. Их можно разделить на группы:

| Группа | Скрипты | Назначение |
|---|---|---|
| Источники discovery | `huggingface.py`, `github.py`, `yc_browser.py`, `greenhouse.py`, `lever.py` | Возвращают JSON-сигналы кандидатов |
| Ядро и утилиты | `models.py`, `normalize.py`, `http_client.py` | Типы, нормализация, HTTP retry/rate-limit |
| Supabase | `supabase_store.py` | CRUD, coverage, stats, run logs |
| Scoring | `score.py` | Pure scoring engine без side effects |
| Deep dossier | `enrichment.py`, `dossier_store.py` | `source_links`, `analysis_notes`, `dossiers` |
| Notion | `notion_sync.py` | Supabase <-> Notion sync |
| Telegram | `notify.py`, `telegram_routines.py` | Уведомления и operational routines |
| Contacts/DM | `dm_*.py`, `contacts_store.py`, `contact_enricher.py` | Поиск и обогащение контактов |

## 4. Инфраструктура запуска

### 4.1. Supabase

Supabase хранит:

- компании и их pipeline status;
- первичные сигналы;
- историю запусков;
- ссылки-источники для досье;
- заметки анализа;
- финальные досье;
- контакты и связи contact-company;
- пресеты Telegram-бота.

Минимальные переменные окружения:

```text
SUPABASE_URL
SUPABASE_KEY
```

Их используют:

- Claude Code Routine, потому что pipeline пишет данные;
- Railway Telegram bot, потому что бот читает `run_logs`, presets, stats и operational lists.

### 4.2. Notion

Notion является витриной. Прямой Notion MCP в основном pipeline не используется. Синхронизация вынесена в `scripts/notion_sync.py`.

Переменные:

```text
NOTION_TOKEN
NOTION_COMPANIES_DB_ID
NOTION_CONTACTS_DB_ID
```

Маппинг:

- `config/notion_mapping.yaml` описывает, какие поля идут из БД в Notion (`forward`);
- какие поля возвращаются из Notion в БД (`reverse`);
- какие таблицы БД и ключи используются.

Для companies:

- forward: `name`, `icp_segment`, `last_signal_date`, `latest_signal`, `linkedin_url`, `website`;
- reverse: `outreach_status`, `outreach_note`.

Для contacts:

- forward: `full_name`, `contact_type`, `email`, `phone`, social URLs, `source_url`, `info`, relation to companies;
- reverse: `contact_result`.

### 4.3. Telegram bot

Telegram bot lives in `bot/` and runs as FastAPI on Railway.

Запуск сервиса:

```bash
uvicorn bot.gateway:app --host 0.0.0.0 --port $PORT
```

Файл Railway:

```text
railway.toml
```

Основные переменные:

```text
TELEGRAM_BOT_TOKEN
TELEGRAM_WEBHOOK_SECRET
BOT_WEBHOOK_URL
ROUTINE_FIRE_URL
ROUTINE_TOKEN
SUPABASE_URL
SUPABASE_KEY
```

Команды:

| Команда | Что делает |
|---|---|
| `/run` | Открывает stateless wizard, собирает RunConfig и вызывает routine `/fire` |
| `/quickrun [preset]` | Берет default или named preset из `bot_presets`, вызывает routine `/fire` |
| `/presets` | CRUD пресетов в Supabase |
| `/status` | Читает незавершенный `run_logs.finished_at IS NULL` |
| `/last [n]` | Читает последние `run_logs` |
| `/digest` | Строит daily digest из Supabase stats |
| `/hot` | Показывает hot leads из Supabase |
| `/stale` | Показывает stale review queue |
| `/ping`, `/help`, `/whoami` | Служебные команды |

Бот не выполняет discovery, scoring, enrichment или analysis. Он не имеет callback от routine о завершении. Финальное уведомление отправляет сама routine через `scripts/notify.py`.

### 4.4. Claude Code Routine `/fire`

`bot/routine.py` содержит тонкий client:

```text
config_to_text(RunConfig) -> "segments=...; limit=...; stages=...; dry_run=...; notion_sync=..."
fire(text) -> POST ROUTINE_FIRE_URL
```

HTTP headers:

```text
Authorization: Bearer <ROUTINE_TOKEN>
anthropic-beta: experimental-cc-routine-2026-04-01
anthropic-version: 2023-06-01
Content-Type: application/json
```

Routine получает JSON:

```json
{"text": "segments=medical-imaging,robotics-ai; limit=30; stages=full; dry_run=false; notion_sync=true"}
```

Если `ROUTINE_FIRE_URL` или `ROUTINE_TOKEN` не заданы, `fire()` возвращает dev-mode ответ и не делает реальный запуск.

## 5. Хронология полного запуска

### 5.1. До запуска: подготовка окружения

Перед тем как pipeline может работать, должны быть настроены:

1. Supabase schema из `sql/*.sql`.
2. Claude Code Routine с prompt `pipeline_task.md`.
3. Секреты routine:
   - `SUPABASE_URL`, `SUPABASE_KEY`;
   - `NOTION_TOKEN`, `NOTION_COMPANIES_DB_ID`, `NOTION_CONTACTS_DB_ID`;
   - `GITHUB_TOKEN`, `HF_TOKEN`;
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
4. Секреты Railway bot:
   - `SUPABASE_URL`, `SUPABASE_KEY`;
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `BOT_WEBHOOK_URL`;
   - `ROUTINE_FIRE_URL`, `ROUTINE_TOKEN`.
5. Telegram webhook через:

```bash
python -m bot.set_webhook
```

6. Network egress allowlist для:
   - Supabase project host;
   - Telegram API;
   - Notion API;
   - HuggingFace;
   - GitHub API;
   - YC public API;
   - Greenhouse;
   - Wayback.

Если network egress закрыт, discovery и записи в Supabase/Telegram уведомления падают. Пример такого partial failure описан в `reports/pipeline_run_2026-06-14.md`.

### 5.2. Триггер запуска

Есть два основных триггера.

#### Schedule

Schedule настраивается в claude.ai/code. В этом случае routine запускается без Telegram-команды. Если `text` пустой, `PipelineAgent` берет все сегменты из `config/icp.yaml`.

#### Manual Telegram trigger

Пользователь пишет `/run` или `/quickrun`.

`/run`:

1. `bot/gateway.py` принимает Telegram webhook.
2. `bot/dialog.py` строит inline wizard.
3. Состояние wizard кодируется в `callback_data`, отдельная таблица состояния не нужна.
4. На подтверждении создается `RunConfig`.
5. `RunConfig.validate()` проверяет сегменты, лимит, stages.
6. `bot/routine.py` сериализует config в text.
7. `fire(text)` POST-ит в routine `/fire`.
8. Telegram получает session id.

`/quickrun`:

1. `bot/presets.py` читает default или named preset из `bot_presets`.
2. Если presets пустые, `ensure_seed_presets()` создает seed presets.
3. Preset превращается в `RunConfig`.
4. Далее путь такой же: `config_to_text()` -> `fire()`.

Записи в БД на этом шаге:

| Компонент | Таблица | Поля |
|---|---|---|
| `bot/presets.py` | `bot_presets` | `name`, `config`, `owner`, `is_default`, `created_at` |
| `/status`, `/last` | `run_logs` | Только чтение: `task_name`, `started_at`, `finished_at` |

`pipeline_runs` в целевой схеме не используется и удаляется миграцией.

### 5.3. Routine стартует

Claude Code Routine:

1. Клонирует репозиторий.
2. Выполняет setup script `pip install -r requirements.txt`.
3. Загружает prompt `agents/prompts/pipeline_task.md`.
4. Получает `text` из trigger.
5. Начинает выполнять роль `PipelineAgent`.

С этого момента orchestration происходит не в Python-коде, а в модели, которая читает промпты этапов и вызывает инструменты.

## 6. Stage 0: параметры запуска и покрытие

### 6.1. Параметры

`pipeline_task.md` ожидает формат:

```text
segments=seg1,seg2; limit=30; stages=full; dry_run=false; notion_sync=true
```

Значения по умолчанию:

| Параметр | Default |
|---|---|
| `segments` | все из `config/icp.yaml` |
| `limit` | `30` |
| `stages` | `full` |
| `dry_run` | `false` |
| `notion_sync` | `true` |

Важно: `bot/config.py` и `bot/dialog.py` поддерживают выбор subset stages, dry-run и notion flag, но `pipeline_task.md` сейчас почти не содержит реальной логики ветвления по этим параметрам. Практически full prompt описывает полный pipeline.

### 6.2. Чтение ICP

Если `segments` не переданы, агент читает:

```bash
cat config/icp.yaml
```

Активные сегменты:

- `medical-imaging`;
- `autonomous-vehicles`;
- `speech-and-audio`;
- `generative-ai`;
- `agriculture-ai`;
- `robotics-ai`;
- `video-photo-ai`.

`config/icp.yaml` задает:

- описание сегмента;
- industries;
- strong/weak keywords;
- funding stages;
- min team size;
- geographies.

### 6.3. Coverage до старта

Команда:

```bash
python scripts/supabase_store.py --coverage
```

Инструмент:

- `scripts/supabase_store.py`;
- класс `SupabaseStore`;
- метод `coverage_by_segment()`.

Источник данных:

- Supabase table `companies`.

Читаемые поля:

- `icp_segment`;
- `status`.

Вывод:

```json
{
  "medical-imaging": {
    "discovered": 10,
    "qualified": 2
  }
}
```

Записей в БД на этом шаге нет.

## 7. Stage 1: DiscoveryAgent

### 7.1. Цель этапа

`DiscoveryAgent` ищет компании-кандидаты из enabled-источников, приводит их к общему формату, резолвит домен/сайт, дедуплицирует и записывает новые компании в Supabase со статусом `discovered`.

Он не анализирует релевантность сайта и не принимает решение о fit. Это оставлено `RelevanceAgent`.

### 7.2. Входы

| Вход | Откуда |
|---|---|
| `segment` | из routine text или `config/icp.yaml` |
| `limit` | из routine text, default `30` |
| source registry | `config/sources.yaml` |
| known ATS slugs | `data/known_ats_slugs.csv` |
| existing companies | Supabase `companies` |

### 7.3. Выбор источников

Агент открывает `config/sources.yaml` и выбирает источники, где:

- `enabled: true`;
- `supported_segments` содержит текущий segment, либо поле отсутствует.

Discovery prompt задает порядок:

```text
huggingface -> github -> yc_browser -> greenhouse
```

Фактически в registry:

| Источник | Enabled | Скрипт | Комментарий |
|---|---:|---|---|
| `huggingface` | yes | `scripts/huggingface.py` | HF organizations по pipeline tags |
| `github` | yes | `scripts/github.py` | GitHub Code Search по `train.py` + ICP keywords |
| `yc_browser` | yes | `scripts/yc_browser.py` | Public YC catalog через `yc-oss` |
| `greenhouse` | yes | `scripts/greenhouse.py` | Job postings по ручному CSV slug-list |
| `lever` | no | `scripts/lever.py` | Stub |
| `ashby` | no | none | Stub |
| `papers_with_code` | no | none | Future |

### 7.4. HuggingFace source adapter

Команда:

```bash
python scripts/huggingface.py --segment <segment> --max-models 1000
```

Источник:

- `https://huggingface.co/api/models`;
- `https://huggingface.co/api/organizations/{org}/overview`;
- optional `HF_TOKEN`.

Механика:

1. Segment превращается в список HuggingFace `pipeline_tags`.
2. Для каждого tag скрипт берет модели организаций.
3. Из моделей извлекаются org authors.
4. Org names дедуплицируются.
5. Для каждой org загружается overview.
6. Системные HF orgs пропускаются.
7. Возвращается JSON candidate signal.

Выходные поля:

- `company_name`;
- `domain` или `null`;
- `evidence_url`;
- `signal_date`;
- `pipeline_tags`;
- `num_models`;
- `num_members`.

Запись в БД сам скрипт не делает. Запись делает агент на основе stdout.

### 7.5. GitHub source adapter

Команда:

```bash
python scripts/github.py --segment <segment> --limit <limit> --dry-run
```

Источники:

- GitHub Code Search API: `https://api.github.com/search/code`;
- GitHub Org API: `https://api.github.com/orgs/{org}`;
- optional `GITHUB_TOKEN`;
- optional Anthropic fallback внутри скрипта для domain inference, если `ANTHROPIC_API_KEY` есть в окружении.

Механика:

1. Скрипт читает `config/icp.yaml`.
2. Для каждого strong keyword ищет `filename:train.py "<keyword>" language:Python`.
3. Берет только owner type `Organization`.
4. Фильтрует активность по `pushed_at`, default last 90 days.
5. Загружает org metadata.
6. Пытается извлечь домен из `blog`, затем из email domain.
7. Если домен не найден, пытается LLM fallback.
8. Возвращает JSON signals.

Выходные поля:

- `source=github`;
- `signal_type=github_repo`;
- `company_name`;
- `domain`;
- `evidence_url=https://github.com/{org}`;
- `signal_date`;
- `confidence`;
- `raw_payload`;
- `parser_version`;
- `source_page_url`.

Запись в БД сам скрипт не делает.

### 7.6. YC Browser source adapter

Команда:

```bash
python scripts/yc_browser.py --segment <segment> --limit <limit>
```

Источник:

- `https://yc-oss.github.io/api/companies/all.json`;
- публичный YC company catalog mirror;
- локальный cache: `data/yc_companies_cache.json`.

Механика:

1. Загружает весь каталог YC.
2. Использует cache с TTL 24h.
3. Segment превращается в YC tags plus AI/ML base tags.
4. Фильтрует active companies по пересечению tags.
5. Нормализует website в domain.
6. Конвертирует каждую компанию в signal JSON.

Выходные поля:

- `company_name`;
- `domain`;
- `website`;
- `description`;
- `source=yc_browser`;
- `signal_type=yc_company`;
- `batch`;
- `tags`;
- `team_size`;
- `evidence_url=https://www.ycombinator.com/companies/{slug}`;
- `signal_date`;
- `confidence`;
- `raw_data`.

Запись в БД сам скрипт не делает.

### 7.7. Greenhouse source adapter

Команда:

```bash
python scripts/greenhouse.py --segment <segment>
```

Источники:

- `data/known_ats_slugs.csv`;
- Greenhouse Job Board API: `https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true`.

Механика:

1. Читает CSV slug-list.
2. Берет только строки `ats=greenhouse`.
3. Для каждого board slug загружает jobs.
4. Чистит HTML content вакансии.
5. Ищет data/ML keywords:
   - `training data`;
   - `data annotation`;
   - `data labeling`;
   - `rlhf`;
   - `dataset`;
   - `fine-tuning`;
   - `ml engineer`;
   - другие.
6. Проверяет segment keywords.
7. Фильтрует freshness: default last 180 days.
8. Нормализует domain из CSV website, если он есть.
9. Возвращает JSON signal.

Выходные поля:

- `source=greenhouse`;
- `signal_type=job_posting`;
- `company_name`;
- `domain`;
- `evidence_url`;
- `signal_date`;
- `confidence=high`;
- `raw_payload` with slug, job id, title, snippet, location, website from CSV;
- `parser_version`.

Запись в БД сам скрипт не делает.

### 7.8. Дедупликация и резолв домена

После выполнения источников агент объединяет результаты.

Дедуп:

1. Внутри текущей сессии по normalized domain.
2. Против Supabase:

```sql
SELECT domain, status
FROM companies
WHERE domain = '<normalized_domain>';
```

Если запись уже есть, компания пропускается. Если одна компания пришла из нескольких источников, `sources` объединяется в JSON-массив.

Резолв домена:

| Источник | Надежность домена | Что делает агент |
|---|---|---|
| `yc_browser` | обычно есть | использует напрямую |
| `huggingface` | часто `null` | WebSearch official website |
| `github` | иногда есть | WebSearch, если `null` |
| `greenhouse` | зависит от CSV | WebSearch, если пусто |

Fallback:

```text
WebSearch: "<company name>" official website
```

Если домен не найден, компания не записывается.

### 7.9. Запись Discovery в БД

`DiscoveryAgent` пишет через SQL/Supabase tool или через Supabase access, описанный в prompt.

Таблица `companies`:

| Поле | Значение |
|---|---|
| `domain` | normalized domain, unique key |
| `name` | company name |
| `website` | `https://<domain>` или найденный website |
| `status` | `discovered` |
| `icp_segment` | текущий segment |
| `sources` | JSON array источников |
| `source_page_url` | URL первичного источника, если колонка есть |
| `updated_at` | `NOW()` |

Таблица `signals`:

| Поле | Значение |
|---|---|
| `source` | `huggingface`, `github`, `yc_browser`, `greenhouse` |
| `signal_type` | `hf_org`, `github_repo`, `job_posting`, `yc_company` |
| `company_name` | company name, если колонка есть |
| `normalized_domain` | company domain |
| `evidence_url` | proof URL, unique |
| `signal_date` | дата сигнала |
| `confidence` | `high/medium/low` |
| `raw_data` | raw payload from source |

Таблица `run_logs`:

| Поле | Значение |
|---|---|
| `task_name` | `discovery_task` |
| `companies_found` | сколько найдено всего |
| `companies_enriched` | сколько записано как `discovered` |
| `errors` | JSON array |
| `notes` | например `no_domain: <K>` |

Уведомление:

```bash
python scripts/notify.py --run-summary '{"task":"discovery_task","segment":"<segment>","discovered":<N>,"dedup_skipped":<X>,"no_domain":<K>}'
```

### 7.10. Особенности этапа

В `discovery_task.md` есть шаг Preview с ожиданием `[yes/no]` перед записью. Для полностью unattended schedule это потенциальный конфликт: routine может ожидать подтверждения, если строго следовать prompt. Если pipeline должен работать автономно по schedule, этот шаг стоит явно переопределить или убрать.

## 8. Stage 2: RelevanceAgent

### 8.1. Цель этапа

`RelevanceAgent` берет компании со статусом `discovered`, проверяет сайт и внешние факты, затем переводит компанию в:

- `relevant`;
- `not_relevant`;
- `manual_review`.

На этом этапе агент отвечает на вопрос: это реальная компания, которая строит собственные AI/ML модели и потенциально подходит под ICP?

### 8.2. Входы

SQL:

```sql
SELECT domain, name, website, icp_segment, sources, source_page_url
FROM companies
WHERE status = 'discovered'
ORDER BY created_at DESC
LIMIT 30;
```

Дополнительные источники:

- company website через WebFetch;
- HuggingFace MCP;
- WebSearch по jobs;
- WebSearch по LinkedIn;
- WebSearch по funding.

### 8.3. Quick Filter

Агент делает:

```text
WebFetch: https://<domain>
```

Если не работает:

```text
WebFetch: https://www.<domain>
```

Ключевой вопрос:

```text
Компания разрабатывает собственные AI/ML модели, а не просто использует чужие?
```

Сигналы pass:

- обучение моделей;
- датасеты;
- fine-tuning;
- формулировки `we train`, `our model`, `custom AI`, `proprietary model`;
- ML/AI вакансии;
- продукт явно в ML-домене.

Quick reject:

| Причина | `reject_reason` |
|---|---|
| parked/dead website | `dead_website` |
| SaaS без ML | `no_ai_dev` |
| OpenAI/ChatGPT wrapper как основной продукт | `api_wrapper` |
| датасет-провайдер или аннотатор | `competitor` |
| крупная корпорация | `too_large` |

Cloudflare/captcha не блокирует. Агент ставит `site_note=behind_protection` и идет к глубоким проверкам.

### 8.4. Глубокая верификация

Для компаний, прошедших Quick Filter:

1. HuggingFace MCP:
   - поиск организации по имени/домену;
   - число моделей;
   - pipeline tags;
   - дата активности.
2. Jobs WebSearch:
   - `"<company name>" jobs "ML engineer" OR "data annotation" OR "training data"`;
   - достаточно одного релевантного job posting.
3. Фактура:
   - description из сайта или HF профиля;
   - LinkedIn URL;
   - team size;
   - funding stage;
   - funding date.

### 8.5. Решение

Правила:

| Outcome | Условие |
|---|---|
| `relevant` | Quick Filter pass и есть хотя бы одно конкретное доказательство |
| `not_relevant` | quick reject или не найдено подтверждений |
| `manual_review` | признаки есть, но данных мало или ситуация неоднозначна |

### 8.6. Записи в БД

Для `relevant`:

| Таблица | Поля |
|---|---|
| `companies` | `status='relevant'`, `description`, `linkedin_url`, `team_size`, `funding_stage`, `funding_date`, `website_snippet`, `site_note`, `last_verified`, `updated_at` |
| `signals` | новые HF/job verification signals, `ON CONFLICT(evidence_url) DO NOTHING` |
| `run_logs` | `task_name='relevance_task'`, counts, errors, notes |

Для `not_relevant`:

| Таблица | Поля |
|---|---|
| `companies` | `status='not_relevant'`, `reject_reason`, `last_verified`, `updated_at` |

Для `manual_review`:

| Таблица | Поля |
|---|---|
| `companies` | как `relevant`, но `status='manual_review'`, `site_note` объясняет причину |

Уведомление:

```bash
python scripts/notify.py --run-summary '{"task":"relevance_task","relevant":<N>,"not_relevant":<M>,"manual_review":<K>}'
```

## 9. Stage 2.5: ScoringAgent

### 9.1. Цель этапа

`ScoringAgent` берет `relevant` компании, считает score и решает, стоит ли тратить дорогие этапы глубокого досье.

Результаты:

- `qualified` - идет дальше в Enrichment, Analysis, Conclusions;
- `triaged_out` - остается в базе, глубокое досье не строится.

### 9.2. Входы

SQL:

```sql
SELECT *
FROM companies
WHERE status = 'relevant'
ORDER BY created_at DESC
LIMIT 10;
```

Для каждой компании:

```sql
SELECT *
FROM signals
WHERE normalized_domain = '<domain>';
```

Конфиг:

- `config/scoring.yaml`.

### 9.3. Детерминированный score

Инструмент:

```bash
echo '<company_profile_json>' | python scripts/score.py
```

`scripts/score.py`:

- не делает сетевых вызовов;
- не пишет в БД;
- читает `config/scoring.yaml`;
- возвращает JSON score breakdown.

Компоненты score:

| Компонент | Что учитывает |
|---|---|
| `training_intensity` | признаки активного обучения моделей |
| `external_data_fit` | вакансии/сигналы потребности в training data, annotation, RLHF, high-data industries |
| `commercial_readiness` | funding stage, funding recency |
| `freshness` | свежесть самого свежего сигнала |
| `negative_flags` | конкуренты/data providers и другие минусы |

`config/scoring.yaml` сейчас содержит:

- `version: v0.1`;
- `thresholds.qualified: 999`;
- `thresholds.manual_review: 15`.

Это shadow mode: автоматический Hot почти невозможен, но Warm может проходить в `qualified`, потому что gate смотрит на `manual_review` threshold.

### 9.4. LLM-корректировка

После deterministic score агент делает LLM adjustment в пределах `-15..+15`.

Он смотрит:

- description;
- snippets вакансий;
- последние новости;
- признаки прямой потребности в датасетах или разметке.

Сильные плюсы:

- компания строит собственный dataset;
- свежий анонс модели;
- Head of Data/Data Operations roles;
- явный запуск разметки.

Минусы:

- только API wrapper;
- pre-product;
- расплывчатое описание;
- готовые чужие модели без собственной ML-разработки.

### 9.5. Записи в БД

Если проходит gate:

| Таблица | Поля |
|---|---|
| `companies` | `score`, `score_bucket='Hot'/'Warm'`, `score_version`, `ai_direction`, `status='qualified'`, `updated_at` |

Если не проходит:

| Таблица | Поля |
|---|---|
| `companies` | `score`, `score_bucket='Cold'`, `score_version`, `ai_direction`, `status='triaged_out'`, `updated_at` |

Уведомления:

- hot lead:

```bash
python scripts/notify.py --hot-lead '{"name":"<name>","domain":"<domain>","score":<score>,"segment":"<segment>"}'
```

- summary:

```bash
python scripts/notify.py --run-summary '{"task":"scoring_task","found":<N>,"qualified":<M>,"triaged_out":<K>,"errors":0}'
```

## 10. Stage 3: EnrichmentAgent

### 10.1. Цель этапа

`EnrichmentAgent` не анализирует компанию. Он собирает URL-ручки, которые понадобятся следующему этапу для глубокого анализа.

Он берет `qualified` компании и пишет `source_links`.

### 10.2. Входы

SQL:

```sql
SELECT domain, name, website, icp_segment
FROM companies
WHERE status = 'qualified'
ORDER BY score DESC NULLS LAST
LIMIT 10;
```

### 10.3. Детерминированные резолверы

Команда:

```bash
python scripts/enrichment.py --domain <domain>
```

Скрипт сам пишет найденные ссылки в `source_links`.

Включенные resolvers:

| Resolver | Источник | Что пишет |
|---|---|---|
| `GithubOrgResolver` | уже сохраненные `signals.evidence_url` или `source_page_url` | `kind=github_org`, `url=https://github.com/<org>` |
| `WaybackResolver` | `http://archive.org/wayback/available?url=<domain>` | `kind=wayback`, closest snapshot URL |

Выключенные stubs:

- LinkedIn;
- Crunchbase;
- Similarweb.

### 10.4. MCP/WebSearch ручки

Agent prompt просит добрать:

| `kind` | Как искать |
|---|---|
| `hf_org` | HuggingFace MCP по имени/домену |
| `news_feed` | WebSearch по news, RSS блога или press page |
| `social` | WebSearch по Twitter/X, ссылки с сайта |
| `wikidata` | WebSearch `site:wikidata.org` |

Запись через:

```bash
echo '{"company_domain":"<domain>","kind":"<kind>","url":"<url>","source":"<resolver>","confidence":"medium"}' \
  | python scripts/dossier_store.py --upsert-source-link
```

### 10.5. Записи в БД

Таблица `source_links`:

| Поле | Значение |
|---|---|
| `company_domain` | domain компании |
| `kind` | `github_org`, `wayback`, `hf_org`, `news_feed`, `social`, `wikidata`, etc. |
| `url` | найденный source URL |
| `source` | resolver или manual source |
| `confidence` | `high/medium/low` |
| `found_via` | optional provenance |
| `raw` | optional raw JSON |
| `fetched_at` | timestamp |

Unique key:

```text
(company_domain, kind, url)
```

После сбора:

| Таблица | Поля |
|---|---|
| `companies` | `status='sources_gathered'`, `updated_at` |

Уведомление:

```bash
python scripts/notify.py --run-summary '{"task":"enrichment_task","processed":<N>,"links_total":<M>}'
```

## 11. Stage 4: AnalysisAgent

### 11.1. Цель этапа

`AnalysisAgent` берет `sources_gathered` компании и строит промежуточные structured notes по секциям досье.

В отличие от Enrichment, здесь агент уже интерпретирует факты:

- что компания заявляет о себе;
- что подтверждается источниками;
- где есть пробелы;
- как это связано с продажей data services.

### 11.2. Входы

SQL:

```sql
SELECT domain, name, icp_segment
FROM companies
WHERE status = 'sources_gathered'
ORDER BY score DESC NULLS LAST
LIMIT 5;
```

Контекст для секционных агентов:

```bash
python scripts/dossier_store.py --list-source-links <domain>
```

Плюс SQL:

```sql
SELECT name, website, icp_segment, description, funding_stage, team_size
FROM companies
WHERE domain = '<domain>';

SELECT *
FROM signals
WHERE normalized_domain = '<domain>';
```

### 11.3. Параллельные section sub-agents

Prompt требует запустить пять независимых под-агентов через Task tool:

| Section | Что изучает |
|---|---|
| `company` | сайт/About, Wikidata, Wayback, размер, локация, дата основания, глава, динамика позиционирования |
| `product` | сайт/docs, GitHub org, HF org, Product Hunt, продукт, технологии, пивоты |
| `collaboration` | партнеры, team page, GitHub/HF members, поставщики данных, ЛПР |
| `financials` | funding news, SEC/гранты если есть, инвесторы, рост/burn |
| `news` | новости за 6-12 месяцев, dedup по инфоповодам |

Инструменты секционных агентов:

- `dossier_store.py --list-source-links`;
- WebFetch;
- Claude-in-Chrome для JS-сайтов, если доступно;
- HuggingFace MCP;
- WebSearch;
- SQL/Supabase для companies/signals;
- `dossier_store.py --upsert-analysis-note`.

### 11.4. Запись section notes

Команда:

```bash
echo '{
  "company_domain":"<domain>",
  "section":"<section>",
  "facts":{ "<key>":"<value>" },
  "sources":[ {"url":"<url>","note":"<what this source supports>"} ],
  "confidence":"<high|medium|low>",
  "model":"claude",
  "version":"v1"
}' | python scripts/dossier_store.py --upsert-analysis-note
```

Таблица `analysis_notes`:

| Поле | Значение |
|---|---|
| `company_domain` | domain компании |
| `section` | `company/product/collaboration/financials/news/audit` |
| `facts` | structured facts JSON |
| `sources` | list of `{url, note}` |
| `confidence` | `high/medium/low` |
| `model` | model label, обычно `claude` |
| `version` | default `v1` |
| `created_at` | timestamp |

Unique key:

```text
(company_domain, section, version)
```

### 11.5. Audit sub-agent

После пяти секций запускается audit sub-agent.

Он читает:

```bash
python scripts/dossier_store.py --list-analysis-notes <domain>
```

Ожидает секции:

- `company`;
- `product`;
- `collaboration`;
- `financials`;
- `news`.

Пишет секцию:

```text
section='audit'
```

В `facts` должны быть:

- `claims_vs_reality`;
- `market_position`;
- `forecast`;
- `sales_opportunity`;
- `contact_angle`.

### 11.6. Статус и уведомление

После секций и audit:

| Таблица | Поля |
|---|---|
| `companies` | `status='analyzed'`, `updated_at` |

Уведомление:

```bash
python scripts/notify.py --run-summary '{"task":"analysis_task","analyzed":<N>,"errors":<K>}'
```

Если секционный под-агент упал, prompt допускает продолжение: остальные секции пишутся, audit отмечает пробел, компания все равно может быть переведена в `analyzed`.

## 12. Stage 5: ConclusionAgent

### 12.1. Цель этапа

`ConclusionAgent` собирает финальное досье из `analysis_notes`, пишет `dossiers`, публикует информацию в Notion и переводит компанию в `dossier_ready`.

Это финальный этап основного pipeline. Outreach остается ручным.

### 12.2. Входы

SQL:

```sql
SELECT domain, name, website, icp_segment, score, score_bucket, ai_direction
FROM companies
WHERE status = 'analyzed'
ORDER BY score DESC NULLS LAST
LIMIT 5;
```

Notes:

```bash
python scripts/dossier_store.py --list-analysis-notes <domain>
```

Ожидаются:

- `company`;
- `product`;
- `collaboration`;
- `financials`;
- `news`;
- `audit`.

### 12.3. Сборка summary

Агент строит `summary_md` строго из фактов notes и сохраняет provenance links.

Разделы:

1. `О компании`;
2. `Продукт`;
3. `Сотрудничество`;
4. `Финансовое здоровье`;
5. `Новости`.

Отдельно:

- `audit_md` из audit note;
- `sections` как structured JSON;
- `table_fields` как provisional structured fields для будущей таблицы.

### 12.4. Запись dossier

Команда:

```bash
echo '{
  "company_domain":"<domain>",
  "summary_md":"<summary_md>",
  "sections":{ "company":"...", "product":"...", "collaboration":"...", "financials":"...", "news":"..." },
  "audit_md":"<audit_md>",
  "table_fields":{
    "name":"<name>",
    "website":"<website>",
    "segment":"<segment>",
    "score":<score>,
    "bucket":"<bucket>",
    "sales_opportunity":"<from audit>",
    "contact_angle":"<from audit>"
  },
  "version":"v1"
}' | python scripts/dossier_store.py --upsert-dossier
```

Таблица `dossiers`:

| Поле | Значение |
|---|---|
| `company_domain` | primary key |
| `summary_md` | финальное markdown summary |
| `sections` | structured sections JSON |
| `audit_md` | audit markdown |
| `table_fields` | provisional structured fields |
| `version` | `v1` |
| `generated_at` | timestamp |
| `notion_page_id` | есть в миграциях, но текущий sync пишет досье в company page |

### 12.5. Notion sync

Команды:

```bash
python scripts/notion_sync.py --entity companies --all
python scripts/notion_sync.py --entity dossiers
```

В полном `pipeline_task.md` дополнительно вызывается:

```bash
python scripts/notion_sync.py --entity contacts --all
```

#### Companies sync

`--entity companies --all` делает:

1. reverse sync:
   - Notion -> Supabase for whitelisted manual fields;
   - `outreach_status`;
   - `outreach_note`.
2. forward sync:
   - Supabase -> Notion for curated fields;
   - creates or updates Notion page.

Если page не существует, `notion_sync.py` создает страницу и пишет назад:

| Таблица | Поля |
|---|---|
| `companies` | `notion_page_id`, `notion_synced_at` |

#### Dossiers sync

`--entity dossiers`:

1. Читает `companies` с `notion_page_id`.
2. Читает `dossiers`.
3. Для каждого dossier находит company page.
4. Конвертирует `summary_md` и `audit_md` в Notion blocks.
5. Append children в body страницы компании.

#### Contacts sync

`--entity contacts --all`:

1. Читает `contacts`.
2. Читает `contact_companies`.
3. Читает `companies.notion_page_id`.
4. Формирует relation `company_page_ids`.
5. Создает/обновляет contact pages.
6. Пишет reverse field `contact_result` из Notion в Supabase.

В основном pipeline контакты могут быть пустыми, потому что `dm_enrich_task.md` сейчас не вызывается.

### 12.6. Финальный статус и уведомления

После Notion:

| Таблица | Поля |
|---|---|
| `companies` | `status='dossier_ready'`, `updated_at` |

Уведомление:

```bash
python scripts/notify.py --run-summary '{"task":"conclusions_task","dossier_ready":<N>,"errors":<K>}'
```

Hot lead notification может отправляться дополнительно, если score выше `threshold_qualified`.

## 13. Stage 6: итоговое покрытие

После всех этапов `PipelineAgent` снова выполняет:

```bash
python scripts/supabase_store.py --coverage
```

Читает:

- `companies.icp_segment`;
- `companies.status`.

Цель:

- получить итоговую картину по сегментам;
- подготовить numbers для финального notify.

Записей в БД нет.

## 14. Stage 7: финальное уведомление и остановка

Финальная команда из `pipeline_task.md`:

```bash
python scripts/notify.py --run-summary '{"task":"pipeline","found":<N>,"qualified":<N>,"dossier_ready":<N>,"errors":<N>}'
```

`scripts/notify.py`:

- читает `TELEGRAM_BOT_TOKEN`;
- читает `TELEGRAM_CHAT_ID`;
- POST-ит в Telegram Bot API `sendMessage`;
- возвращает exit code `0`, если отправка успешна.

Если весь pipeline критически упал:

```bash
python scripts/notify.py --error '{"task":"pipeline","error":"<short description>"}'
```

После финального уведомления routine завершает сессию. Внешнего callback в Telegram bot нет.

## 15. Статус-машина компаний

Канонический список в `scripts/models.py`:

```text
discovered
relevant
not_relevant
manual_review
triaged_out
qualified
sources_gathered
analyzed
dossier_ready
needs_update
pending_verify
```

Основной путь:

```text
discovered
  -> relevant
  -> qualified
  -> sources_gathered
  -> analyzed
  -> dossier_ready
```

Reject/manual branches:

```text
discovered
  -> not_relevant

discovered
  -> manual_review

relevant
  -> triaged_out
```

Monitor branches:

```text
dossier_ready / historical enriched
  -> needs_update
  -> pending_verify
```

Важный drift: часть старых скриптов и prompt-файлов еще упоминает `new`, `pending_enrich`, `enriched`. В новой основной цепочке они не являются основным путем.

## 16. Таблицы БД и кто их пишет

### 16.1. `companies`

Главная таблица компаний и pipeline state.

Пишут:

- `DiscoveryAgent`;
- `RelevanceAgent`;
- `ScoringAgent`;
- `EnrichmentAgent`;
- `AnalysisAgent`;
- `ConclusionAgent`;
- `notion_sync.py`;
- `contacts_store.py --mark-enriched`;
- `MonitorAgent` в отдельном контуре.

Ключевые поля:

| Поле | Кто пишет | Когда |
|---|---|---|
| `domain` | Discovery | при создании |
| `name` | Discovery | при создании |
| `website` | Discovery/Relevance | при создании или верификации |
| `status` | все stage agents | на переходах статусов |
| `icp_segment` | Discovery | при создании |
| `sources` | Discovery | список источников |
| `source_page_url` | Discovery | primary source page, если колонка есть |
| `description` | Relevance | после проверки |
| `linkedin_url` | Relevance/Notion sync | если найдено |
| `team_size` | Relevance | если найдено |
| `funding_stage` | Relevance | если найдено |
| `funding_date` | Relevance | если найдено |
| `website_snippet` | Relevance | quick filter audit |
| `site_note` | Relevance | technical note |
| `reject_reason` | Relevance | для `not_relevant` |
| `last_verified` | Relevance/Monitor | дата проверки |
| `score` | Scoring | после score |
| `score_bucket` | Scoring | Hot/Warm/Cold |
| `score_version` | Scoring | версия scoring config |
| `ai_direction` | Scoring | LLM explanation |
| `notion_page_id` | Notion sync | после создания Notion page |
| `notion_synced_at` | Notion sync | после создания page |
| `outreach_status` | Notion reverse sync | ручное поле из Notion |
| `outreach_note` | Notion reverse sync | ручная заметка из Notion |
| `dm_enriched_at` | Contacts store | если DM enrichment запускался |
| `latest_signal` | Discovery/Relevance/Monitor | human-readable signal |
| `last_signal_date` | Monitor/Relevance if filled | дата последнего сигнала |

### 16.2. `signals`

Сигналы discovery и verification.

Пишут:

- `DiscoveryAgent`;
- `RelevanceAgent`;
- `MonitorAgent`;
- `SupabaseStore.upsert_signal()` если используется из скрипта.

Поля:

| Поле | Назначение |
|---|---|
| `source` | источник сигнала |
| `signal_type` | тип сигнала |
| `company_name` | имя компании, если колонка есть |
| `domain` | raw domain, если колонка есть |
| `normalized_domain` | link to `companies.domain` |
| `linkedin_url` | optional, если колонка есть |
| `evidence_url` | unique proof URL |
| `signal_date` | дата сигнала |
| `confidence` | confidence |
| `parser_version` | версия parser |
| `raw_data` | raw payload |
| `source_page_url` | expected by some code/prompts, но live DB audit говорит о drift |

### 16.3. `run_logs`

Легкая история запусков этапов.

Пишут:

- stage prompts через SQL;
- `SupabaseStore.log_run()`.

Читают:

- Telegram `/status`;
- Telegram `/last`.

Поля:

| Поле | Назначение |
|---|---|
| `task_name` | имя этапа |
| `started_at` | старт |
| `finished_at` | завершение, сейчас часто пустое |
| `companies_found` | count found |
| `companies_enriched` | count written/enriched |
| `errors` | JSON error list |
| `notes` | free-form summary |

Замечание: `finished_at` используется ботом для определения активного run, но текущие prompts часто делают insert без последующего update `finished_at`.

### 16.4. `source_links`

Ссылки-источники для глубокого анализа.

Пишут:

- `scripts/enrichment.py`;
- `scripts/dossier_store.py --upsert-source-link`;
- `EnrichmentAgent`.

Поля:

| Поле | Назначение |
|---|---|
| `company_domain` | компания |
| `kind` | тип ссылки |
| `url` | URL |
| `source` | resolver/source |
| `confidence` | confidence |
| `found_via` | optional |
| `raw` | raw metadata |
| `fetched_at` | timestamp |

### 16.5. `analysis_notes`

Промежуточные AI notes по секциям досье.

Пишут:

- section sub-agents;
- audit sub-agent;
- `scripts/dossier_store.py --upsert-analysis-note`.

Поля:

| Поле | Назначение |
|---|---|
| `company_domain` | компания |
| `section` | `company/product/collaboration/financials/news/audit` |
| `facts` | structured facts |
| `sources` | list of supporting URLs |
| `confidence` | confidence |
| `model` | model label |
| `version` | version |
| `created_at` | timestamp |

### 16.6. `dossiers`

Финальное досье.

Пишут:

- `ConclusionAgent`;
- `scripts/dossier_store.py --upsert-dossier`.

Читает:

- `scripts/notion_sync.py --entity dossiers`.

Поля:

| Поле | Назначение |
|---|---|
| `company_domain` | primary key |
| `summary_md` | финальное summary |
| `sections` | sections JSON |
| `audit_md` | audit markdown |
| `table_fields` | provisional structured fields |
| `version` | version |
| `generated_at` | timestamp |
| `notion_page_id` | present in migrations, текущий sync в основном использует company page |

### 16.7. `contacts`

Контакты/ЛПР. Это дополнительный контур, не основной full pipeline.

Пишут:

- `contacts_store.py --upsert`;
- `contact_enricher.py`;
- `DMEnrichAgent`.

Поля:

| Группа | Поля |
|---|---|
| identity | `company_domain`, `full_name`, `first_name`, `last_name` |
| role | `title`, `title_normalized`, `dm_priority` |
| channels | `email`, `email_status`, `email_source`, `linkedin_url`, `twitter_handle`, `github_username`, `hf_username`, `personal_website`, `phone`, `instagram_url`, `facebook_url` |
| provenance | `source_vector`, `source_url`, `confidence`, `raw_payload` |
| outreach | `outreach_status`, `outreach_note`, `contact_result`, `info` |
| Notion | `notion_page_id`, relation via `contact_companies` |

### 16.8. `contact_companies`

Many-to-many relation between contacts and companies.

Пишет:

- `contacts_store.py` if input contact JSON has `company_domains`.

Поля:

- `contact_id`;
- `company_domain`.

### 16.9. `bot_presets`

Пресеты запуска Telegram bot.

Пишут:

- `bot/presets.py`;
- `/presets save`;
- `ensure_seed_presets()`.

Поля:

- `name`;
- `config`;
- `owner`;
- `is_default`;
- `created_at`.

## 17. Инструменты и side effects

### 17.1. Read-only or stdout-only tools

| Tool | Reads | Writes | Output |
|---|---|---|---|
| `huggingface.py` | HF API | optional file only if `--output` | JSON candidates |
| `github.py` | GitHub API, `config/icp.yaml` | none | JSON candidates |
| `yc_browser.py` | YC public API, cache file | cache file | JSON candidates |
| `greenhouse.py` | Greenhouse API, CSV slugs | none | JSON signals |
| `score.py` | stdin/profile, `config/scoring.yaml` | none | JSON score |
| `normalize.py` | argument | none | normalized domain |

### 17.2. Database write tools

| Tool | Writes |
|---|---|
| `supabase_store.py` | `companies`, `signals`, `run_logs` through class methods |
| `enrichment.py` | `source_links` through `dossier_store.upsert_source_link` |
| `dossier_store.py --upsert-source-link` | `source_links` |
| `dossier_store.py --upsert-analysis-note` | `analysis_notes` |
| `dossier_store.py --upsert-dossier` | `dossiers` |
| `contacts_store.py --upsert` | `contacts`, optional `contact_companies` |
| `contacts_store.py --mark-enriched` | `companies.dm_enriched_at` |
| `notion_sync.py` | Notion pages and `companies.notion_page_id/notion_synced_at`, reverse fields |

### 17.3. External communication tools

| Tool | External system | Side effect |
|---|---|---|
| `notify.py` | Telegram Bot API | sends message |
| `telegram_routines.py` | Telegram Bot API via `notify.send` | sends digest/hot/stale messages |
| `bot/gateway.py` | Telegram Bot API | replies to user, edits wizard messages |
| `bot/routine.py` | Anthropic Routine API | triggers routine run |
| `notion_sync.py` | Notion API | creates/updates Notion pages, appends dossier blocks |

## 18. Notion sync mechanics

`notion_sync.py` is intentionally config-driven.

### 18.1. Forward sync

Direction:

```text
Supabase -> Notion
```

Mechanics:

1. Load `config/notion_mapping.yaml`.
2. For selected entity, fetch rows from Supabase.
3. Apply optional `db_status_filter`.
4. Convert DB values to Notion property payloads.
5. If `notion_page_id` exists, update page.
6. If not, create page.
7. After creating company page, write back `notion_page_id` and `notion_synced_at`.

### 18.2. Reverse sync

Direction:

```text
Notion -> Supabase
```

Mechanics:

1. Index rows with `notion_page_id`.
2. Query Notion database.
3. Read only fields marked `direction: reverse`.
4. Convert Notion property values to Python values.
5. Update Supabase only if values changed.

Reverse fields are manual CRM fields. This keeps Notion useful for human workflow without making all Notion fields authoritative.

### 18.3. Dossier sync

`notion_sync.py --entity dossiers` does not create separate dossier database pages. It appends `summary_md` and `audit_md` as blocks to the company Notion page found by `companies.notion_page_id`.

## 19. Дополнительные ветки, которые не входят в основной full pipeline

### 19.1. DM enrichment

Prompt:

```text
agents/prompts/dm_enrich_task.md
```

Скрипты:

- `dm_github.py`;
- `dm_apollo.py`;
- `dm_wellfound.py`;
- `dm_team_page.py`;
- `dm_huggingface_contacts.py`;
- `dm_contact_page.py`;
- `contacts_store.py`;
- `contact_enricher.py`.

Источники:

- GitHub org members and commits;
- Apollo People Search;
- Wellfound company page;
- website team/about pages;
- HuggingFace org members;
- contact pages;
- Hunter.io email verifier, if `HUNTER_API_KEY` exists.

Записи:

- `contacts`;
- `contact_companies`;
- `companies.dm_enriched_at`;
- Notion contacts database via `notion_sync.py` or prompt-specific Notion flow.

Important drift:

- `dm_enrich_task.md` ожидает `companies.status = 'enriched'`;
- основная новая цепочка использует `qualified`, `sources_gathered`, `analyzed`, `dossier_ready`;
- `pipeline_task.md` не вызывает `dm_enrich_task.md`.

То есть DM enrichment существует как отдельная ветка, но не является частью текущего full pipeline.

### 19.2. Monitor task

Prompt:

```text
agents/prompts/monitor_task.md
```

Цель:

- ежедневно проверять старые компании на новые сигналы;
- ставить `needs_update` или `pending_verify`;
- отправлять Telegram уведомления по сильным сигналам.

Источники:

- HuggingFace MCP;
- WebSearch jobs;
- WebSearch news/funding/model/dataset.

Записи:

- `companies.latest_signal`;
- `companies.last_signal_date`;
- `companies.status='needs_update'`;
- `companies.status='pending_verify'`;
- `signals`;
- Telegram message.

Important drift:

- prompt говорит про статусы `enriched` и `pending_verify`;
- `enriched` относится к старому контуру.

### 19.3. Telegram operational routines

Файл:

```text
scripts/telegram_routines.py
```

Команды через bot:

- `/digest`;
- `/hot`;
- `/stale`.

Что читают:

- `SupabaseStore.stats()`;
- `SupabaseStore.coverage_by_segment()`;
- `SupabaseStore.list_hot_leads()`;
- `SupabaseStore.list_stale_review_queue()`.

Что пишут:

- ничего в БД;
- отправляют Telegram message.

Important drift:

- `list_hot_leads()` сейчас фильтрует `status='enriched'` и `score_bucket='Hot'`;
- новая основная цепочка не использует `enriched`.

### 19.4. Deprecated prompts

Файлы оставлены для справки:

- `research_task.md`;
- `collection_task.md`;
- `verify_task.md`;
- `source_expansion_task.md`;
- `discover_verify_task.md`.

Они относятся к старой схеме со статусами:

- `new`;
- `pending_enrich`;
- `enriched`.

Новый основной путь разделен на:

- `discovery_task.md`;
- `relevance_task.md`;
- `scoring_task.md`;
- deep stages.

### 19.5. GitHub workflow

`.github/workflows/main.yml` не запускает agent pipeline. Он только dispatch-ит событие в parent repo `Katoli-IV-ka/kvetio` при push в `main`.

## 20. Известные рассинхроны и риски понимания

### 20.1. Prompt parameters не полностью реализованы

`RunConfig` и Telegram wizard поддерживают:

- subset `stages`;
- `dry_run`;
- `notion_sync`.

Но `pipeline_task.md` сейчас описывает полный pipeline и не содержит строгой механики пропуска этапов или отключения Notion sync.

Практический вывод: считать `stages`, `dry_run`, `notion_sync` интерфейсом будущей/частичной поддержки, а не надежной гарантией поведения.

### 20.2. Human confirmation внутри discovery

`discovery_task.md` просит Preview и `[yes/no]` перед записью. Это хорошо для ручного запуска, но плохо для schedule routine.

Если schedule должен быть автономным, это надо исправить в prompt.

### 20.3. Live DB drift

`docs/DB-FIELD-AUDIT-2026-06-16.md` фиксирует drift:

- live `signals` может не иметь `company_name`, `domain`, `linkedin_url`, `source_page_url`, хотя code/prompts это ожидают;
- live `companies` может не иметь `source_page_url`, хотя prompts это ожидают;
- `pipeline_runs` уже исчезла в live DB;
- некоторые empty tables есть, но еще не используются.

Перед боевым прогоном стоит сверить live schema и локальные миграции.

### 20.4. `run_logs.finished_at`

Telegram `/status` ищет активный run как последний `run_logs` с `finished_at IS NULL`.

Но многие записи создаются как insert без финального update `finished_at`. Это может приводить к ложному "active run".

### 20.5. Contacts контур есть, но pipeline его не кормит

`pipeline_task.md` синхронизирует contacts в Notion, но не запускает `dm_enrich_task.md`. Если контакты пустые, sync пройдет, но не создаст полезных записей.

### 20.6. Stubs and disabled sources

В registry и code есть stubs:

- Lever;
- LinkedIn;
- Crunchbase;
- Similarweb;
- SEC EDGAR;
- GDELT;
- grants.

Они обозначают будущие возможности, но не являются активной частью pipeline.

## 21. Как читать результат запуска

После run полезно смотреть:

1. Telegram final notification from `notify.py`.
2. Supabase `run_logs`:
   - какие stages отработали;
   - counts;
   - errors;
   - notes.
3. Supabase `companies` by status:
   - сколько `discovered`;
   - сколько `relevant`;
   - сколько `qualified`;
   - сколько `dossier_ready`.
4. Supabase `signals`:
   - evidence URLs;
   - source mix.
5. `source_links`:
   - достаточно ли ссылок для analysis.
6. `analysis_notes`:
   - все ли 6 секций есть.
7. `dossiers`:
   - есть ли `summary_md` и `audit_md`.
8. Notion:
   - created/updated company pages;
   - appended dossier blocks.

## 22. Минимальная end-to-end трасса

Ниже компактная трасса одного потенциального лида.

```text
1. Telegram /quickrun nightly-full
2. bot/gateway.py loads preset from bot_presets
3. bot/routine.py POSTs /fire with text
4. Routine starts PipelineAgent
5. PipelineAgent reads config/icp.yaml and coverage
6. DiscoveryAgent runs huggingface/github/yc/greenhouse for medical-imaging
7. Candidate "Acme Medical AI" appears from HuggingFace
8. Agent resolves acme.ai by source domain or WebSearch
9. Agent writes companies(acme.ai, status=discovered)
10. Agent writes signals(evidence_url=https://huggingface.co/acme, normalized_domain=acme.ai)
11. RelevanceAgent WebFetches acme.ai
12. RelevanceAgent finds own model/fine-tuning evidence and HF/job proof
13. Agent updates companies.status=relevant, fills description/funding/team fields
14. ScoringAgent reads company + signals
15. score.py returns base score and bucket
16. Agent applies LLM adjustment
17. Agent updates companies.status=qualified, score, score_bucket, ai_direction
18. EnrichmentAgent runs enrichment.py
19. enrichment.py writes source_links(github_org/wayback)
20. Agent adds hf_org/news/social/wikidata source_links
21. Agent updates companies.status=sources_gathered
22. AnalysisAgent starts 5 section sub-agents
23. Each section writes analysis_notes
24. Audit sub-agent writes analysis_notes(section=audit)
25. Agent updates companies.status=analyzed
26. ConclusionAgent reads notes
27. Agent writes dossiers(summary_md, audit_md, sections)
28. notion_sync.py creates/updates company page and appends dossier
29. Agent updates companies.status=dossier_ready
30. PipelineAgent sends final Telegram summary
31. Routine stops
```

## 23. Практическая карта файлов по этапам

| Этап | Prompt | Scripts | Tables |
|---|---|---|---|
| Trigger | none | `bot/gateway.py`, `bot/dialog.py`, `bot/presets.py`, `bot/routine.py` | `bot_presets`, read `run_logs` |
| Pipeline orchestration | `pipeline_task.md` | shell, stage scripts | all pipeline tables |
| Coverage | inline in `pipeline_task.md` | `supabase_store.py --coverage` | read `companies` |
| Discovery | `discovery_task.md` | `huggingface.py`, `github.py`, `yc_browser.py`, `greenhouse.py`, `normalize.py`, `notify.py` | `companies`, `signals`, `run_logs` |
| Relevance | `relevance_task.md` | WebFetch/WebSearch/HF MCP, `notify.py` | `companies`, `signals`, `run_logs` |
| Scoring | `scoring_task.md` | `score.py`, `notify.py` | `companies` |
| Enrichment | `enrichment_task.md` | `enrichment.py`, `dossier_store.py`, WebSearch/HF MCP, `notify.py` | `source_links`, `companies` |
| Analysis | `analysis_task.md`, `analysis_section_task.md`, `analysis_audit_task.md` | `dossier_store.py`, WebFetch/WebSearch/HF MCP, Task tool | `analysis_notes`, `companies` |
| Conclusions | `conclusions_task.md` | `dossier_store.py`, `notion_sync.py`, `notify.py` | `dossiers`, `companies`, Notion |
| Contacts side flow | `dm_enrich_task.md` | `dm_*.py`, `contacts_store.py`, `contact_enricher.py`, `notion_sync.py` | `contacts`, `contact_companies`, `companies.dm_enriched_at`, Notion |
| Monitor side flow | `monitor_task.md` | WebSearch/HF MCP, `notify.py` | `companies`, `signals` |
| Telegram ops | none | `telegram_routines.py`, `notify.py` | read `companies`, Telegram send |

## 24. Итоговая модель понимания

Проект лучше воспринимать как agent harness, где:

- prompt `pipeline_task.md` задает главный loop;
- stage prompts задают policy и business logic для каждого шага;
- Python CLI scripts являются tool registry;
- Supabase является durable state;
- Notion является user-facing projection;
- Telegram является trigger и notification layer;
- старый worker/queue контур удаляется и не должен использоваться;
- часть старых prompt/scripts еще хранит legacy status vocabulary, что важно учитывать при развитии.

Если нужно понять, что реально происходит при полном запуске, стартовая точка всегда:

```text
bot/routine.py or Schedule
  -> agents/prompts/pipeline_task.md
  -> stage prompt
  -> scripts/*.py
  -> Supabase/Notion/Telegram
```

Если нужно понять, куда записываются данные, стартовая точка:

```text
sql/*.sql
  -> scripts/supabase_store.py
  -> scripts/dossier_store.py
  -> scripts/contacts_store.py
  -> scripts/notion_sync.py
  -> stage prompts
```

Если нужно понять источники фактов:

```text
config/sources.yaml
  -> source adapter scripts
  -> WebSearch/WebFetch/MCP usage in prompts
  -> signals/source_links/analysis_notes
```
