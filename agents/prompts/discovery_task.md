# Discovery Task — Поиск компаний и резолв сайта (Этап 1)

## Роль
Ты выполняешь роль DiscoveryAgent. За один запуск ты:
1. Находишь компании-кандидаты из включённых источников
2. Резолвишь домен и сайт каждой
3. Записываешь их в Supabase со статусом `discovered` + сигналы с провенансом

Ты НЕ анализируешь сайт и НЕ оцениваешь релевантность — это задача RelevanceAgent.
Предпочитай breadth, а не глубину.

**Следующий этап:** `relevance_task`

---

## Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---|---|
| `segment` | обязательный | ICP-сегмент из `config/icp.yaml` |
| `limit` | 5 | Максимум новых компаний на сегмент после dedupe |
| `sources` | auto | Список через запятую; если не указан — из `config/sources.yaml` |

---

## Шаг 1 — Покрытие до запуска

```bash
python scripts/supabase_store.py --coverage
```

## Шаг 2 — Выбрать источники

Открой `config/sources.yaml`. Выбери источники где `enabled: true` и
`supported_segments` содержит `segment` (или поле отсутствует).

| Источник | Команда |
|---|---|
| `huggingface` | `python scripts/huggingface.py --segment <segment> --max-models 1000` |
| `github` | `python scripts/github.py --segment <segment> --limit <limit> --dry-run` |
| `yc_browser` | `python scripts/yc_browser.py --segment <segment> --limit <limit>` |
| `greenhouse` | `python scripts/greenhouse.py --segment <segment>` |

Порядок: huggingface → github → yc_browser → greenhouse. Сообщи выбор перед запуском.

## Шаг 3 — Запустить источники

Запускай по очереди; каждый скрипт выводит JSON в stdout. 0 компаний — зафиксируй и продолжай.

## Шаг 4 — Объединить, дедуплицировать и применить limit

**4a. В сессии** — по нормализованному домену; объединяй источники в `sources`:
`["huggingface","github","yc_browser"]`.

**4b. Против базы:**
```sql
SELECT domain, status FROM companies WHERE domain = '<normalized_domain>';
```
Уже есть — пропускать.

**4c. Runtime limit** — после dedupe и проверки базы выбери не больше `limit`
кандидатов для текущего `segment`. Если источники вернули больше, приоритизируй
кандидатов с прямым доменом и самым сильным evidence.

## Шаг 5 — Резолв домена/сайта

Надёжность домена зависит от источника:

| Источник | Домен | Действие |
|---|---|---|
| `yc_browser` | Всегда есть | Используй напрямую |
| `huggingface` | Иногда `null` | Если `null` → WebSearch |
| `github` | Иногда `null` | Если `null` → WebSearch |
| `greenhouse` | Из CSV `website` | Если пусто → WebSearch |

**Fallback:** `WebSearch: "<company name>" official website` → первый явный домен компании
(не LinkedIn, не Crunchbase). Не нашёл → `domain_status: not_found`, **не записывай** компанию.

## Шаг 6 — Preview

Выведи первые 10 и дождись подтверждения `[yes/no]` перед записью.

## Шаг 7 — Запись `discovered`

```sql
INSERT INTO companies (
  domain, name, website, status, icp_segment, sources, source_page_url, updated_at
)
VALUES (
  '<domain>', '<name>', 'https://<domain>', 'discovered', '<segment>',
  '<["huggingface","github"]>', '<source_page_url>', NOW()
)
ON CONFLICT (domain) DO NOTHING;
```

## Шаг 8 — Сигналы

```sql
INSERT INTO signals (
  source, signal_type, company_name, normalized_domain,
  evidence_url, signal_date, confidence, raw_data
)
VALUES (
  '<source>', '<hf_org | github_repo | job_posting | yc_company>',
  '<company_name>', '<domain>', '<evidence_url>', '<signal_date>', 'high', '<{json}>'
)
ON CONFLICT (evidence_url) DO NOTHING;
```

## Шаг 9 — run_log + уведомление

```sql
INSERT INTO run_logs (task_name, companies_found, companies_enriched, errors, notes)
VALUES ('discovery_task', <всего>, <записано_discovered>, '[]', 'no_domain: <K>');
```

```bash
python scripts/notify.py --run-summary '{"task":"discovery_task","segment":"<segment>","discovered":<N>,"dedup_skipped":<X>,"no_domain":<K>}'
python scripts/supabase_store.py --coverage
```

## Граничные случаи
- Домен не найден → не записывать, лог `no_domain`.
- Supabase недоступен → прервать с ошибкой.
- `no` на preview → предложить изменить параметры.
