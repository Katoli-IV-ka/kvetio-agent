# Kvetio DB Runtime Usage Audit

Дата аудита: 2026-06-17  
Supabase project: `Kvetio Project` / `qcfygtxkohopxhsathkv`  
Цель: проверить, какие таблицы и поля реально заполнены агентом/скриптами, какие данные лежат в базе, и что эти данные означают.

Cleanup decision 2026-06-17:
- Score fields are removed.
- companies.sources, latest_signal, reject_reason are removed.
- bot_presets and contact_companies are removed.
- contacts.company_id is canonical; contacts.company_domain remains transitional legacy data.
- Notion CRM reverse fields are removed from the agent database.

## 1. Короткий вывод

База сейчас реально используется как runtime-ledger для ранних этапов pipeline:

1. `companies` - основная рабочая таблица; заполнена 328 компаниями.
2. `signals` - evidence-сигналы; заполнена 74 строками.
3. `run_logs` - журнал запусков; заполнен 16 строками.
4. `bot_presets` - Telegram presets; заполнена 3 строками.
5. `contacts`, `contact_companies`, `source_links`, `analysis_notes`, `dossiers` - есть в схеме, но сейчас пустые.

Практический смысл: агент уже выполнял discovery / verify / relevance / частично scoring, но deep research контур (`source_links -> analysis_notes -> dossiers`) и DM-контур (`contacts`) в live DB еще не дали записей.

## 2. Сколько данных реально записано

Точные counts через `SELECT count(*)`:

| Таблица | Rows | Фактическое использование |
|---|---:|---|
| `companies` | 328 | Да, основная рабочая таблица |
| `signals` | 74 | Да, evidence для части компаний |
| `run_logs` | 16 | Да, история запусков, но `finished_at` не закрывается |
| `bot_presets` | 3 | Да, Telegram `/quickrun` presets |
| `analysis_notes` | 0 | Нет live-записей |
| `contact_companies` | 0 | Нет live-записей |
| `contacts` | 0 | Нет live-записей |
| `dossiers` | 0 | Нет live-записей |
| `source_links` | 0 | Нет live-записей |

## 3. `companies`

### 3.1. Что это за данные

`companies` - главная таблица агента. Каждая строка - одна компания/лид. По ней агент понимает:

- какой домен у компании;
- как она называется;
- в каком ICP-сегменте она найдена;
- на каком этапе pipeline она находится;
- что агент уже понял о релевантности;
- есть ли Notion page;
- есть ли score/объяснение, если scoring запускался.

### 3.2. Статусы

| Status | Count | Объяснение |
|---|---:|---|
| `not_relevant` | 114 | Агент отклонил как нерелевантные |
| `relevant` | 97 | Агент считает потенциально релевантными, но дальше они не все прошли |
| `pending_enrich` | 66 | Старый/legacy статус: ожидает обогащения |
| `qualified` | 28 | Прошли scoring/gate и готовы к глубоким этапам |
| `manual_review` | 20 | Нужна ручная проверка |
| `triaged_out` | 2 | Отсечены после scoring/triage |
| `enriched` | 1 | Старый/legacy статус |

Вывод: база смешивает старую и новую статус-машину. Новая документация говорит про `qualified -> sources_gathered -> analyzed -> dossier_ready`, но live DB содержит много `pending_enrich` и один `enriched`.

### 3.3. ICP-сегменты

| ICP segment | Count |
|---|---:|
| `medical-imaging` | 112 |
| `generative-ai` | 76 |
| `robotics-ai` | 39 |
| `agriculture-ai` | 36 |
| `speech-and-audio` | 26 |
| `video-photo-ai` | 26 |
| `autonomous-vehicles` | 13 |

Что можно понять:

- база сильнее всего наполнена `medical-imaging`;
- `autonomous-vehicles` покрыт слабее всего;
- `generative-ai` активно использовался в последнем прогоне 2026-06-16.

### 3.4. Заполненность полей

| Поле | Filled | % | Интерпретация |
|---|---:|---:|---|
| `domain`, `name`, `website`, `status`, `icp_segment`, `last_verified` | 328/328 | 100.0 | Базовый company ledger заполнен полностью |
| `description` | 214/328 | 65.2 | Relevance/verify реально писали описания |
| `sources` | 196/328 | 59.8 | У части компаний есть provenance источников |
| `notion_page_id` | 169/328 | 51.5 | Около половины компаний синхронизированы в Notion |
| `latest_signal` | 134/328 | 40.9 | Есть человекочитаемый последний сигнал не у всех |
| `reject_reason` | 111/328 | 33.8 | Отклонения частично объяснены |
| `site_note` | 36/328 | 11.0 | Технические заметки по сайту используются редко |
| `score`, `score_bucket`, `ai_direction` | 31/328 | 9.5 | Scoring почти не покрывает базу |
| `funding_stage` | 30/328 | 9.1 | Funding почти не собран |
| `linkedin_url` | 30/328 | 9.1 | LinkedIn почти не собран |
| `website_snippet` | 30/328 | 9.1 | Quick filter snippets почти не собраны |
| `funding_date` | 24/328 | 7.3 | Funding date почти не собран |
| `team_size` | 13/328 | 4.0 | Team size почти не собран |
| `last_signal_date` | 1/328 | 0.3 | Почти не используется |
| `dm_enriched_at` | 0/328 | 0.0 | DM enrichment не запускался/не записывался |
| `funding_amount` | 0/328 | 0.0 | Не используется |
| `notion_synced_at` | 0/328 | 0.0 | Notion page id есть, но sync timestamp не пишется |
| `outreach_status`, `outreach_note` | 0/328 | 0.0 | Reverse sync из Notion не наполнил CRM-поля |
| `score_version` | 0/328 | 0.0 | Score есть, но версия score не записана |

### 3.5. Примеры данных

Примеры последних обновленных компаний:

| Domain | Name | Status | Segment | Что записано |
|---|---|---|---|---|
| `auravision.ai` | Aura Vision | `manual_review` | `generative-ai` | Есть описание: retail analytics from cameras, own CV models; есть Notion page |
| `replika.ai` | Replika | `relevant` | `generative-ai` | Описание: AI companion, own conversational AI/LLM models; есть Notion page |
| `overview.ai` | Overview | `relevant` | `generative-ai` | Описание: industrial CV for quality control |
| `inscribe.ai` | Inscribe | `relevant` | `generative-ai` | Описание: document fraud detection, trained on financial documents |
| `moonshot.cn` | Moonshot AI | `relevant` | `generative-ai` | Источник `huggingface`, есть Notion page |
| `stepfun.com` | StepFun | `qualified` | `generative-ai` | Score 85 / `Hot`, описание про trillion-parameter MoE LLMs |
| `inceptionlabs.ai` | Inception Labs | `qualified` | `generative-ai` | Score 80 / `Warm`, описание про diffusion LLMs |
| `blackforestlabs.ai` | Black Forest Labs | `qualified` | `video-photo-ai` | Score 99 / `Hot`, описание про FLUX models |
| `midjourney.com` | Midjourney | `qualified` | `video-photo-ai` | Score 99 / `Hot`, описание про proprietary diffusion/video models |

Что это говорит:

- последние записи выглядят как результат ручного/agent web research, а не чистого адаптера;
- `description` и `ai_direction` уже содержат ценные qualitative notes;
- score проставлен только на малой части и не является надежной общей метрикой.

### 3.6. Reject reasons

Сводка:

| Reject reason | Count |
|---|---:|
| `<null>` | 217 |
| `no_ai_dev` | 83 |
| `api_wrapper` | 12 |
| `competitor` | 2 |
| Разовые текстовые причины | 14 |

Примеры разовых причин:

- acquired by Autodesk / John Deere;
- third-party model aggregator;
- infrastructure/tooling platform, not model developer;
- government research institution;
- website 503.

Вывод: `reject_reason` сейчас смешивает два типа данных:

1. канонические enum-коды (`no_ai_dev`, `api_wrapper`);
2. свободный текст.

Для чистой структуры лучше разделить это на `reject_code` и `reject_note`, либо стандартизировать все значения.

## 4. `signals`

### 4.1. Что это за данные

`signals` - таблица evidence. Одна строка должна означать: "для этой компании есть конкретный источник/ссылка, подтверждающая релевантный сигнал".

Пример смысла:

```text
normalized_domain = hume.ai
source = websearch
signal_type = foundation_model
evidence_url = https://www.hume.ai/blog/series-b-evi-announcement
signal_date = 2026-06-16
confidence = high
```

Это значит: агент нашел websearch-сигнал, что `hume.ai` связан с foundation model, и хранит URL как доказательство.

### 4.2. Источники сигналов

| Source | Count |
|---|---:|
| `huggingface` | 34 |
| `websearch` | 26 |
| `web` | 14 |

### 4.3. Типы сигналов

| Signal type | Count |
|---|---:|
| `hf_org` | 48 |
| `foundation_model` | 20 |
| `proprietary_ai` | 5 |
| `proprietary_models` | 1 |

Комбинации:

| Source + type | Count |
|---|---:|
| `huggingface` + `hf_org` | 34 |
| `websearch` + `foundation_model` | 20 |
| `web` + `hf_org` | 14 |
| `websearch` + `proprietary_ai` | 5 |
| `websearch` + `proprietary_models` | 1 |

### 4.4. Заполненность полей

| Поле | Filled | % | Интерпретация |
|---|---:|---:|---|
| `normalized_domain` | 74/74 | 100.0 | Сигналы связаны с компаниями |
| `source` | 74/74 | 100.0 | Источник всегда есть |
| `signal_type` | 74/74 | 100.0 | Тип сигнала всегда есть |
| `evidence_url` | 74/74 | 100.0 | URL доказательства всегда есть |
| `signal_date` | 74/74 | 100.0 | Дата всегда есть |
| `confidence` | 74/74 | 100.0 | Confidence всегда есть |
| `raw_data` | 14/74 | 18.9 | Сырые payload почти не сохраняются |
| `parser_version` | 0/74 | 0.0 | Parser version не используется |

### 4.5. Примеры сигналов

| Domain | Source | Type | Evidence |
|---|---|---|---|
| `hume.ai` | `websearch` | `foundation_model` | blog/series-b-evi-announcement |
| `cartesia.ai` | `websearch` | `foundation_model` | cartesia.ai/blog/series-a |
| `pyannote.ai` | `websearch` | `proprietary_ai` | pyannote.ai homepage |
| `fish.audio` | `websearch` | `foundation_model` | GitHub `fish-speech` |
| `deepgram.com` | `websearch` | `foundation_model` | Deepgram Series C press |
| `elevenlabs.io` | `websearch` | `foundation_model` | ElevenLabs Series D blog |

Вывод: `signals` сейчас полезны, но хранят очень тонкий evidence record. Для будущего анализа лучше сохранять `raw_data` и `parser_version`, иначе сложно понять, какой именно контекст агент видел.

## 5. `run_logs`

### 5.1. Что это за данные

`run_logs` - журнал этапов. Он показывает не одну полную сессию, а отдельные checkpoint/stage записи.

### 5.2. Что записано

| Task | Rows | Found sum | Enriched sum | Open rows |
|---|---:|---:|---:|---:|
| `collection_task` | 7 | 644 | 134 | 7 |
| `discover_verify_task/agriculture-ai` | 1 | 7 | 1 | 1 |
| `discover_verify_task/autonomous-vehicles` | 1 | 8 | 2 | 1 |
| `discover_verify_task/generative-ai` | 1 | 7 | 5 | 1 |
| `discover_verify_task/medical-imaging` | 1 | 10 | 1 | 1 |
| `discover_verify_task/robotics-ai` | 1 | 8 | 7 | 1 |
| `discover_verify_task/speech-and-audio` | 1 | 14 | 14 | 1 |
| `discover_verify_task/video-photo-ai` | 1 | 7 | 4 | 1 |
| `pipeline_final_checkpoint` | 1 | 328 | 81 | 1 |
| `relevance_task` | 1 | 30 | 26 | 1 |

Все 16 строк имеют `finished_at = null`.

### 5.3. Примеры логов

Примеры:

- `relevance_task`: found 30, enriched 26, notes: `relevant: 26, not_relevant: 4...`
- `pipeline_final_checkpoint`: found 328, enriched 81, notes: `81 relevant (out of 328 total), 108 not_relevant, 7 manual_review, 131 pending_enrich...`
- `discover_verify_task/robotics-ai`: found 8, enriched 7, notes: `pending_enrich: skild.ai, unitree.com...`
- `collection_task`: found 99, enriched 0, repeated several times.

Вывод:

- `run_logs` реально используется.
- Но `finished_at` не закрывается, поэтому Telegram `/status` будет считать старые записи активными.
- `companies_enriched` используется нестрого: иногда значит "записано", иногда "прошло дальше", иногда "relevant".

## 6. `bot_presets`

### 6.1. Что это за данные

`bot_presets` - сохраненные конфигурации запуска Telegram `/quickrun`.

### 6.2. Что записано

| Name | Default | Config |
|---|---:|---|
| `nightly-full` | true | Все 7 сегментов, `limit_per_segment=5`, `stages=full`, `notion_sync=true` |
| `quick-2seg` | false | `medical-imaging`, `generative-ai`, limit 10, no Notion sync |
| `dry-smoke` | false | `medical-imaging`, stages `discovery,relevance`, `dry_run=true` |

Вывод: Telegram bot storage работает, но RLS на таблице выключен. Если Data API exposed для anon/authenticated, presets можно читать/менять с клиентским ключом.

## 7. Пустые таблицы

### 7.1. `source_links`

Ожидаемое назначение: URL-ручки для глубокого анализа: GitHub org, HF org, Wayback, новости, соцсети.  
Фактическое состояние: 0 строк.

Вывод: Enrichment stage либо не запускался, либо не дошел до записи, либо новый pipeline еще не использует deep enrichment.

### 7.2. `analysis_notes`

Ожидаемое назначение: секционные факты по компании: `company`, `product`, `collaboration`, `financials`, `news`, `audit`.  
Фактическое состояние: 0 строк.

Вывод: Analysis stage не persisted в live DB.

### 7.3. `dossiers`

Ожидаемое назначение: финальное досье компании, `summary_md`, `audit_md`, `sections`, `table_fields`.  
Фактическое состояние: 0 строк.

Вывод: Conclusions stage не persisted в live DB. Notion pages есть у 169 компаний, но досье как отдельная таблица не заполнено.

### 7.4. `contacts` и `contact_companies`

Ожидаемое назначение: ЛПР и связь контактов с компаниями.  
Фактическое состояние: 0 строк.

Вывод: DM enrichment не запущен или не пишет в Supabase. Это согласуется с `companies.dm_enriched_at = 0/328`.

## 8. Реальное использование кодом и агентом

### 8.1. Таблицы, которые реально читают/пишут скрипты

| Таблица | Кто пишет | Кто читает | Live data есть? |
|---|---|---|---|
| `companies` | `supabase_store.py`, prompts, `contacts_store.py --mark-enriched`, `notion_sync.py` | почти все stages, Telegram routines | Да, 328 |
| `signals` | `supabase_store.py`, discovery/verify prompts | scoring, analysis, enrichment, DM HF contacts | Да, 74 |
| `run_logs` | `supabase_store.py`, prompts | bot `/status`, `/last` | Да, 16 |
| `bot_presets` | `bot/presets.py` | bot `/quickrun`, `/presets` | Да, 3 |
| `source_links` | `enrichment.py`, `dossier_store.py` | analysis | Нет |
| `analysis_notes` | `dossier_store.py` | conclusions | Нет |
| `dossiers` | `dossier_store.py` | `notion_sync.py --entity dossiers` | Нет |
| `contacts` | `contacts_store.py`, contact enricher | Notion contacts sync, DM prompts | Нет |
| `contact_companies` | `contacts_store.py` | Notion contacts relation builder | Нет |

### 8.2. Что реально происходило по логам

По live `run_logs` видно, что реально запускались:

- legacy `collection_task`;
- `discover_verify_task` по 7 сегментам;
- `relevance_task`;
- `pipeline_final_checkpoint`.

Не видно записанных stage logs для:

- `scoring_task` как отдельного run_log;
- `enrichment_task`;
- `analysis_task`;
- `conclusions_task`;
- `dm_enrich_task`;
- `monitor_task`.

При этом scoring-поля есть у 31 компании, значит scoring или ручной update выполнялся, но не был нормально залогирован как отдельный этап.

## 9. Что данные говорят о состоянии агента

1. Агент уже умеет находить и классифицировать компании.
   - 328 компаний с доменами, сайтами, сегментами и статусами.

2. Relevance/verify работает заметно лучше, чем scoring/deep stages.
   - 214 descriptions.
   - 111 reject reasons.
   - 328 last_verified.

3. Scoring используется мало.
   - Только 31/328 компаний имеют score.
   - `score_version` пустой у всех.
   - Это подтверждает, что score не является надежной основой для принятия решений.

4. Notion sync частично работал.
   - 169 компаний имеют `notion_page_id`.
   - Но `notion_synced_at`, `outreach_status`, `outreach_note` пустые.
   - Значит forward page creation был, а timestamp/reverse CRM либо не работает, либо не настроен.

5. Deep research контур пока не используется в live DB.
   - `source_links`, `analysis_notes`, `dossiers` пустые.
   - Это главный разрыв между целевой архитектурой и фактическим состоянием.

6. DM/contact контур не используется.
   - `contacts`, `contact_companies` пустые.
   - `dm_enriched_at` пустой у всех компаний.

7. Logs дают полезную историю, но ломают operational status.
   - Все `run_logs.finished_at` пустые.
   - Telegram `/status` будет ошибочно видеть старые runs как активные.

## 10. Рекомендации по чистке данных

### 10.1. Оставить как core

Эти данные реально полезны:

- `companies.domain`
- `companies.name`
- `companies.website`
- `companies.status`
- `companies.icp_segment`
- `companies.description`
- `companies.sources`
- `companies.latest_signal`
- `companies.reject_reason`, но лучше нормализовать
- `companies.notion_page_id`
- `signals.normalized_domain`
- `signals.source`
- `signals.signal_type`
- `signals.evidence_url`
- `signals.signal_date`
- `signals.confidence`
- `run_logs`, но с исправлением lifecycle
- `bot_presets`

### 10.2. Пересмотреть

Эти поля есть, но сейчас слабые или смешанные:

- `score`, `score_bucket`, `ai_direction` - мало покрыты, можно заменить qualitative fit fields.
- `reject_reason` - смешивает enum и свободный текст.
- `latest_signal` - полезно, но заполнено только 40.9%.
- `sources` - полезно, но нужно единое значение source names.
- `notion_synced_at` - либо починить запись, либо убрать.
- `last_signal_date` - почти не используется.

### 10.3. Считать неиспользуемыми до доказательства обратного

Если в ближайшей архитектуре они не нужны, можно пометить deprecated:

- `funding_amount`
- `dm_enriched_at` до запуска DM flow
- `outreach_status`, `outreach_note` до рабочей reverse sync
- `score_version` если score удаляется

### 10.4. Не удалять пустые deep tables сразу

`source_links`, `analysis_notes`, `dossiers` пустые, но они соответствуют хорошей архитектуре agent-legible research. Их лучше не удалять до решения по новой структуре агента. Они могут стать правильной заменой score: вместо числа хранить источники, факты и досье.

## 11. Следующий архитектурный вывод

Если убирать score, текущие данные подсказывают естественную замену:

```text
companies
  -> status + fit_decision + fit_reason
signals
  -> evidence URLs
source_links
  -> источники для исследования
analysis_notes
  -> структурные факты
dossiers
  -> итоговое объяснение, почему компания интересна
```

То есть база должна стать не "скоринговой", а evidence/research системой.
