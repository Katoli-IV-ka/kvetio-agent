# Scoring / Triage Gate Task — Скоринг и гейт (Этап 2.5)

## Роль
Ты выполняешь роль ScoringAgent. Берёшь компании со статусом `relevant`, считаешь
скор (детерминированные правила + LLM-корректировка) и решаешь, достойна ли компания
дорогого глубокого досье (этапы 3–5).

- Hot / Warm → статус `qualified` (идёт в Enrichment → Analysis → Conclusions)
- Cold → статус `triaged_out` (остаётся в базе под мониторингом, досье не строим)

Ты НЕ публикуешь карточки — публикация происходит на этапе 5 (Conclusions).

**Следующий этап:** `enrichment_task` (для `qualified`).

---

## Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---|---|
| `segment` | все | Фильтр по сегменту |
| `limit` | 5 | Максимум компаний на сегмент |

## Шаг 1 — Получить компании для скоринга
```sql
SELECT *
FROM companies
WHERE status = 'relevant'
  AND ('<segment>' = 'all' OR icp_segment = '<segment>')
ORDER BY created_at DESC
LIMIT <limit>;
```

## Шаг 2 — Детерминированный скор

Собери JSON-профиль (company + signals) и передай в движок:
```sql
SELECT * FROM signals WHERE normalized_domain = '<domain>';
```

```bash
echo '{
  "domain": "<domain>",
  "name": "<name>",
  "funding_stage": "<stage>",
  "industries": ["<industry>"],
  "evidences": [
    {"source":"greenhouse","signal_type":"job_posting","url":"<url>","signal_date":"2026-04-15","confidence":"high","snippet":"<300 символов>"}
  ]
}' | python scripts/score.py
```
Получишь JSON с базовым скором (0–85) и engine-bucket (`qualified|manual_review|not_relevant`).

## Шаг 3 — LLM-корректировка (±15)

Прочитай описание, тексты вакансий (snippet), последние новости. Вопрос:
**есть ли признаки, что компания прямо сейчас строит датасет / запускает разметку?**

- Сильные (+10..+15): "we are building our own dataset"; свежий анонс модели в medical/autonomous; поиск Head of Data.
- Слабые (+5..+10): ML-вакансии с data pipeline; HF-активность <30 дней; раунд <6 мес.
- Отрицательные (−5..−15): только готовые модели/API; pre-product; расплывчатое описание.

Финальный скор = базовый + корректировка, в пределах 0..100.

## Шаг 4 — Маппинг bucket (для отображения)
- engine `qualified` (≥ threshold_qualified) → `Hot`
- engine `manual_review` (≥ threshold_manual_review) → `Warm`
- engine `not_relevant` (< threshold_manual_review) → `Cold`

> Shadow mode: `threshold_qualified = 999` в `scoring.yaml` означает, что `Hot` автоматически
> почти не выдаётся — большинство сильных лидов будут `Warm`. Поэтому **гейт ниже опирается
> на порог `threshold_manual_review`, а не на `Hot`.**

## Шаг 5 — Гейт-решение и запись

**Правило гейта:** компания проходит в дорогие этапы, если её финальный скор
`>= threshold_manual_review` (т.е. bucket `Hot` или `Warm`).

**Проходит (`qualified`):**
```sql
UPDATE companies SET
  score = <total>,
  score_bucket = '<Hot|Warm>',
  score_version = '<version из scoring.yaml>',
  ai_direction = '<1-3 предложения: почему такой скор>',
  status = 'qualified',
  updated_at = NOW()
WHERE domain = '<domain>';
```

**Не проходит (`triaged_out`):**
```sql
UPDATE companies SET
  score = <total>,
  score_bucket = 'Cold',
  score_version = '<version из scoring.yaml>',
  ai_direction = '<почему Cold>',
  status = 'triaged_out',
  updated_at = NOW()
WHERE domain = '<domain>';
```

## Шаг 6 — Уведомления и отчёт

Новый Hot-лид (score ≥ threshold_qualified):
```bash
python scripts/notify.py --hot-lead '{"name":"<name>","domain":"<domain>","score":<score>,"segment":"<segment>"}'
```

Итог:
```bash
python scripts/notify.py --run-summary '{"task":"scoring_task","found":<N>,"qualified":<M>,"triaged_out":<K>,"errors":0}'
```
