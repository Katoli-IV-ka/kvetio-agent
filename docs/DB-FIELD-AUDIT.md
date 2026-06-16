# Database Field Audit

Дата проверки: 2026-06-15  
Supabase project: `Kvetio Project` / `qcfygtxkohopxhsathkv`  
Схема: `public`

## Короткий вывод

В реальной базе сейчас есть 11 таблиц и 2 view:

- Таблицы с данными: `companies` (199 строк), `run_logs` (7 строк).
- Пустые таблицы: `signals`, `contacts`, `source_links`, `analysis_notes`, `dossiers`, `pipeline_runs`, `bot_users`, `bot_presets`, `bot_dialog_state`.
- View: `pipeline_stats`, `recent_leads`.

Есть существенный дрейф между локальными SQL-файлами/промптами и фактической БД:

- В БД нет `companies.source_page_url`, но локальная миграция `sql/003_source_page_url.sql` и агентские промпты ожидают это поле.
- В БД нет `signals.source_page_url`, но локальная миграция `sql/004_signals_source_page_url.sql` и код DM/enrichment ожидают это поле.
- В БД `signals` нет `company_name`, `domain`, `linkedin_url`, хотя `scripts/supabase_store.py` пишет их в `upsert_signal`.
- В БД `contacts` нет `outreach_note`, хотя `sql/006_contacts.sql` и `config/notion_mapping.yaml` ожидают это поле.
- В локальном SQL есть `github_org_cache`, но в реальной БД этой таблицы нет и migration history ее не показывает.
- `pipeline_runs` уже помечена в `docs/RUNBOOK.md` и `docs/CLEANUP-PLAN.md` как таблица на удаление.

Отдельно: Supabase advisory показывает, что RLS выключен на `contacts`, `source_links`, `analysis_notes`, `dossiers`, `pipeline_runs`, `bot_users`, `bot_presets`, `bot_dialog_state`. Это не про чистку полей, но это важный security-risk, если таблицы доступны через anon/authenticated API.

## Как читать оценку удаления

- `Низкая` - можно удалить после удаления 0-2 ссылок в коде/конфигах, обычно без изменения логики.
- `Средняя` - поле участвует в промптах, синке, view или отдельном этапе pipeline; нужно править несколько мест и тесты.
- `Высокая` - поле является ключом, статусом, дедуп-ключом, FK/unique/index основой или используется критическим workflow.

## `companies` - основная таблица лидов

Заполненность nullable-полей на 199 строк:

- Полностью заполнены или почти базовые: `website` 199, `icp_segment` 199, `last_verified` 199, `notion_page_id` 169, `latest_signal` 134, `description` 99, `reject_reason` 94, `sources` non-empty 67.
- Почти пустые: `score` 1, `score_bucket` 1, `ai_direction` 1, `funding_stage` 1, `last_signal_date` 1, `site_note` 6.
- Полностью пустые: `linkedin_url`, `score_version`, `funding_amount`, `funding_date`, `team_size`, `website_snippet`, `dm_enriched_at`, `outreach_status`, `outreach_note`, `notion_synced_at`.

| Поле | Для чего используется | Тип | Сложность удаления |
|---|---|---:|---:|
| `id` | UUID primary key. Внешне почти не используется, но это PK таблицы. | Техническое | Высокая |
| `domain` | Главный дедуп-ключ компании, уникальный идентификатор, soft-FK для многих таблиц. | Техническое + пользовательское | Высокая |
| `name` | Название компании, уходит в Notion, используется в промптах и выводах. | Пользовательское | Высокая |
| `website` | Сайт компании, базовый вход для анализа, Notion forward, prompts. | Пользовательское | Высокая |
| `linkedin_url` | LinkedIn компании, Notion forward. Сейчас пустое. | Пользовательское | Низкая-средняя |
| `description` | Краткое описание, синтезируется агентами, используется analysis/scoring prompts. | Пользовательское | Средняя |
| `status` | Статус pipeline и очередей. Индексируется. | Техническое | Высокая |
| `icp_segment` | ICP-сегмент, фильтры, статистика, Notion forward. | Пользовательское + техническое | Высокая |
| `score` | Числовой скор, hot leads, view `recent_leads`, bot summaries. Сейчас почти пустое. | Пользовательское | Средняя |
| `score_bucket` | Hot/Warm/Cold, view `recent_leads`, hot queue. | Пользовательское + техническое | Средняя-высокая |
| `score_version` | Версия скоринга. Код может писать при наличии score, но сейчас пусто. | Техническое | Низкая-средняя |
| `ai_direction` | LLM-обоснование score; `scoring_task` пишет, `recent_leads` читает. Не включено в текущий Notion mapping. | AI-пользовательское | Средняя |
| `funding_stage` | Стадия финансирования, prompts и analysis/scoring context. Сейчас 1 значение. | Пользовательское | Средняя |
| `funding_amount` | Сумма финансирования. В коде/промптах почти не используется, пустое. | Пользовательское | Низкая |
| `funding_date` | Дата финансирования, prompts пишут/читают. Сейчас пусто. | Пользовательское | Средняя |
| `team_size` | Размер команды, prompts пишут/читают. Сейчас пусто. | Пользовательское | Средняя |
| `latest_signal` | Последний сигнал, Notion forward, monitor, lead views. | Пользовательское | Высокая |
| `last_signal_date` | Дата сигнала, Notion forward, `recent_leads`. Сейчас 1 значение. | Пользовательское + техническое | Средняя |
| `last_verified` | Дата проверки, stale review queue. | Техническое | Высокая |
| `notion_page_id` | Связка с Notion страницей, forward/reverse sync, DM enrichment gate. | Техническое | Высокая |
| `created_at` | Аудит создания. | Техническое | Средняя |
| `updated_at` | Аудит обновления, триггер и код явно обновляют. | Техническое | Высокая |
| `reject_reason` | Причина отклонения, активно заполнено у 94 строк, индексируется. | Пользовательское + audit | Средняя-высокая |
| `site_note` | Техническая пометка сайта: Cloudflare, нет сайта и т.п. | Техническое + audit | Средняя |
| `sources` | JSON provenance: из каких источников найден лид. | Техническое + audit | Средняя |
| `website_snippet` | Аудит quick-filter решения. Сейчас пустое. | Audit | Низкая-средняя |
| `dm_enriched_at` | Маркер, запускался ли DM enrichment. Очередь DM enrichment опирается на NULL. Сейчас пусто. | Техническое | Средняя |
| `outreach_status` | CRM-статус компании, reverse-sync из Notion. Сейчас пусто. | Пользовательское | Средняя |
| `outreach_note` | Ручная заметка компании, reverse-sync из Notion. Сейчас пусто. | Пользовательское | Средняя |
| `notion_synced_at` | Метка создания/синка Notion. Код только пишет при создании страницы, не читает. Сейчас пусто. | Техническое | Низкая |

Кандидаты на удаление из `companies`, если цель - упростить пользовательскую модель: `funding_amount`, `website_snippet`, `score_version`, `notion_synced_at`, возможно `linkedin_url`.  
Кандидаты только после продуктового решения: `team_size`, `funding_stage`, `funding_date`, `ai_direction`, `outreach_status`, `outreach_note`, `dm_enriched_at`.

## `signals` - первичные сигналы обнаружения

Сейчас 0 строк. Реальная таблица меньше, чем локальная схема и код.

| Поле | Для чего используется | Тип | Сложность удаления |
|---|---|---:|---:|
| `id` | UUID primary key. | Техническое | Высокая |
| `normalized_domain` | FK на `companies.domain`, связывает сигнал с компанией. | Техническое | Высокая |
| `source` | Источник сигнала: HF, YC, Greenhouse и т.д. | Audit | Средняя |
| `signal_type` | Тип сигнала: вакансия, repo, hf_org и т.д. | Audit + scoring | Средняя-высокая |
| `evidence_url` | Уникальная ссылка-доказательство, dedup key. | Техническое + audit | Высокая |
| `signal_date` | Дата сигнала, сортировка и freshness. | Техническое + audit | Средняя |
| `confidence` | Уверенность парсера/агента. | Audit | Низкая-средняя |
| `parser_version` | Версия парсера. Сейчас скорее audit/debug. | Техническое | Низкая |
| `raw_data` | Сырой payload источника, нужен для отладки и будущего извлечения. | Техническое + audit | Средняя |
| `created_at` | Аудит создания. | Техническое | Низкая-средняя |

Не удалять, а исправить рассинхрон: добавить или убрать из кода `company_name`, `domain`, `linkedin_url`, `source_page_url`. Сейчас `upsert_signal` пишет поля, которых нет в БД.

## `run_logs` - история запусков/этапов

Сейчас 7 строк, все `task_name = collection_task`.

| Поле | Для чего используется | Тип | Сложность удаления |
|---|---|---:|---:|
| `id` | UUID primary key. | Техническое | Средняя |
| `task_name` | Имя задачи/этапа, индексируется, используется для диагностики. | Техническое | Высокая |
| `started_at` | Время запуска, индексируется, используется для истории. | Техническое | Высокая |
| `finished_at` | Время завершения. Сейчас не заполнено. | Техническое | Низкая-средняя |
| `companies_found` | Сколько компаний найдено. Используется summaries/coverage. | Техническое + отчетное | Средняя |
| `companies_enriched` | Сколько записано/обогащено. | Техническое + отчетное | Средняя |
| `errors` | JSON ошибок. | Техническое | Средняя |
| `notes` | Свободные заметки. Сейчас пусто. | Техническое/audit | Низкая |

Важный рассинхрон: `bot/worker.py` ожидает в `run_logs` поля `stage`, `segment`, `status`, `companies_qualified`, `error`, `created_at`, которых нет в реальной таблице. Либо worker устарел, либо схема недомигрирована.

## `contacts` - контакты ЛПР

Сейчас 0 строк. Таблица нужна только если DM enrichment и Notion contacts остаются частью продукта.

| Поле | Для чего используется | Тип | Сложность удаления |
|---|---|---:|---:|
| `id` | UUID primary key, ключ для Notion sync contacts. | Техническое | Высокая |
| `company_domain` | Связь с компанией и dedup. | Техническое | Высокая |
| `full_name` | Имя контакта, часть unique key. | Пользовательское | Высокая |
| `first_name` | Для email pattern guesser. | Техническое + пользовательское | Средняя |
| `last_name` | Для email pattern guesser. | Техническое + пользовательское | Средняя |
| `title` | Должность, Notion forward. | Пользовательское | Средняя |
| `title_normalized` | Нормализованная роль для приоритета. | AI-техническое | Низкая-средняя |
| `dm_priority` | Приоритет outreach, Notion forward. | Пользовательское + техническое | Средняя |
| `email` | Email контакта, Notion forward. | Пользовательское | Средняя |
| `email_status` | verified/guessed/bounced/unknown, Notion forward. | Техническое + пользовательское | Средняя |
| `email_source` | Источник email. | Audit | Низкая |
| `linkedin_url` | LinkedIn контакта, Notion forward. | Пользовательское | Средняя |
| `twitter_handle` | Twitter/X handle, собирается enrichment. | Пользовательское | Низкая-средняя |
| `github_username` | GitHub username, нужен GitHub profile enrichment. | Техническое + пользовательское | Средняя |
| `source_vector` | Откуда найден контакт: github/hf/team/apollo/etc. | Audit + техническое | Средняя |
| `source_url` | URL-доказательство. | Audit | Низкая-средняя |
| `confidence` | Уверенность контакта. | Audit | Низкая |
| `outreach_status` | CRM-статус контакта, reverse-sync из Notion. | Пользовательское | Средняя |
| `raw_payload` | Сырой ответ источника. | Техническое/audit | Средняя |
| `created_at` | Аудит создания. | Техническое | Низкая-средняя |
| `updated_at` | Аудит обновления, триггер. | Техническое | Средняя |
| `personal_website` | Личный сайт контакта, новый enrichment. | Пользовательское | Низкая-средняя |
| `hf_username` | HuggingFace username, нужен HF profile enrichment. | Техническое + пользовательское | Средняя |
| `notion_page_id` | Связка с Notion contact page. | Техническое | Средняя |

В БД отсутствует `outreach_note`, хотя локальная миграция и Notion mapping его ожидают. Это нужно исправить до reverse-sync contacts.

## `source_links` - ссылки для deep enrichment

Сейчас 0 строк. Таблица питает этап analysis/dossier.

| Поле | Для чего используется | Тип | Сложность удаления |
|---|---|---:|---:|
| `id` | UUID primary key. | Техническое | Средняя |
| `company_domain` | Компания-владелец ссылки. | Техническое | Высокая |
| `kind` | Тип ссылки: github_org, wayback, linkedin и т.д. | Техническое + audit | Высокая |
| `url` | Сама ссылка, часть unique key. | Пользовательское/audit | Высокая |
| `source` | Каким резолвером найдена ссылка. | Audit | Низкая-средняя |
| `confidence` | Уверенность. | Audit | Низкая |
| `found_via` | Дополнительная provenance-пометка. | Audit | Низкая |
| `raw` | Сырой payload резолвера. | Техническое/audit | Низкая-средняя |
| `fetched_at` | Когда ссылка получена. | Техническое | Низкая-средняя |

Если deep dossier pipeline не нужен, можно удалить всю таблицу вместе с `scripts/dossier_store.py` частично и prompts `enrichment/analysis/conclusions`. Если нужен - поля в целом оправданы.

## `analysis_notes` - промежуточные факты анализа

Сейчас 0 строк. Это AI scratchpad для секций досье.

| Поле | Для чего используется | Тип | Сложность удаления |
|---|---|---:|---:|
| `id` | UUID primary key. | Техническое | Средняя |
| `company_domain` | Компания. | Техническое | Высокая |
| `section` | Секция анализа: company/product/collaboration/etc. | AI-техническое | Высокая |
| `facts` | JSON фактов секции. | AI-пользовательское | Высокая |
| `sources` | JSON источников фактов. | Audit | Средняя |
| `confidence` | Уверенность секции. | Audit | Низкая-средняя |
| `model` | Какая модель сгенерировала note. | Техническое/audit | Низкая |
| `version` | Версия note, часть unique key. | Техническое | Средняя |
| `created_at` | Аудит создания. | Техническое | Низкая-средняя |

Кандидаты на упрощение: `model`, возможно `confidence`. Остальные поля держат структуру этапа.

## `dossiers` - финальное досье

Сейчас 0 строк. Пишется conclusions stage и sync в Notion.

| Поле | Для чего используется | Тип | Сложность удаления |
|---|---|---:|---:|
| `company_domain` | Primary key и связь с компанией. | Техническое | Высокая |
| `summary_md` | Финальное summary, пишется в Notion body. | Пользовательское | Высокая |
| `sections` | Структурированное досье JSON. | AI-пользовательское | Средняя-высокая |
| `audit_md` | Аудит/обоснование, пишется в Notion body. | Audit + пользовательское | Средняя |
| `table_fields` | Поля для таблицы/карточки. Сейчас не видно активного чтения в коде. | Пользовательское/AI | Низкая-средняя |
| `version` | Версия досье. | Техническое | Низкая-средняя |
| `generated_at` | Когда сгенерировано. | Техническое | Низкая-средняя |
| `notion_page_id` | Трекинг Notion, но sync сейчас пишет досье в страницу компании через `companies.notion_page_id`; это поле почти не используется. | Техническое | Низкая |

Лучшие кандидаты: `table_fields`, `notion_page_id`, возможно `version`, если не планируется версионирование.

## `pipeline_runs` - очередь worker

Сейчас 0 строк. Документы `docs/RUNBOOK.md` и `docs/CLEANUP-PLAN.md` уже говорят удалить эту таблицу и перейти на routines `/fire`.

| Поле | Для чего используется | Тип | Сложность удаления |
|---|---|---:|---:|
| `id` | UUID run id. | Техническое | Средняя |
| `trigger_type` | manual/scheduled/api. | Техническое | Средняя |
| `triggered_by` | Кто запустил. | Audit | Низкая |
| `config` | RunConfig JSON. | Техническое | Средняя |
| `status` | queued/running/succeeded/etc. | Техническое | Средняя |
| `queued_at` | Очередь. | Техническое | Низкая |
| `started_at` | Старт. | Техническое | Низкая |
| `finished_at` | Завершение. | Техническое | Низкая |
| `heartbeat_at` | Lock/worker heartbeat. | Техническое | Средняя |
| `summary` | Итог запуска. | Пользовательское/audit | Низкая-средняя |
| `error` | Ошибка запуска. | Audit | Низкая |
| `tg_chat_id` | Куда редактировать live message. | Техническое | Низкая |
| `tg_message_id` | Telegram message id. | Техническое | Низкая |

Рекомендация: удалить таблицу целиком после удаления/переписывания `bot/runs.py`, `bot/worker.py`, `/cancel` и тестов `test_bot_runs.py`/`test_bot_summary.py`.

## `bot_users` - устаревший allowlist Telegram bot

Сейчас 0 строк.

| Поле | Для чего используется | Тип | Сложность удаления |
|---|---|---:|---:|
| `chat_id` | Primary key и allowlist identity. | Техническое | Высокая, если бот нужен |
| `username` | Удобное имя оператора. | Пользовательское | Низкая |
| `role` | admin/viewer, доступ к командам. | Техническое | Средняя |
| `active` | Включен ли пользователь. | Техническое | Средняя |
| `added_at` | Аудит добавления. | Audit | Низкая |

Решение: удалить таблицу вместе с `bot/access.py`; доступ к боту ограничивается внешними средствами.

## `bot_presets` - presets запуска

Сейчас 0 строк, но `bot/presets.py` умеет seed presets при первом использовании.

| Поле | Для чего используется | Тип | Сложность удаления |
|---|---|---:|---:|
| `id` | UUID primary key. | Техническое | Средняя |
| `name` | Уникальное имя preset. | Пользовательское | Высокая |
| `config` | RunConfig JSON. | Техническое + пользовательское | Высокая |
| `owner` | Кто создал. | Audit | Низкая |
| `is_default` | Default preset. | Техническое | Средняя |
| `created_at` | Аудит создания. | Audit | Низкая |

Кандидат на упрощение: `owner`, если не нужна история владельца.

## `bot_dialog_state` - устаревшее состояние wizard `/run`

Сейчас 0 строк.

| Поле | Для чего используется | Тип | Сложность удаления |
|---|---|---:|---:|
| `chat_id` | Primary key состояния диалога. | Техническое | Высокая, если wizard нужен |
| `step` | Текущий шаг wizard. | Техническое | Высокая |
| `draft` | JSON черновика RunConfig. | Техническое | Высокая |
| `updated_at` | Время обновления состояния. | Техническое | Низкая |

Решение: удалить таблицу. Multi-step wizard сохраняется, но состояние кодируется в Telegram `callback_data`.

## Views

### `pipeline_stats`

Definition: агрегирует `companies` по `status`.

| Поле view | Источник | Удаление |
|---|---|---:|
| `status` | `companies.status` | Нельзя без удаления/переписывания view |
| `count` | `count(*)` | Производное |

### `recent_leads`

Definition: берет из `companies` последние Hot/Warm лиды за 30 дней или без даты.

| Поле view | Источник | Удаление |
|---|---|---:|
| `domain` | `companies.domain` | Высокая |
| `name` | `companies.name` | Высокая |
| `score` | `companies.score` | Средняя |
| `score_bucket` | `companies.score_bucket` | Средняя-высокая |
| `icp_segment` | `companies.icp_segment` | Высокая |
| `latest_signal` | `companies.latest_signal` | Высокая |
| `last_signal_date` | `companies.last_signal_date` | Средняя |
| `ai_direction` | `companies.ai_direction` | Средняя |
| `notion_page_id` | `companies.notion_page_id` | Высокая |

Перед удалением любого из этих полей надо сначала `CREATE OR REPLACE VIEW recent_leads ...` без поля.

## Локальная, но отсутствующая в реальной БД: `github_org_cache`

Файл `sql/002_github_org_cache.sql` описывает таблицу:

- `org_login` - primary key GitHub org slug.
- `data` - raw JSON ответа GitHub `/orgs/{login}`.
- `cached_at` - timestamp кеширования.

Код `scripts/org_cache.py` ожидает эту таблицу. В реальной БД ее нет. Это не поле на удаление; это выбор: либо применить миграцию, либо удалить cache layer из кода.

## Рекомендованный порядок чистки

1. Сначала исправить дрейф схемы и кода:
   - решить судьбу `source_page_url`;
   - привести `signals` к тому, что пишет `upsert_signal`;
   - добавить или убрать `contacts.outreach_note`;
   - решить, нужен ли `github_org_cache`.
2. Удалить очевидный хвост `pipeline_runs`, если переход на routines `/fire` актуален.
3. Упростить пустые/слабоиспользуемые поля:
   - `companies.funding_amount`;
   - `companies.website_snippet`;
   - `companies.notion_synced_at`;
   - `dossiers.table_fields`;
   - `dossiers.notion_page_id`;
   - `analysis_notes.model`;
   - `bot_presets.owner`.
4. Отдельным решением: оставить или убрать весь DM/contact контур (`contacts`, `dm_enriched_at`, contact scripts, Notion contacts).
5. Отдельным решением: оставить или убрать deep dossier контур (`source_links`, `analysis_notes`, `dossiers`).
