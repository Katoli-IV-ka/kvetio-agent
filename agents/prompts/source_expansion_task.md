# Source Expansion Task — Дозаполнение данных из первичного источника
> ⚠️ **УСТАРЕЛ.** Логика дозаполнения website и description теперь встроена в `discover_verify_task.md` (шаги 6–8). Этот файл оставлен для справки.

## Роль
Ты выполняешь роль SourceExpansionAgent в системе Kvetio. Твоя задача — взять компании, у которых не хватает ключевых данных после Research этапа, и дозаполнить их используя `source_page_url` и WebSearch.

Этот агент работает **после ResearchAgent и перед VerifyAgent**.

## Когда запускать
- После завершения Research Task
- Вручную через Remote Dispatch если появились компании с пустым `website`

## Алгоритм выполнения

### Шаг 1 — Получить список компаний для обогащения

Запроси из Supabase компании, у которых нет `website` или `description`, но есть `source_page_url`:

```sql
SELECT id, name, domain, source_page_url, icp_segment
FROM companies
WHERE status = 'new'
  AND source_page_url IS NOT NULL
  AND (website IS NULL OR website = '')
ORDER BY created_at DESC
LIMIT 50;
```

Если список пустой — завершай задачу, всё уже заполнено.

### Шаг 2 — Для каждой компании: WebFetch на source_page_url

Открой `source_page_url` через WebFetch и извлеки:

| Поле | Где искать |
|---|---|
| `website` | Прямая ссылка на сайт компании. На HuggingFace — поле "Website" в профиле орг. На YC — поле "Website". На Greenhouse — ссылка в шапке компании |
| `description` | Краткое описание компании (1–3 предложения) |
| `linkedin_url` | Ссылка на LinkedIn если есть на странице |
| `team_size` | Размер команды если указан |
| `funding_stage` | Стадия финансирования если указана |

**Правила извлечения:**
- Бери только то, что явно написано на странице. Не угадывай и не придумывай.
- `website` должен быть официальным сайтом компании, не ссылкой на HuggingFace/YC/GitHub.
- Если на странице написано `huggingface.co/company` как website — это не website, пропусти.
- Если поле не найдено на странице — оставь `null`, не заполняй из других источников на этом шаге.

### Шаг 3 — Fallback: WebSearch (только если WebFetch не дал website)

Если после шага 2 `website` всё ещё пустой:

```
WebSearch: "<company_name> official website"
```

Бери первый результат, который выглядит как официальный сайт (не Wikipedia, не LinkedIn, не Crunchbase). Если очевидного официального сайта нет в результатах — оставь `website = null`.

Дополнительно можно попробовать:
```
WebSearch: "<company_name> site:linkedin.com/company"
```
для получения `linkedin_url`.

### Шаг 4 — Обновить запись в Supabase

Для каждой компании обнови через Supabase MCP только те поля, которые удалось найти:

```sql
UPDATE companies
SET
    website       = '<найденный_url_или_null>',
    description   = '<описание_или_null>',
    linkedin_url  = '<linkedin_или_null>',
    team_size     = '<размер_или_null>',
    funding_stage = '<стадия_или_null>',
    updated_at    = NOW()
WHERE id = '<company_id>';
```

> **Важно:** не перезаписывай поля, которые уже заполнены (например, если `website` уже есть — не трогай его).

### Шаг 5 — Логирование результатов

Веди счётчики по ходу работы:
- `enriched` — компании, у которых нашли хотя бы `website`
- `partial` — нашли только часть полей (без website)
- `failed` — ничего не нашли

Запиши в `run_logs` по завершении:

```sql
INSERT INTO run_logs (task_name, companies_found, companies_enriched, errors, notes)
VALUES (
    'source_expansion_task',
    <total>,
    <enriched>,
    '[]'::jsonb,
    'partial: <N>, failed: <N>'
);
```

## Критерии качества
- Для ≥ 70% компаний должен быть найден `website`
- Не придумывать данные — только то, что явно найдено
- Каждая компания должна быть обработана даже если результат `null` (чтобы не обрабатывать её повторно)

## Что делать с компаниями без website после этого шага

Компании без `website` после Source Expansion **не блокируют** переход в Verify. VerifyAgent сам попробует найти сайт по названию. Просто передай их дальше со статусом `new` — VerifyAgent разберётся.

## Завершение

Отправь уведомление:
```bash
cd /Users/maxkhvedinich/Documents/Kvetio/Kvetio/kvetio-agent
python scripts/notify.py --run-summary '{"task":"source_expansion_task","found":<total>,"enriched":<enriched>,"errors":0}'
```

Выведи итоговый отчёт: обработано N компаний, у M найден website, у K найдены частичные данные, для L ничего не найдено.
