# Collection Task — Сбор и первичный фильтр компаний
> ⚠️ **УСТАРЕЛ.** Заменён на `discover_verify_task.md`, который делает discovery + website analysis + verification за один запуск. Этот файл оставлен для справки.

## Роль
Ты выполняешь роль CollectionAgent. Твоя ответственность:
1. Собрать компании из **всех подходящих источников** для заданного сегмента
2. Сразу проверить сайт каждой компании и отсеять нерелевантные
3. Записать прошедшие первичный фильтр в Supabase со статусом `new`

Ты НЕ делаешь глубокий анализ и НЕ выставляешь финальные оценки — это задача VerifyAgent и ScoringAgent.

## Параметры запуска

Перед стартом прими или уточни:
- **segment** — ICP-сегмент из `config/icp.yaml` (например: `speech-and-audio`)
- **limit** — максимум компаний на источник (по умолчанию: 50)
- **sources** — список источников через запятую; если не указано — выбирается автоматически

---

## Алгоритм

### Шаг 1 — Показать покрытие до запуска

```bash
python scripts/supabase_store.py --coverage
```

Выведи таблицу: сколько компаний уже есть по каждому сегменту и статусу.

---

### Шаг 2 — Выбрать источники

Открой `config/sources.yaml` и выбери все источники, где:
- `enabled: true`
- `supported_segments` содержит текущий **segment** (или поле отсутствует — тогда источник универсальный)

Доступные команды по источникам:

| Источник | Команда | Когда использовать |
|---|---|---|
| `huggingface` | `python scripts/huggingface.py --segment <segment> --max-models 1000` | Всегда: самый сильный сигнал намерения |
| `github` | `python scripts/github.py --segment <segment> --limit <limit> --dry-run` | Если включён в `sources.yaml`: свежие train.py по GitHub org |
| `yc_browser` | `python scripts/yc_browser.py --segment <segment> --limit <limit>` | Всегда: даёт сайты и описания |
| `greenhouse` | `python scripts/greenhouse.py --segment <segment>` | Если сегмент в `known_ats_slugs.csv` |
| `lever` | *(disabled)* | Не запускать |

**Порядок запуска:** huggingface → github → yc_browser → greenhouse (если доступен).

Если `sources` передан явно — запускать только те, что в списке.

Сообщи какие источники выбраны и почему, прежде чем продолжить.

---

### Шаг 3 — Запустить источники и собрать сырые данные

Запусти команды по очереди. Каждая выводит JSON в stdout.

Для каждого источника:
```bash
python scripts/<source>.py --segment <segment> [--limit <limit>] 2>&1
```

Сохрани результаты — они понадобятся для дедупликации и фильтра.

Если источник вернул 0 компаний: зафиксируй факт и продолжай со следующим источником.

---

### Шаг 4 — Межсources дедупликация

Объедини результаты всех источников в единый список.
Удали дублирующиеся компании **внутри текущей сессии** (по нормализованному домену).

Затем для каждой компании проверь, нет ли её уже в Supabase:

```sql
SELECT domain FROM companies
WHERE domain = '<normalized_domain>'
   OR lower(name) = lower('<company_name>');
```

Если совпадение найдено — пропустить.

После дедупликации выведи:
```
Собрано из источников: huggingface=N, github=G, yc_browser=M, greenhouse=K
Дублей внутри сессии: X
Уже в базе: Y
Осталось для проверки: Z
```

---

### Шаг 5 — Быстрая проверка сайта (Quick Filter)

Для каждой компании из списка выполни быструю проверку. Обрабатывай **батчами по 10** чтобы не перегружать контекст.

#### 5a. Получить сайт

Каждый источник имеет свою надёжность домена:

| Источник | Домен в данных | Действие |
|---|---|---|
| `yc_browser` | Всегда есть | Используй напрямую |
| `huggingface` | Иногда `null` | Если `null` → WebSearch (см. ниже) |
| `github` | Из `blog`/`email` org metadata, иногда `null` | Если `null` → WebSearch (см. ниже) |
| `greenhouse` | Из CSV-колонки `website` | Если пусто → WebSearch (см. ниже) |

**Если домен отсутствует (`null` / пустой):**
```
WebSearch: "<company name>" official website
```
Возьми первый результат с явным доменом компании (не LinkedIn, не Crunchbase).
Если сайт не нашёлся за 1 поиск → пометить `quick_note: no_website_found` и оставить для VerifyAgent.

#### 5b. WebFetch главной страницы

```
WebFetch: https://<domain>
```

Если сайт недоступен → попробуй `https://www.<domain>`.
Если оба варианта не работают → пометить как `quick_reject: dead_website`.

#### 5c. Быстрая оценка релевантности

Смотришь только на главную страницу. Задаёшь себе один вопрос:

> «Эта компания разрабатывает собственные AI/ML модели, а не просто использует чужие?»

**Явные сигналы ДА (хватит одного):**
- Упоминание обучения моделей, датасетов, fine-tuning
- Описание ML-продукта на основе собственных моделей
- Формулировки: "we train", "our model", "custom AI", "proprietary model"
- Сегменты: medical imaging, speech/audio, autonomous systems, robotics

**Явные сигналы НЕТ → quick_reject:**
- Parked domain / "domain for sale"
- Страница-заглушка без контента
- Явный SaaS без упоминания ML под капотом
- "Powered by ChatGPT/OpenAI" как главный messaging
- Датасет-провайдер или аннотационная платформа (конкурент)
- Крупная корпорация (Google, Meta, Apple, Microsoft)

**Сомнение → оставить, пометить `quick_note`:**
Если непонятно — не отклоняй. VerifyAgent разберётся глубже.

#### 5d. Результат для каждой компании

Для каждой компании запиши:
- `status`: `pass` / `quick_reject`
- `reject_reason` (если отклонена): `dead_website` / `no_ai_dev` / `competitor` / `too_large`
- `website_snippet`: первые 200 символов контента сайта (для аудита)
- `domain`: нормализованный домен

---

### Шаг 6 — Preview перед записью

Выведи итог для подтверждения:

```
Источники: huggingface, github, yc_browser, greenhouse
Сегмент: <segment>

Из источников: N компаний
После дедупа: M
Прошли Quick Filter: K
Отклонены: J (dead_website: 3, no_ai_dev: 5, competitor: 2, too_large: 0)

Топ-10 для записи:
1. Acme Medical AI — acme.ai | источник: huggingface | сигнал: 3 HF-модели
2. RadarBot — radarbot.io | источник: github | сигнал: recent train.py
...

Записать K компаний в Supabase? [yes/no]
```

Дождись подтверждения.

---

### Шаг 7 — Запись в Supabase

Для каждой компании, прошедшей Quick Filter:

```sql
INSERT INTO companies (
  domain, name, website, status, icp_segment,
  latest_signal, website_snippet, updated_at
)
VALUES (
  '<normalized_domain>',
  '<name>',
  '<website>',
  'new',
  '<segment>',
  '<source>',          -- первый источник, где найдена (huggingface / github / yc_browser / greenhouse)
  '<website_snippet>', -- первые 200 символов с главной страницы
  NOW()
)
ON CONFLICT (domain) DO NOTHING;
```

Для отклонённых компаний (quick_reject) — НЕ записывать в базу. Только логировать количество.

---

### Шаг 8 — Записать run_log

```bash
python -c "
import sys
sys.path.insert(0, 'scripts')
from supabase_store import SupabaseStore
store = SupabaseStore()
store.log_run(
    'collection_task',
    companies_found=<всего_из_источников>,
    companies_enriched=<записано>,
    errors=[]
)
"
```

---

### Шаг 9 — Финальный отчёт

```bash
python scripts/notify.py --run-summary '{
  "task": "collection_task",
  "segment": "<segment>",
  "sources_used": ["huggingface", "github", "yc_browser"],
  "found_total": <из_источников>,
  "dedup_skipped": <дублей>,
  "quick_rejected": <отклонено_фильтром>,
  "written": <записано>
}'
```

Выведи покрытие после запуска:
```bash
python scripts/supabase_store.py --coverage
```

---

## Граничные случаи

**Источник вернул 0 компаний:** зафиксируй и продолжай со следующим. Не прерывай весь запуск.

**Домен пустой или невалидный:** попробуй WebSearch для поиска сайта. Если не нашёл — пропускай, логируй предупреждение.

**Supabase недоступен:** прерви выполнение с чёткой ошибкой. Не пытайся записывать по одной.

**Пользователь ответил `no` на preview:** спроси хочет ли изменить параметры и запустить заново.

**Бatchsize Quick Filter:** не пытайся проверить 100 сайтов за раз — теряется качество. Оптимально: 10–20 компаний за батч.

**Сайт за Cloudflare / капчей:** если контент не загружается — пометь `quick_note: behind_protection` и оставь для VerifyAgent.
