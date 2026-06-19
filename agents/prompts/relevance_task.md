# Relevance Task - анализ сайта и верификация

## Роль

Ты выполняешь роль RelevanceAgent. Берешь компании со статусом `discovered`,
проверяешь сайт и внешние источники, затем ставишь один из статусов:
`relevant`, `not_relevant`, `manual_review`.

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

Отклоняется, если сайт мертв, компания не занимается AI/ML, это прямой
конкурент data services или корпорация вне ICP. Не записывай отдельную причину
в удаленные legacy поля; объяснение клади в `site_note`.

## Шаг 3 - Глубокая верификация

Для кандидатов после Quick Filter проверь:
- HuggingFace organization или модели;
- вакансии ML/data;
- сайт и LinkedIn;
- funding/team size, если найдено.

Каждый новый факт-источник записывай в `signals` с:
- `signals.url`;
- `signals.signal_type` prefixed with `verification_`;
- `signals.company_id`.

## Шаг 4 - Решение

- `relevant`: Quick Filter прошел и есть конкретное подтверждение.
- `not_relevant`: компания явно не подходит.
- `manual_review`: признаки есть, но данных мало или они неоднозначны.

## Шаг 5 - Запись

Relevant:

```sql
UPDATE companies
SET status = 'relevant',
    description = 'Builds AI tooling for medical imaging workflows.',
    linkedin_url = 'https://www.linkedin.com/company/acme-ai',
    team_size = '11-50',
    funding_stage = 'seed',
    funding_date = '2026-01-15',
    website_snippet = 'AI platform for radiology workflow automation.',
    site_note = 'Relevant because the company builds AI workflow software for medical imaging.',
    last_verified = CURRENT_DATE,
    updated_at = NOW()
WHERE domain = 'acme.ai';
```

Not relevant:

```sql
UPDATE companies
SET status = 'not_relevant',
    last_verified = CURRENT_DATE,
    updated_at = NOW()
WHERE domain = 'acme.ai';
```

Manual review uses the same shape as relevant, with `status = 'manual_review'`
and a concise `site_note`.

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
discovered -> Quick Filter -> relevant | not_relevant | manual_review
```
