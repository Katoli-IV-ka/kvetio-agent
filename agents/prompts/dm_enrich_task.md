# DM Enrich Task — Поиск ЛПР для компании

## Роль

Ты выполняешь роль DMEnrichAgent. Для одной компании в Phase 1 запускаешь все
DM-векторы, классифицируешь контакты и сохраняешь итог в Supabase + Notion.

Следующий этап pipeline после `scoring_task`.

---

## Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---|---|
| `domain` | обязательный | Домен компании, например `radai.com` |
| `batch` | false | Batch-режим зарезервирован для Phase 2 |
| `limit` | 10 | Компаний за batch-запуск в Phase 2 |
| `segment` | все | Фильтр по ICP-сегменту для Phase 2 |

---

## ФАЗА 1: Контекст компании

### Шаг 1 — Получить данные компании

```sql
SELECT name, website, icp_segment, score, score_bucket, sources,
       notion_page_id, dm_enriched_at, status
FROM companies
WHERE domain = '<domain>';
```

Если компания не найдена или `status != 'enriched'`, останови выполнение и
выведи предупреждение.

Если `notion_page_id IS NULL`, останови выполнение: DM enrichment запускается
только после Notion sync.

Если `dm_enriched_at IS NOT NULL`, компания уже была обогащена. Спроси
оператора, продолжать ли повторный прогон.

### Шаг 2 — Проверить существующие контакты

```sql
SELECT full_name, dm_priority, email, source_vector
FROM contacts
WHERE company_domain = '<domain>'
ORDER BY dm_priority;
```

Если контакты уже есть, покажи список и спроси: добавить ещё или пропустить.

---

## ФАЗА 2: Запуск fetcher-скриптов

### Шаг 3 — Запустить все векторы

Запускай команды по очереди из директории `kvetio-agent`. Сохрани stdout каждого
скрипта в отдельную переменную. Если скрипт вернул `[]`, пустую строку или
ошибку, зафиксируй это и продолжай.

```bash
python scripts/dm_github.py --domain <domain>
python scripts/dm_apollo.py --domain <domain>
python scripts/dm_wellfound.py --domain <domain>
python scripts/dm_team_page.py --domain <domain>
python scripts/dm_huggingface_contacts.py --domain <domain>
```

Для каждого вектора выведи краткий итог:

- `dm_github`: N контактов, M с email
- `dm_apollo`: N контактов
- `dm_wellfound`: N контактов
- `dm_team_page`: found/not found, source URL если есть
- `dm_huggingface_contacts`: N контактов

---

## ФАЗА 3: LLM-обработка

### Шаг 4 — Парсинг team page text

Прочитай stdout `dm_team_page.py`, если он не пустой.

Извлеки сотрудников с техническими, ML, data, research или leadership ролями.
Игнорируй marketing, sales, HR, legal, design, finance.

Для каждого найденного человека верни:

```json
{"full_name": "...", "title": "...", "linkedin_url": "... или null"}
```

Если текст содержит секцию `[LINKEDIN_URLS]`, используй эти URL при маппинге.

### Шаг 5 — Классификация ролей из bio

Для каждого контакта из `dm_github` и `dm_huggingface_contacts` с непустым `bio`:

1. Проверь аффилиацию: bio должен упоминать целевую компанию по имени или домену.
   Если bio явно указывает другую текущую компанию, пропусти контакт.
2. Извлеки `title_normalized` из bio.
   - `Research Scientist at Rad.AI` -> `Research Scientist`
   - `Head of ML Platform | radai.com` -> `Head of ML`
   - `Software Engineer` без подтверждения компании -> `dm_priority=3`, `confidence=low`

### Шаг 6 — Merge и дедупликация

Объедини контакты из всех источников по `lower(full_name)`.

При конфликте:

- email: `verified > guessed > unknown`
- linkedin_url: любой непустой
- twitter/github: любой непустой
- dm_priority: меньшее число побеждает
- source_vector: первый источник, где нашли контакт
- raw_payload: сохрани исходные данные в объекте по именам источников

### Шаг 7 — Присвоить dm_priority

| title_normalized содержит | dm_priority |
|---|---|
| head of data, vp data, director of data, ml platform lead, head of ai, vp ml, vp of ai | 1 |
| cto, co-founder, chief technology officer, research lead, head of research, vp engineering | 2 |
| research scientist, ml engineer, data scientist, computer vision engineer, speech engineer | 3 |
| неопределённая роль | 3 |

Для компаний с командой <= 20 человек: CTO и Co-founder повышаются до P1.

---

## ФАЗА 4: Сохранение

### Шаг 8 — Записать в Supabase

Для каждого итогового контакта:

```bash
echo '{
  "company_domain": "<domain>",
  "full_name": "<name>",
  "first_name": "<first>",
  "last_name": "<last>",
  "title": "<raw_title>",
  "title_normalized": "<normalized>",
  "dm_priority": 1,
  "email": "<email or null>",
  "email_status": "<verified|guessed|unknown>",
  "email_source": "<github_commit|apollo|team_page|...>",
  "linkedin_url": "<url or null>",
  "twitter_handle": "<handle or null>",
  "github_username": "<username or null>",
  "source_vector": "<github|apollo|wellfound|team_page|huggingface>",
  "source_url": "<url>",
  "confidence": "<high|medium|low>",
  "raw_payload": {}
}' | python scripts/contacts_store.py --upsert
```

### Шаг 9 — Создать записи в Notion «Сотрудники»

Используй Notion MCP. Database ID: `336fa05a-c45f-802a-8654-000b1c0ea8b3`.

Для каждого контакта создай или обнови страницу:

```json
{
  "Name": "<full_name>",
  "Компания": [{"url": "<notion_page_id компании>"}],
  "Должность": "<title>",
  "Приоритет": "P1 | P2 | P3",
  "Email": "<email>",
  "Email статус": "Verified | Guessed | Unknown",
  "LinkedIn": "<linkedin_url>",
  "Twitter": "<twitter_handle>",
  "GitHub": "<github_username>",
  "Источник": "<source_vector>",
  "Аутрич": "Не писали"
}
```

Если контакт уже есть в Notion по имени + компании, обнови его, не создавай дубль.

### Шаг 10 — Пометить компанию как обогащённую

Даже если найдено 0 контактов, проставь `dm_enriched_at`, чтобы не повторять
пустой прогон без ручного сброса:

```bash
python scripts/contacts_store.py --mark-enriched <domain>
```

---

## ФАЗА 5: Итоговый отчёт

Выведи:

```text
<company_name> (<domain>) — DM Enrichment завершён

Контакты найдены:
  P1: N
  P2: N
  P3: N

По каналам:
  Email verified: N
  Email guessed: N
  LinkedIn URL: N
  GitHub: N
  Twitter: N

По источникам: github=N, apollo=N, wellfound=N, team_page=N, huggingface=N

Notion: N записей создано / M обновлено
```

Если P1 контактов = 0 для Hot-лида, добавь предупреждение:
`Hot лид без P1 контакта — рекомендуется ручной поиск через LinkedIn Sales Navigator`.

---

## Batch-режим (Phase 2+)

Если запущен с `--batch`:

```sql
SELECT domain, name, score, score_bucket
FROM companies
WHERE status = 'enriched'
  AND notion_page_id IS NOT NULL
  AND dm_enriched_at IS NULL
ORDER BY score DESC
LIMIT <limit>;
```

Обработай каждую компанию по алгоритму выше. Между компаниями делай паузу
2 секунды. При ошибке по одной компании залогируй и продолжи следующую.
