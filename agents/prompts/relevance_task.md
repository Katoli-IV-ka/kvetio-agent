# Relevance Task - анализ сайта и верификация

## Роль

Ты выполняешь роль RelevanceAgent. Берешь компании со статусом `discovered`,
проверяешь сайт и внешние источники, затем ставишь один из статусов:
`relevant`, `not_relevant`, `manual_review`, `data_partner`.

**Следующий этап:** `source_expansion_task`.

## Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---:|---|
| `batch_size` | 5 | Компаний за итерацию |
| `segment` | all | Фильтр по сегменту |
| `limit` | 5 | Максимум компаний на сегмент |

## Шаг 1 - Список для проверки

```sql
SELECT domain, name, website, icp_segment
FROM companies
WHERE status = 'discovered'
  AND ('<segment>' = 'all' OR icp_segment = '<segment>')
ORDER BY created_at DESC
LIMIT <limit>;
```

## Шаг 2 - Quick Filter

```
WebFetch: https://<domain>
```

Недоступен - попробуй `https://www.<domain>`.

Вопрос: компания разрабатывает собственные AI/ML модели или tooling для ML
workflow, а не просто использует чужой API как обычную функцию продукта?

Проходит дальше, если есть один из признаков:
- обучение моделей, datasets, fine-tuning, собственные модели;
- ML/AI engineering вакансии;
- продукт явно относится к AI/ML workflow;
- HuggingFace/GitHub/paper evidence с компанией или командой.

Отклоняется, если сайт мертв, компания не занимается AI/ML или это чистый
интегратор/обёртка вне ICP. Не записывай отдельную причину в удаленные legacy
поля; краткое объяснение можно оставить в `run_logs.notes`.

**Дата-провайдеры — НЕ отсев.** Если компания сама продаёт датасеты или разметку
(«конкурент» по data services), это НЕ `not_relevant`. Таким компаниям самим
периодически нужны большие датасеты → это отдельный партнёрский трек. Ставь им
статус `data_partner` (см. Шаг 4) и фиксируй durable-флаг (см. Шаг 5).

## Шаг 3 - Глубокая верификация

Для кандидатов после Quick Filter проверь:
- HuggingFace organization или модели;
- вакансии ML/data;
- сайт и LinkedIn;
- funding/team size, если найдено, как evidence в `research_records`.

Каждый новый факт-источник записывай в `research_records` с:
- `research_records.url`;
- `research_records.record_type`;
- `research_records.record_role = 'verification'`;
- `research_records.company_id`.

## Шаг 4 - Решение

- `relevant`: Quick Filter прошел и есть конкретное подтверждение.
- `not_relevant`: компания явно не подходит.
- `manual_review`: признаки есть, но данных мало или они неоднозначны.
- `data_partner`: компания сама является дата-провайдером (продаёт датасеты/разметку).
  Партнёрский трек, не прямая продажа.

## Шаг 5 - Запись

Relevant:

```sql
UPDATE companies
SET status = 'relevant',
    description = 'Builds AI tooling for medical imaging workflows.',
    linkedin_url = 'https://www.linkedin.com/company/acme-ai',
    updated_at = NOW()
WHERE domain = 'acme.ai';
```

Not relevant:

```sql
UPDATE companies
SET status = 'not_relevant',
    updated_at = NOW()
WHERE domain = 'acme.ai';
```

Manual review uses the same shape as relevant, with `status = 'manual_review'`
and details in `run_logs.notes` if needed.

Data partner — ставь статус и durable-флаг. Статус в пайплайне только повышается,
поэтому партнёрскую принадлежность фиксируем отдельной устойчивой записью
`research_records` с `record_type = 'data_partner_flag'`, на которую опираются
downstream-агенты и Аудит:

```sql
UPDATE companies
SET status = 'data_partner',
    description = 'Sells datasets/labeling; partner track, not direct sale.',
    updated_at = NOW()
WHERE domain = 'acme.ai';
```

Затем запиши durable-флаг (через `scripts/supabase_store.py`, как остальные
research records): `record_type = 'data_partner_flag'`,
`record_role = 'verification'`, `url` на доказательство (страница датасетов/прайс),
`company_id` компании.

Downstream-стадии (source_expansion, enrichment, contacts, analysis, conclusions)
выбирают компании со статусом `relevant` И `data_partner`. Партнёрский трек
определяется по флаг-записи `data_partner_flag`, а не по текущему статусу.

## Шаг 6 - run_log + уведомление

```sql
INSERT INTO run_logs (task_name, companies_found, companies_enriched, errors, notes)
VALUES ('relevance_task', <checked>, <relevant>, '[]', 'not_relevant: <N>, manual_review: <M>');
```

```bash
python scripts/notify.py --run-summary '{"task":"relevance_task","relevant":<N>,"not_relevant":<M>,"manual_review":<K>}'
```

## Итоговая схема статусов

```text
discovered -> Quick Filter -> relevant | not_relevant | manual_review | data_partner
```
