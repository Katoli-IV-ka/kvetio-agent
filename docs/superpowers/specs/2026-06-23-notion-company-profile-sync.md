# Spec: Company Notion Profile Builder + sync rework — 2026-06-23

## Контекст и цель

Сейчас `sync_forward("companies")` мапит сырую строку `companies` напрямую, типизированные
поля досье живут в мёртвом `dossiers`-маппинге (в `main()` `--entity dossiers` уходит в
`sync_dossiers()` → аппенд в тело страницы, а forward-поля YAML не используются), а
ни одна компания/досье не имеет `notion_page_id` (sync де-факто не доставляет результат).

Цель: одна плоская Notion-карточка компании, собранная из `companies + dossiers +
computed`, через детерминированный **profile builder** в Python. YAML остаётся
декларативным (свойства, типы, направление, источник). Нарратив досье
(`summary_md/section_summaries/audit_md`) по-прежнему рендерится в тело страницы
существующим `notion_render`/`sync_dossiers` — не трогаем.

Решения пользователя зафиксированы: переименования свойств Notion делает вручную;
relation Contacts↔Companies уже настроен в Notion вручную (sync его не создаёт);
отдельные фильтр-поля Funding Stage/Amount не нужны (`Funding Info` — одна строка);
тип `Country` пользователь меняет вручную; типы данных `Potential Data` добавляются в Notion.

## Целевая схема Notion (база компаний)

| Notion property | Type | Источник | direction | source |
|---|---|---|---|---|
| Company Name | title | companies.name | forward | db_column |
| Website | url | companies.website | forward | db_column |
| LinkedIn | url | companies.linkedin_url | forward | db_column |
| ICP Segment | select | companies.icp_segment | forward | db_column |
| Pipeline Status | select | companies.status | forward | db_column |
| AI Summary | rich_text | companies.description | forward | db_column |
| Funding Info | rich_text | computed(dossiers.funding_stage, funding_amount_usd) | forward | computed |
| Company Size | select | companies.company_size | forward | db_column |
| Potential Data | multi_select | computed(icp_segment, status) | forward | computed |
| Country | select | companies.country | forward | db_column |
| Last Info Update | date | computed(max дат) | forward | computed |
| Contacts | relation | настроен вручную | — | НЕ трогаем |

Все поля компании — **forward-only**. У `companies` нет reverse-полей → `sync_reverse`
для компаний остаётся no-op, источник данных не может быть затёрт из Notion.
`Industry` выводится из активного синка (код его не трогает; в Notion можно оставить).

## Изменения БД

Миграция `sql/migrations/029_notion_profile_fields.sql` + правка `sql/schema.sql`:

```sql
ALTER TABLE companies
  ADD COLUMN hq_location text;

ALTER TABLE contacts
  ADD COLUMN source          text,   -- github | apollo | team_page | hf | wellfound | arxiv
  ADD COLUMN outreach_status text NOT NULL DEFAULT 'new'
    CONSTRAINT contacts_outreach_check
    CHECK (outreach_status IN ('new','queued','contacted','replied','bounced','skip'));

-- Кэш переводов (см. раздел «Перевод текстовых полей на русский»).
CREATE TABLE translations (
  source_hash     text NOT NULL,            -- sha256(source_text)
  target_lang     text NOT NULL DEFAULT 'ru',
  source_text     text NOT NULL,
  translated_text text NOT NULL,
  model           text,
  created_at      timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (source_hash, target_lang)
);
```

Примечания:
- `country` и `company_size` наполняет firmographics enrichment из уже сохранённых
  research_records. `hq_location` пока остаётся дополнительной локацией.
- `contacts.source` и `outreach_status` нужны под английские свойства `Source` и
  `Outreach Status`. Поля `tier`/`role_title` из аудита §5.1 — опционально, вне
  объёма этого spec.
- Применять с осторожностью: на проде RLS отключён (см. аудит §7).

## Profile builder

Новый модуль `scripts/notion_profile.py` (или функции в `notion_sync.py`):

```python
def build_company_notion_profile(company: dict, dossier: dict | None,
                                 aggregates: dict, potential_cfg: dict) -> dict:
    """Чистая функция. Возвращает плоский dict для forward-маппинга.
    Содержит и presentation-ключи (по db_column из YAML), и служебные ключи."""
```

Контракт результата (ключи = `db_column` из YAML + служебные):
- `name, website, linkedin_url, icp_segment, status, description, country, company_size` — из company;
- `funding_info` — computed (см. ниже);
- `potential_data` — computed list[str];
- `last_info_update` — computed ISO-date;
- **служебные (обязательно сохранить):** `id`, `domain`, `notion_page_id`,
  `notion_synced_at`. Без них ломается writeback `notion_page_id`
  (`row[cfg["db_key"]]` = domain) и рендер тела (`row["id"]`).

### Computed-правила

`funding_info(stage, amount_usd)`:
- stage + amount → `"Series A · $12M"`
- только stage → `"Seed"`
- только amount → `"$3M"`
- ничего → `None` (поле очищается)
- формат суммы: компактный, $K/$M/$B, округление до 1 знака при необходимости
  (`$12M`, `$3.5M`, `$750K`). Единый форматтер `_format_amount(usd)`.

`potential_data(icp_segment, status, potential_cfg)`:
- база = `potential_cfg["segments"].get(icp_segment, [])`;
- union с `potential_cfg["status_overrides"].get(status, [])`;
- сохранить порядок, убрать дубли; неизвестный сегмент → `[]`.

`last_info_update(company, dossier, aggregates)`:
- `max(company.updated_at, dossier.updated_at,
       aggregates.last_research_created_at, aggregates.last_contact_updated_at)`;
- None-значения игнорируются; результат — ISO-date (`YYYY-MM-DD`).
- Это заменяет «lightweight touch компании» — никаких `UPDATE companies SET
  updated_at=NOW()` в дочерних сторах (нет write-amplification).

### Префетч (без N+1)

`build_company_profiles(company_rows, db, potential_cfg) -> list[dict]`:
1. один `db.fetch("dossiers")` → индекс по `company_id`;
2. агрегаты дат — константное число запросов независимо от числа компаний:
   - `db.fetch_max_dates("research_records", "created_at")` → `{company_id: max}`;
   - `db.fetch_max_dates("contacts", "updated_at")` → `{company_id: max}`;
   (реализовать как выборку минимальных колонок + редукция в Python, по образцу
   существующего `enrich_contact_rows`, стр. 168);
3. на каждую компанию вызвать `build_company_notion_profile(...)` in-memory.

## Изменения sync

1. `notion_mapping.yaml`:
   - `companies`: новый набор полей по таблице выше + на каждом поле маркер
     `source: db_column | dossier | computed`; флаг `profile_builder: true`;
   - `contacts`: переименовать Notion-свойства на английские — `Name`, `Contact Type`,
     `Contact Info`, `Company` (relation, как сейчас `company_page_ids`),
     `Outreach Status` (← `outreach_status`), `Source` (← `source`). Добавить `x_url`
     при необходимости;
   - **удалить** entity `dossiers` из маппинга и убрать использование
     `NOTION_DOSSIERS_DB_ID` (forward-поля досье больше не существуют как отдельная DB).
2. `sync_forward`: если `cfg.get("profile_builder")`, перед циклом маппинга заменить
   `rows` на `build_company_profiles(rows, self.db, potential_cfg)`. Дальше — тот же
   цикл `to_notion_property` по forward-полям; writeback и рендер тела не меняются
   (служебные ключи сохранены билдером).
3. `--entity dossiers` по-прежнему → `sync_dossiers()` (аппенд нарратива в тело). Не меняем.
4. `validate_mapping`: допускать опциональный ключ `source` (значения
   `db_column|dossier|computed`); computed-поле не может иметь `direction: reverse`.
5. `ensure_schema`: без изменений — он читает `cfg["fields"]` (имя+тип), создаст новые
   не-title свойства (Pipeline Status, Funding Info, Company Size, Potential Data, Country,
   Last Info Update). Relation `Contacts` он не трогает (его нет в маппинге).

## Что добавить в Notion (пункт 8)

Опции свойства `Potential Data` (multi_select) — пред-создать или дать синку создать
их при первой записи. Полный набор (union из `config/potential_data.yaml`):

`Medical Data, Images, Annotation, Video, Synthetic Data, Audio, Voice Data,
Transcription, Camera Data, Sensor Data, Geospatial Data, Text, LLM Data,
Human Feedback, Data Supplier` — 15 значений.

`Pipeline Status` (select) опции: `relevant, sources_gathered, analyzed,
dossier_ready, data_partner` (синхронно с `db_status_filter`).

## Перевод текстовых полей на русский (RU localization)

Требование: все свободные текстовые данные переводятся на русский **перед записью в
Notion**. В БД исходный текст остаётся как есть (источник истины), русский — это
кэш для отображения.

### Что переводим (только свободная проза)

- `companies.description` → «AI Summary»;
- `dossiers.summary_md`;
- `dossiers.section_summaries` (значения секций);
- `dossiers.audit_md`;
- (опционально) `contacts.info` → «Contact Info».

### Что НЕ переводим (важно)

- title `Company Name` (бренд/имя оставляем как есть);
- URL/email/phone (`Website`, `LinkedIn`, и т.п.);
- значения select/multi_select — контролируемый словарь: `ICP Segment`,
  `Pipeline Status`, `Company Size`, `Potential Data`, токены стадий в `Funding Info`.
  Живой перевод опций ломает соответствие конфигу (option drift). Если нужны
  русские лейблы для select — это статическая карта в `config/`, а не перевод на лету
  (вне объёма).
- `Funding Info` — структурная строка (`Series A · $12M`), не переводим.

### Дизайн: translate-and-cache (не inline в sync)

Живой вызов перевода внутри `sync_forward` сделал бы синк сетевым и
недетерминированным. Вместо этого — отдельный переводчик с кэшем:

- `scripts/translate.py`:
  - `get_or_translate(store, text, backend, lang="ru") -> str`:
    хэшируем `text` (sha256) → ищем в `translations` по `(hash, lang)`; при попадании
    возвращаем кэш (чисто, без сети); при промахе вызываем `backend`, пишем в кэш,
    возвращаем. Дедуп: одинаковые строки переводятся один раз на всю базу.
  - `backend` (LLM-перевод) инжектируется как gateway — в тестах подменяется
    стабом. Промпт бэкенда: сохранять markdown-разметку, не трогать URL/код,
    переводить только прозу.
- `Translator` gateway инжектируется в `NotionSync` и body-renderer, как `notion`/`db`.
  В проде использует LLM + таблицу `translations`; в тестах — стаб (identity или
  `"RU:"+text`), поэтому тесты синка остаются оффлайн.

### Точки вызова

- `build_company_notion_profile`: `description` переводится перед попаданием в профиль
  (в «AI Summary» уходит русский). Структурные/select-поля не трогаем.
- Тело страницы: и `sync_dossiers()` (стр. 498), и `notion_render.render_and_write_body`
  (вызывается из `sync_forward` при создании страницы, стр. 348–349) — оба пути
  переводят `summary_md` / значения `section_summaries` / `audit_md` через
  `get_or_translate` перед `md_to_blocks`. Важно покрыть ОБА пути, иначе часть страниц
  останется на английском.

### Инвалидация и стоимость

Кэш по хэшу исходного текста: изменился источник → новый хэш → авто-перевод заново;
неизменное не переводится повторно. Язык по умолчанию `ru` (env `KVETIO_NOTION_LANG`).

## Тесты

`tests/test_notion_profile.py` + дополнения к `tests/test_notion_sync.py`:
- `funding_info`: 4 ветки (оба / только stage / только amount / пусто) + форматтер сумм;
- `potential_data`: синтез по сегменту, union с `data_partner`, неизвестный сегмент → `[]`;
- `Country` берётся из `companies.country`;
- `last_info_update` = max по всем источникам, None игнорируются;
- **профиль сохраняет `id/domain/notion_page_id`** (контракт writeback);
- computed-поля исключены из reverse (для companies reverse — no-op; ассерт, что
  computed-колонки не попадают в reverse-набор);
- `ensure_schema` создаёт новые не-title свойства;
- fake forward sync: создаёт страницу с ожидаемыми properties, затем пишет
  `notion_page_id` обратно в БД;
- contacts mapping использует английские имена свойств;
- `build_company_profiles` делает константное число `db.fetch` независимо от числа
  компаний (защита от N+1).

`tests/test_translate.py` + дополнения:
- кэш: промах вызывает backend один раз и пишет в `translations`; повтор той же
  строки backend НЕ вызывает (берётся из кэша);
- изменение исходного текста → новый хэш → новый перевод;
- builder переводит `description`, но НЕ трогает select/url-поля;
- оба body-пути (`sync_dossiers` и `notion_render`) переводят summary/sections/audit;
- контролируемый словарь (`Potential Data`, `Pipeline Status`, `Company Size`) не переводится;
- markdown сохраняется (стаб-бэкенд проверяет, что на вход пришла проза, разметка цела);
- тесты синка оффлайн при инжекте стаб-переводчика (нет сети).

## Порядок выполнения

1. Миграция `029_*` (поля компаний/контактов + таблица `translations`) + правка
   `schema.sql`; применить в Supabase.
2. `config/potential_data.yaml` — готов.
3. Реализовать `notion_profile.py` (builder + префетч) с тестами.
4. Реализовать `translate.py` (`get_or_translate` + `Translator` gateway) с тестами.
5. Обновить `notion_mapping.yaml` (companies/contacts; удалить dossiers-entity).
6. Подключить builder + переводчик в `sync_forward`, `sync_dossiers` и `notion_render`;
   `validate_mapping` под `source`.
7. Прогнать тесты (с инжектом стаб-переводчика — оффлайн).
8. Вручную в Notion: переименовать `Sammary→AI Summary`, русские поля контактов →
   английские; задать тип `Country`; relation уже настроен.
9. `python scripts/notion_sync.py --ensure-schema --entity companies` (создаст
   недостающие свойства + опции Potential Data/Pipeline Status).
10. Разовый прогон локализации: перевести прозу существующих 42 досье (наполнить
    кэш `translations`) перед первым синком.
11. `python scripts/notion_sync.py --entity companies --forward` (или `--all`),
    проверить карточки, русский текст и проставление `notion_page_id`.

## Вне объёма

Наполнение `hq_location`, `contacts.tier/role_title`, починка сбора
контактов/новостей/финансов, включение RLS — отдельные задачи (см. аудит 2026-06-22).
