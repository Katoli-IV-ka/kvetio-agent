# Monitor Task — Ежедневный мониторинг сигналов

## Роль
Ты выполняешь роль MonitorAgent. Каждый день проверяешь компании в базе на появление новых сигналов. При обнаружении — обновляешь статус и отправляешь уведомление.

## Запуск
Ежедневно по расписанию. Обрабатывает компании со статусами: `enriched`, `pending_verify`.

## Алгоритм

### Шаг 1 — Список для мониторинга
```sql
-- Компании, которые давно не проверялись
SELECT domain, name, icp_segment, score, score_bucket, last_verified
FROM companies
WHERE status IN ('enriched', 'pending_verify')
  AND (last_verified IS NULL OR last_verified < CURRENT_DATE - INTERVAL '7 days')
ORDER BY score DESC NULLS LAST
LIMIT 30;
```

Приоритет: Hot > Warm > Cold. Не больше 30 компаний за один запуск.

### Шаг 2 — Для каждой компании: проверить новые сигналы

#### 2a. HuggingFace
Через HuggingFace MCP: новые модели или датасеты от этой организации за последние 7 дней?

#### 2b. Вакансии
WebSearch: `site:greenhouse.io OR site:lever.co "<company name>" ML OR annotation OR "training data"` (за последний месяц)

#### 2c. Новости
WebSearch: `"<company name>" funding OR "AI model" OR dataset` (за последние 14 дней)

### Шаг 3 — Оценить сигнал

**Сильный новый сигнал** (требует обновления):
- Новый раунд финансирования
- Новая ML-вакансия с явным упоминанием данных
- Новая модель / датасет на HuggingFace
- Публикация о запуске AI-продукта

**Слабый сигнал** (записать, не менять статус):
- Общая новость о компании без AI-контекста
- Переиндексация старой вакансии

### Шаг 4 — Обновить при сильном сигнале

```sql
UPDATE companies SET
  latest_signal = '<описание нового сигнала>',
  last_signal_date = '<date>',
  status = 'needs_update',   -- если нужен пересмотр скора
  updated_at = NOW()
WHERE domain = '<domain>';
```

Также добавь сигнал в таблицу `signals`.

### Шаг 5 — Повторная верификация устаревших

Если `last_verified` > 30 дней назад И статус `enriched`:
```sql
UPDATE companies SET status = 'pending_verify'
WHERE domain = '<domain>';
```

### Шаг 6 — Уведомления

Если нашёл новый сильный сигнал у Hot-лида:
```bash
python scripts/notify.py --message "📡 Новый сигнал: <company_name> (<domain>) — <описание>"
```

Итоговый отчёт по завершении мониторинга:
```bash
python scripts/notify.py --run-summary '{"task":"monitor_task","found":<новых_сигналов>,"enriched":0,"errors":0}'
```

## Критерии качества
- Не спамить уведомлениями — только действительно новые сильные сигналы
- Не менять скор без полного пересчёта (только флаг `needs_update`)
- Фиксировать дату последней проверки даже если новых сигналов нет
