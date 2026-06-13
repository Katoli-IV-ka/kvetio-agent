# Analysis Audit Task — Под-агент комплексного аудита (Этап 4)

## Роль
Ты — под-агент аудита. Запускаешься ПОСЛЕ пяти секционных под-агентов. Синтезируешь
их ноты в критическую реалистичную оценку компании — не по самозаявлениям, а по
реальному положению дел, динамике и рынку.

## Шаг 1 — Загрузить ноты секций
```bash
python scripts/dossier_store.py --list-analysis-notes <domain>
```
Должны быть ноты: company, product, collaboration, financials, news.

## Шаг 2 — Сформировать аудит
Оцени:
- Насколько заявленные цели/процессы соответствуют фактам и динамике.
- Положение на рынке и реалистичный прогноз развития.
- **Вывод для нас:** есть ли потребность в датасетах/разметке; насколько вероятна
  продажа data services; точки контакта (ЛПР); угол привлекательного оффера.

Отмечай уровень уверенности и пробелы в данных.

## Шаг 3 — Записать ноту аудита
```bash
echo '{
  "company_domain":"<domain>",
  "section":"audit",
  "facts":{
    "claims_vs_reality":"<...>",
    "market_position":"<...>",
    "forecast":"<...>",
    "sales_opportunity":"<...>",
    "contact_angle":"<...>"
  },
  "sources":[ {"url":"<url>","note":"<...>"} ],
  "confidence":"<high|medium|low>",
  "model":"claude",
  "version":"v1"
}' | python scripts/dossier_store.py --upsert-analysis-note
```
