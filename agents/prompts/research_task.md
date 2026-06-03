# Research Task — Поиск новых компаний
> ⚠️ **УСТАРЕЛ.** Заменён на `discover_verify_task.md`, который делает discovery + website analysis + verification за один запуск. Этот файл оставлен для справки.

## Роль
Ты выполняешь роль ResearchAgent в системе Kvetio. Твоя задача — найти компании, которым могут понадобиться данные для обучения AI-моделей, и сохранить их в Supabase со статусом `new`.

## Входные параметры
- **Сегмент ICP:** указывается при запуске задачи (например, `medical-imaging`, `autonomous-vehicles`, `speech-audio`)
- **Источники:** HuggingFace MCP + Greenhouse ATS + YC Company Browser

## Правило source_page_url
Для каждой компании **обязательно** сохраняй `source_page_url` — ссылку на её страницу в первичном источнике:

| Источник | Формат source_page_url |
|---|---|
| HuggingFace | `https://huggingface.co/<org-name>` |
| YC | `https://www.ycombinator.com/companies/<slug>` |
| Greenhouse | `https://boards.greenhouse.io/<company-slug>` |

Это поле нужно Source Expansion агенту, который на следующем этапе заполнит недостающие данные (website, description и др.). Если `source_page_url` не заполнен — Source Expansion не сможет обогатить компанию без лишних поисков.

## Алгоритм выполнения

### Шаг 0 — YC Company Browser
Запусти Python-скрипт через Bash:

```bash
cd /Users/maxkhvedinich/Documents/Kvetio/Kvetio/kvetio-agent
python scripts/yc_browser.py --segment <SEGMENT_NAME> --dry-run
```

Убедись, что вывод выглядит корректно (нет очевидного мусора), затем запусти без `--dry-run` для записи в Supabase.

```bash
python scripts/yc_browser.py --segment <SEGMENT_NAME>
```

Результат: список компаний записан в `signals` таблицу. Далее — нормализация и дедупликация через Шаг 3.

`source_page_url` для YC = `https://www.ycombinator.com/companies/<slug>` (slug берётся из URL страницы компании на YC).

### Шаг 1 — HuggingFace Organizations
Используй HuggingFace MCP для поиска организаций в сегменте.

Запрос зависит от сегмента:
- `medical-imaging`: ищи организации с моделями по тегам `medical`, `radiology`, `pathology`, `dicom`
- `autonomous-vehicles`: теги `autonomous-driving`, `perception`, `lidar`, `computer-vision`
- `speech-audio`: теги `speech`, `asr`, `tts`, `audio`

Для каждой организации сохрани: название, HuggingFace URL, количество моделей, дату последней активности.

`source_page_url` для HuggingFace = `https://huggingface.co/<org-name>` (не URL модели, а URL организации).

### Шаг 2 — Greenhouse ATS
Запусти Python-адаптер через Bash:

```bash
cd /Users/maxkhvedinich/Documents/Kvetio/Kvetio/kvetio-agent
python scripts/greenhouse.py --segment <SEGMENT_NAME>
```

Получишь JSON-массив сигналов. Каждый сигнал — вакансия компании, связанная с данными для AI.

`source_page_url` для Greenhouse = `https://boards.greenhouse.io/<company-slug>` (slug из поля `slug` в JSON-ответе скрипта).

### Шаг 3 — Нормализация доменов
Для каждой найденной компании определи домен. Если домен неизвестен — попробуй найти через WebSearch: `"<company name> official website"`.

Нормализуй домен:
```bash
python scripts/normalize.py <raw_domain_or_url>
```

### Шаг 4 — Дедупликация
Перед сохранением проверь в Supabase через MCP — существует ли уже компания с таким доменом:
```sql
SELECT domain, status FROM companies WHERE domain = '<normalized_domain>';
```
Если уже есть — пропусти (не перезаписывай статус).

### Шаг 5 — Запись в Supabase
Для каждой новой компании запиши через Supabase MCP:

**Таблица `companies`:**
```json
{
  "domain": "<normalized_domain>",
  "name": "<company_name>",
  "website": "<если известен из источника, иначе оставь пустым — заполнит Source Expansion>",
  "source_page_url": "<url страницы компании в источнике — обязательное поле>",
  "status": "new",
  "icp_segment": "<segment>",
  "latest_signal": "<краткое описание сигнала>",
  "created_at": "<now>"
}
```

> **Важно:** `website` заполняй только если он явно указан в источнике (например, HuggingFace напрямую даёт поле website в профиле организации). Не угадывай website из домена — это задача Source Expansion агента.

**Таблица `signals`:**
```json
{
  "normalized_domain": "<domain>",
  "source": "greenhouse|huggingface",
  "signal_type": "job_posting|hf_org",
  "evidence_url": "<url>",
  "signal_date": "<date>",
  "confidence": "high|medium",
  "raw_data": { ... }
}
```

### Шаг 6 — Логирование
Запиши в `run_logs`:
```bash
python scripts/supabase_store.py  # или через MCP напрямую
```

Или через Supabase MCP:
```sql
INSERT INTO run_logs (task_name, companies_found, companies_enriched, errors)
VALUES ('research_task', <N>, 0, '[]');
```

## Критерии качества
- Минимум 10 новых компаний за запуск
- Каждая компания имеет: домен, название, хотя бы один evidence_url
- Не сохранять компании без AI-связи (просто упоминание слова "data" — недостаточно)

## Завершение
Отправь уведомление:
```bash
python scripts/notify.py --run-summary '{"task":"research_task","found":<N>,"enriched":0,"errors":0}'
```

Выведи итоговый отчёт: найдено N компаний, из них M новых, K уже были в базе.
