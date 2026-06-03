# Scoring Task — Скоринг и синхронизация с Notion

## Роль
Ты выполняешь роль ScoringAgent. Берёшь компании со статусом `pending_enrich` из Supabase, считаешь скор (детерминированные правила + LLM-корректировка), переводишь в `enriched` и синхронизируешь в Notion.

## Алгоритм

### Шаг 1 — Получить компании для скоринга
```sql
SELECT *
FROM companies
WHERE status = 'pending_enrich'
ORDER BY created_at DESC
LIMIT 10;
```

### Шаг 2 — Для каждой компании: детерминированный скор

Собери JSON-профиль компании из Supabase (company + signals):
```sql
SELECT * FROM signals WHERE normalized_domain = '<domain>';
```

Передай в scoring engine:
```bash
echo '{
  "domain": "<domain>",
  "name": "<name>",
  "funding_stage": "<stage>",
  "industries": ["<industry>"],
  "evidences": [
    {
      "source": "greenhouse",
      "signal_type": "job_posting",
      "url": "<url>",
      "signal_date": "2026-04-15",
      "confidence": "high",
      "snippet": "<первые 300 символов описания вакансии>"
    }
  ]
}' | python scripts/score.py
```

Получишь JSON с базовым скором (0–85 баллов).

### Шаг 3 — LLM-корректировка (±15 баллов)

Прочитай:
- Описание компании
- Текст вакансий (snippet из сигналов)
- Последние новости (если есть)

Задай себе вопрос: **есть ли признаки, что компания прямо сейчас строит или планирует строить собственный датасет / запускать процесс разметки?**

Сильные положительные сигналы (+10..+15):
- Вакансия явно упоминает "we are building our own dataset"
- Компания недавно анонсировала новую AI-модель в специфичном домене (medical, autonomous)
- Активный поиск Head of Data / Data Infrastructure

Слабые положительные сигналы (+5..+10):
- Вакансии ML-инженеров с упоминанием data pipeline
- HuggingFace-активность за последние 30 дней
- Недавний раунд финансирования (< 6 месяцев)

Отрицательные сигналы (−5..−15):
- Компания использует только готовые модели (OpenAI API, etc.) без обучения
- Pre-product стадия, нет явного AI-продукта
- Описание расплывчатое, нет конкретики по AI

Финальный скор = базовый_скор + LLM_корректировка (не выходит за пределы 0..100).

### Шаг 4 — Запись результата
```sql
UPDATE companies SET
  score = <total>,
  score_bucket = '<Hot|Warm|Cold|Not Relevant>',
  score_version = '<version из scoring.yaml>',
  ai_direction = '<1-3 предложения: почему такой скор>',
  status = 'enriched',
  updated_at = NOW()
WHERE domain = '<domain>';
```

**Маппинг bucket:**
- qualified (≥60) → `Hot`
- manual_review (35–59) → `Warm`
- not_relevant (<35) → `Cold`

> **Shadow mode:** пока threshold_qualified = 999 в scoring.yaml, никто не попадает в Hot автоматически. Все компании получают реальный скор но остаются для ручного просмотра.

### Шаг 5 — Синхронизация в Notion
Для каждой компании со статусом `enriched` создай или обнови страницу в Notion через Notion MCP.

Поля для записи:
- **Company Name** (title): название
- **Website**: https://domain
- **Score**: число
- **Score Bucket**: Hot / Warm / Cold / Not Relevant
- **AI Direction**: текстовое обоснование
- **Funding Stage**: стадия
- **ICP Segment**: сегмент
- **Latest Signal**: последний сигнал
- **Signal Date**: дата сигнала
- **Last Verified**: дата верификации
- **Source**: источники через запятую

После создания страницы — сохрани `notion_page_id` обратно в Supabase:
```sql
UPDATE companies SET notion_page_id = '<page_id>' WHERE domain = '<domain>';
```

### Шаг 6 — Уведомления
Если появились новые Hot-лиды (score ≥ 60):
```bash
python scripts/notify.py --hot-lead '{"name":"<name>","domain":"<domain>","score":<score>,"segment":"<segment>"}'
```

Итоговый отчёт:
```bash
python scripts/notify.py --run-summary '{"task":"scoring_task","found":<N>,"enriched":<M>,"errors":0}'
```
