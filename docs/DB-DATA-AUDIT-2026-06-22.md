# Аудит данных kvetio-agent — 2026-06-22

> Фокус по запросу: **данные и инструменты их обработки**, а не запись/форматирование
> страниц. Цель — понять, хватает ли в системе данных и полей, чтобы стабильно
> получать «желаемый результат» (досье компании + контакты ЛПР в Notion), и где нужны
> новые таблицы/поля.
>
> Источник фактов: реальная БД Supabase (`Kvetio Project`, проект `qcfygtxkohopxhsathkv`),
> `sql/schema.sql`, prompts в `agents/prompts/`, `scripts/*_store.py`,
> `config/notion_mapping.yaml`. Все цифры — снимок на 2026-06-22.

---

## 1. Главный вывод

**Схема БД — НЕ узкое место.** Она богатая, нормализованная и с запасом покрывает
желаемый результат (типизированное досье + provenance + контакты). Проблема не в
структуре, а в трёх вещах уровня данных:

1. **Сбор данных недонаполняет таблицы.** Из 24 объявленных типов сигналов реально
   производится только 6. Контакты ЛПР, новости, найм, гранты, рыночные сигналы — не
   собираются вообще. Поэтому финальные поля досье пустые не потому, что им негде
   лежать, а потому, что данных нет.
2. **Notion sync фактически не доставляет результат.** Ни одна компания и ни одно
   досье не имеют `notion_page_id` (0 из 338 / 0 из 42). То есть «результат», который
   вы видите в Notion, сейчас не порождается этим пайплайном автоматически.
3. **Несколько полей-под-результат нельзя ни отфильтровать, ни спроецировать.**
   Ключевой признак для «поиска аккаунтов менеджеров» — tier/роль ЛПР — по контракту
   хранится текстом в `contacts.info`, а не отдельной колонкой. Часть заполненных
   полей досье не попадает в маппинг Notion.

Дальше — конкретика с цифрами и предлагаемыми изменениями схемы.

---

## 2. Что «желаемый результат» требует на уровне данных

Из `conclusions_task.md`, `dm_enrich_task.md` и `notion_mapping.yaml` следует, что
конечный продукт состоит из двух сущностей:

**Досье компании** (`dossiers`) — типизированные поля + 6 текстовых секций:
funding_stage / funding_amount_usd / funding_date, team_size_estimate,
product_category, ai_use_case, icp_fit, last_news_date, плюс `section_summaries`
(О компании, Продукт, Сотрудничество, Финансы, Новости, Аудит) и `summary_md`.

**Контакты ЛПР** (`contacts`) — для каждой relevant/partner-компании 1–3 лица,
принимающих решение, с tier 1–3, ролью и прямым каналом связи (email/LinkedIn/X).

Чтобы это собрать, на входе нужны заполненные `research_records` (сырые сигналы) и
`analysis_records` (интерпретация). Ниже — насколько они реально наполнены.

---

## 3. Карта наполненности данных (факт)

### 3.1 Воронка компаний (`companies`, всего 338)

| Статус | Кол-во |
|---|---:|
| relevant | 137 |
| not_relevant | 116 |
| dossier_ready | 54 |
| manual_review | 20 |
| discovered | 10 |
| sources_gathered | 1 |

Видна «пробка»: 137 relevant → только 54 dossier_ready. Стадии между ними
(source_expansion / enrichment / contacts / analysis) почти не продвигают компании
(`sources_gathered` = 1, статуса `analyzed` нет вообще).

### 3.2 Идентификационные поля компаний

| Поле | Заполнено | Пусто |
|---|---:|---:|
| `linkedin_url` | 30 / 338 | **308 пусто** |
| `description` (→ Notion «Sammary») | 214 / 338 | **124 пусто** |
| `notion_page_id` | **0 / 338** | 338 |

### 3.3 Сырые сигналы (`research_records`) — используется 6 из 24 типов

| record_type | записей | компаний | ср. confidence |
|---|---:|---:|---:|
| source_link | 138 | 59 | 0.53 |
| hf_org | 48 | 48 | 0.63 |
| funding_announcement | 25 | 5 | **0.20** |
| foundation_model | 20 | 20 | 0.90 |
| proprietary_ai | 5 | 5 | 0.90 |
| proprietary_models | 1 | 1 | 0.90 |

**Не произведено ни одной записи** по 18 типам, включая критичные для результата:
`contact_found`, `news`, `product_update`, `job_posting`, `job_count`, `grant`,
`form_d`, `market_quote`, `arxiv_paper`, `github_repo`, `data_partner_flag`.

### 3.4 Интерпретация (`analysis_records`)

42 компании имеют все 6 секций, но факты «тонкие» (средняя длина JSON ~100–140
символов) и низкоуверенные (confidence ~0.33). Секция `audit` есть только у 20/42.

### 3.5 Финальное досье (`dossiers`, всего 42)

| Поле | Заполнено |
|---|---:|
| team_size_estimate | 41 / 42 |
| icp_fit (известный) | 42 / 42 |
| summary_md | 32 / 42 |
| audit_md | 32 / 42 |
| section_summaries | 30 / 42 |
| funding_stage | 23 / 42 |
| product_category | 23 / 42 |
| ai_use_case | 23 / 42 |
| last_news_date | 13 / 42 |
| **funding_amount_usd** | **2 / 42** |
| **funding_date** | **2 / 42** |
| **extra_facts** | **1 / 42** |

### 3.6 Контакты и provenance

| Метрика | Значение |
|---|---:|
| Всего контактов | **1** |
| Компаний с контактами | **1 / 338** |
| Досье с `dossier_links` (provenance) | **1 / 42** |
| Компаний в Notion | **0** |
| Досье в Notion | **0** |

`run_logs` содержит только `collection_task`, `discover_verify_task/*`,
`relevance_task` — то есть стадии enrichment / contacts / analysis / conclusions /
notion_sync в логах прогонов отсутствуют.

---

## 4. Пробелы данных и инструментов (приоритизировано)

### MUST FIX — без этого «желаемый результат» недостижим

1. **Контакты ЛПР не собираются (1 на всю базу).** Это ядро ценности («поиск
   аккаунтов менеджеров»). Стадия `contacts` и адаптеры (`dm_apollo.py`,
   `dm_github.py`, `dm_team_page.py`, `dm_huggingface_contacts.py`, `dm_wellfound.py`)
   фактически не дают записей. Тип `contact_found` = 0. → Инструментальная проблема
   сбора, плюс см. §5 про схему контактов.
2. **Notion sync не доставляет результат (0 синхронизаций).** Данные есть (192
   компании в syncable-статусах), но `notion_page_id` пуст у всех. Нужно проверить,
   почему `notion_sync.py` не проставляет id (доступ/маппинг/не запускается в пайплайне).
3. **LinkedIn у компаний почти отсутствует (30/338).** Без него невозможно ни
   синхронизировать поле «LinkedIn» в Notion, ни выходить на менеджеров. Нужен
   отдельный шаг резолва компании в LinkedIn URL на enrichment.

### SHOULD FIX — результат собирается, но беден/неполон

4. **Финансовые сигналы слабые.** `funding_announcement` покрывает 5 компаний при
   confidence 0.20; `form_d`, `grant`, `market_quote` — 0 записей. Поэтому
   `funding_amount_usd`/`funding_date` заполнены лишь у 2/42 досье.
5. **Новости не собираются** (`news`/`product_update` = 0), отчего `last_news_date`
   есть только у 13/42, а refresh-ветка NewsAgent не имеет входных данных.
6. **12 «зависших» компаний:** статус `dossier_ready`, но строки в `dossiers` нет
   (54 vs 42). Статус двигается без артефакта — нужно либо дособрать досье, либо
   откатить статус.
7. **Provenance не пишется:** `dossier_links` заполнен у 1/42 досье. Связь
   «вывод → доказательство» де-факто потеряна, хотя таблицы под неё есть.

### CLEANUP — снять «шум» в схеме и маппинге

8. **18 из 24 `record_types` не используются.** Либо реализовать их производителей,
   либо вынести в «план» и убрать из активного словаря, чтобы словарь отражал
   реальность.
9. **`dossiers.extra_facts` практически мёртв** (1/42). Решить: наполнять или убрать.
10. **Маппинг Notion теряет заполненные поля.** В `notion_mapping.yaml` для `dossiers`
    не спроецированы `funding_amount_usd`, `ai_use_case`, `audit_md`,
    `section_summaries`; для `contacts` не спроецирован `x_url`. Данные есть — в Notion
    не доезжают.

---

## 5. Рекомендации по схеме — новые поля и таблицы

> Изменения НЕ применены автоматически. Это предложения; решение и запуск — за вами
> (тем более что на проде у всех таблиц **отключён RLS**, см. §7).

### 5.1 `contacts` — сделать ЛПР запрашиваемыми (MUST для «поиска менеджеров»)

Сейчас tier и роль лежат текстом в `info`, поэтому нельзя отфильтровать «покажи всех
Tier-1 CTO с email». Предлагается вынести в колонки:

```sql
ALTER TABLE contacts
  ADD COLUMN tier        smallint
      CONSTRAINT contacts_tier_check CHECK (tier BETWEEN 1 AND 3),
  ADD COLUMN role_title  text,                 -- «Head of ML», «CTO», ...
  ADD COLUMN seniority   text,                 -- c-level | vp | head | lead | ic
  ADD COLUMN source      text,                 -- github | apollo | team_page | hf | wellfound | arxiv
  ADD COLUMN outreach_status text NOT NULL DEFAULT 'new'
      CONSTRAINT contacts_outreach_check
      CHECK (outreach_status IN ('new','queued','contacted','replied','bounced','skip'));

CREATE INDEX idx_contacts_tier ON contacts (tier);
CREATE INDEX idx_contacts_company_tier ON contacts (company_id, tier);
```

Плюс обновить `dm_enrich_task.md`, чтобы агент писал `tier`/`role_title`/`source`
в колонки, и добавить эти поля в `notion_mapping.yaml` (select/rich_text).

### 5.2 `companies` — фирмографика под карточку и таргетинг (SHOULD)

Сейчас страновые/размерные/финансовые признаки живут только в `dossiers` (и только
для дошедших до конца). Базовая фирмография полезна раньше — на стадии relevance/
enrichment и для Notion-карточки:

```sql
ALTER TABLE companies
  ADD COLUMN country          text,
  ADD COLUMN hq_location       text,
  ADD COLUMN founded_year      smallint,
  ADD COLUMN employee_count    integer,
  ADD COLUMN github_url         text,
  ADD COLUMN hf_url             text,
  ADD COLUMN linkedin_resolved_at timestamptz;  -- когда последний раз искали LinkedIn
```

`linkedin_url` уже есть — добавлять не нужно, нужно его наполнять (см. §4.3).

### 5.3 Новости как первоклассный сигнал (SHOULD)

`news`/`product_update` уже есть в `record_types`, но их никто не пишет, и нет
быстрого «последняя новость по компании». Если NewsAgent остаётся в архитектуре,
явный материализованный признак свежести ускорит refresh-ветку:

```sql
ALTER TABLE companies
  ADD COLUMN last_signal_at date;   -- max(observed_at) по research_records
-- наполнять триггером/джобой; используется и для приоритезации refresh
```

(Альтернатива без новой колонки — вычислять на лету из `research_records`.)

### 5.4 Опционально — таблица аутрича (если нужен CRM-слой)

Заметки на странице про ремаркетинг/«дожать» подразумевают историю касаний. Если это
в роадмапе — провенанс лучше отдельной таблицей, а не полями в `contacts`:

```sql
CREATE TABLE outreach_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  contact_id uuid NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
  channel text NOT NULL,                 -- linkedin | email | x | form
  direction text NOT NULL DEFAULT 'out', -- out | in
  status text,                           -- sent | opened | replied | bounced
  occurred_at timestamptz NOT NULL DEFAULT now(),
  payload jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX idx_outreach_contact ON outreach_events (contact_id);
```

### 5.5 CLEANUP схемы

- Привести активный словарь `record_types` в соответствие реальности: оставить
  6 рабочих + те, под которые есть план/производитель; остальное пометить как
  планируемое отдельной категорией (например `category='planned'`) или удалить.
- Решить судьбу `dossiers.extra_facts` (наполнять либо удалить).
- Добавить в `notion_mapping.yaml` недостающие проекции (`funding_amount_usd`,
  `ai_use_case`, `audit_md`, `contacts.x_url`).

---

## 6. Что менять в инструментах (не схема)

- **Наполнить стадию `contacts`:** довести адаптеры до реальных записей и писать
  `contact_found` в `research_records` для provenance.
- **Включить Notion sync в пайплайн** и разобраться, почему `notion_page_id` не
  проставляется (доступ к БД Notion / id окружения / стадия не запускается).
- **Шаг резолва LinkedIn** компании на enrichment (домен → company LinkedIn URL).
- **Поднять качество финансов и новостей:** активировать `form_d`/`grant`/
  `market_quote` и `news`-сборщики (`news.py`, `greenhouse.py`, `lever.py`),
  поднять confidence по `funding_announcement`.
- **Закрыть «зависшие» 12 компаний** `dossier_ready` без строки `dossiers`.
- **Писать `dossier_links`/`analysis_links` всегда** на стадии conclusions, иначе
  provenance-таблицы бесполезны.

---

## 7. Безопасность (обязательно к сведению)

Supabase advisor: **RLS отключён у всех 9 таблиц** (`companies`, `contacts`,
`dossiers`, `research_records`, `analysis_records`, `analysis_links`,
`dossier_links`, `record_types`, `run_logs`). С anon-ключом любой может читать и
менять все строки. Перед включением RLS нужно добавить политики (иначе доступ
заблокируется полностью), поэтому решение и SQL — за вами:

```sql
ALTER TABLE companies        ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts         ENABLE ROW LEVEL SECURITY;
ALTER TABLE dossiers         ENABLE ROW LEVEL SECURITY;
ALTER TABLE research_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_links   ENABLE ROW LEVEL SECURITY;
ALTER TABLE dossier_links    ENABLE ROW LEVEL SECURITY;
ALTER TABLE record_types     ENABLE ROW LEVEL SECURITY;
ALTER TABLE run_logs         ENABLE ROW LEVEL SECURITY;
-- + соответствующие CREATE POLICY ...
```

---

## 8. Итог в одну строку

Данных на выходе мало не из-за нехватки места в схеме, а из-за того, что стадии
сбора (контакты, новости, финансы, LinkedIn) почти не пишут, а Notion-sync не
доставляет уже собранное. Схему достаточно точечно дополнить (tier/роль у контактов,
фирмография у компаний, опционально аутрич), но 80% эффекта даст наполнение
существующих таблиц и починка sync.
