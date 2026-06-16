# Relevance Task — Анализ сайта и верификация (Этап 2)

## Роль
Ты выполняешь роль RelevanceAgent. Берёшь компании со статусом `discovered`,
анализируешь их сайт и проверяешь, реальна ли компания, жива ли и осмысленно ли
работает с AI в нашем сегменте.

Прошедшие → `relevant`. Отклонённые → `not_relevant`. Неоднозначные → `manual_review`.

**Следующий этап:** `scoring_task` (триаж-гейт)

---

## Параметры запуска

| Параметр | По умолчанию | Описание |
|---|---|---|
| `batch_size` | 5 | Компаний за итерацию |
| `segment` | все | Фильтр по сегменту (опционально) |
| `limit` | 5 | Максимум компаний на сегмент |

## Шаг 1 — Список для проверки

```sql
SELECT domain, name, website, icp_segment, sources, source_page_url
FROM companies
WHERE status = 'discovered'
  AND ('<segment>' = 'all' OR icp_segment = '<segment>')
ORDER BY created_at DESC
LIMIT <limit>;
```

Обрабатывай батчами по `batch_size`. После каждого батча — промежуточный итог.

## Шаг 2 — Quick Filter

```
WebFetch: https://<domain>
```
Недоступен → попробуй `https://www.<domain>`.

Вопрос: «Компания разрабатывает собственные AI/ML модели, а не просто использует чужие?»

**Пропускаем дальше** если есть сигнал: обучение моделей/датасеты/fine-tuning;
"we train / our model / custom AI"; продукт в ML-домене; ML/AI-вакансии.

**Сразу отклоняем (`quick_reject`):**
| Причина | `reject_reason` |
|---|---|
| Parked / заглушка | `dead_website` |
| SaaS без ML | `no_ai_dev` |
| "Powered by ChatGPT" как главный messaging | `api_wrapper` |
| Датасет-провайдер / аннотатор | `competitor` |
| Крупная корпорация | `too_large` |

За Cloudflare/капчей — не блокирует: `site_note: behind_protection`, идём на шаг 3.

## Шаг 3 — Глубокая верификация (только прошедшие Quick Filter)

**3a. HuggingFace** (MCP `hf_hub_query`/`hub_repo_search`): организация по имени/домену →
кол-во моделей, pipeline_tags, дата последней активности.

**3b. Вакансии:** `WebSearch: "<company name>" jobs "ML engineer" OR "data annotation" OR "training data"` → один релевантный posting (title + URL).

**3c. Фактура:**
| Поле | Метод |
|---|---|
| `description` | Сайт / HF профиль |
| `linkedin_url` | `WebSearch: site:linkedin.com/company "<name>"` |
| `team_size` | LinkedIn / сайт |
| `funding_stage`, `funding_date` | `WebSearch: "<name>" funding round OR raised` |

Заполняй что нашёл, не обязательно всё.

## Шаг 4 — Решение

**→ `relevant`**: прошёл Quick Filter И есть ≥1 конкретное доказательство из шага 3.
**→ `not_relevant`**: `quick_reject`, либо прошёл Quick Filter, но подтверждений нет.
**→ `manual_review`**: признаки есть, но данных мало (stealth/закрытый сайт) или неоднозначно.

## Шаг 5 — Запись

**Прошедшие:**
```sql
UPDATE companies SET
  status = 'relevant',
  description = '<description>',
  linkedin_url = '<linkedin_url или NULL>',
  team_size = '<team_size или NULL>',
  funding_stage = '<funding_stage или NULL>',
  funding_date = '<funding_date или NULL>',
  website_snippet = '<первые ~200 символов>',
  site_note = '<site_note или NULL>',
  last_verified = CURRENT_DATE,
  updated_at = NOW()
WHERE domain = '<domain>';
```

**Отклонённые:**
```sql
UPDATE companies SET
  status = 'not_relevant', reject_reason = '<reject_reason>',
  last_verified = CURRENT_DATE, updated_at = NOW()
WHERE domain = '<domain>';
```

**На ручной просмотр:** то же что `relevant`, но `status = 'manual_review'` и `site_note` объясняет причину.

## Шаг 6 — Сигналы верификации

Для `relevant` запиши новые сигналы (HF-модели, вакансии) в `signals`
(`ON CONFLICT (evidence_url) DO NOTHING`).

## Шаг 7 — run_log + уведомление

```sql
INSERT INTO run_logs (task_name, companies_found, companies_enriched, errors, notes)
VALUES ('relevance_task', <проверено>, <relevant>, '[]', 'not_relevant: <N>, manual_review: <M>');
```

```bash
python scripts/notify.py --run-summary '{"task":"relevance_task","relevant":<N>,"not_relevant":<M>,"manual_review":<K>}'
```

## Итоговая схема статусов
```
discovered → [Quick Filter] ── quick_reject ──→ not_relevant
                  └─ pass → [Глубокая верификация]
                              ├─ confirmed → relevant → [scoring_task]
                              ├─ not_confirmed → not_relevant
                              └─ unclear → manual_review
```
