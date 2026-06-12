# Pipeline Task — Полный запуск pipeline лидогенерации

## Роль
Ты выполняешь роль PipelineAgent. Запускаешь полный pipeline последовательно:
**discover_verify** (для всех активных сегментов) → **scoring** → **уведомление**.

Если на каком-то этапе возникает критическая ошибка по одному сегменту — зафиксируй её,
отправь notify об ошибке и продолжай со следующим сегментом.
Не останавливайся полностью из-за одного сегмента.

---

## Шаг 1 — Прочитать активные сегменты

```bash
cat config/icp.yaml
```

Извлеки список `name` из всех сегментов (поле `segments[*].name`).
Активных сегментов 7: medical-imaging, autonomous-vehicles, speech-and-audio,
generative-ai, agriculture-ai, robotics-ai, video-photo-ai.

---

## Шаг 2 — Показать покрытие до старта

```bash
python scripts/supabase_store.py --coverage
```

---

## Шаг 3 — Discover & Verify для каждого сегмента

Для каждого сегмента из списка:

1. Прочитай инструкции: `cat agents/prompts/discover_verify_task.md`
2. Выполни весь алгоритм из этого файла для текущего сегмента с параметрами:
   - `segment` = текущий сегмент
   - `limit` = 30 (по умолчанию)
   - `sources` = auto (из config/sources.yaml)
3. Запиши итог (segment, found, verified, errors) для финального отчёта.

При ошибке сегмента:
```bash
python scripts/notify.py --error '{"task":"discover_verify/<segment>","error":"<краткое описание>"}'
```

---

## Шаг 4 — Scoring

Прочитай инструкции: `cat agents/prompts/scoring_task.md`
Выполни весь алгоритм из этого файла.
Запиши итог (enriched, errors).

---

## Шаг 5 — Финальное уведомление

Подсчитай итоги по всем сегментам и отправь сводку:

```bash
python scripts/notify.py --run-summary '{"task":"pipeline","found":<N>,"enriched":<N>,"errors":<N>}'
```

Замени `<N>` на реальные числа из шагов 3 и 4.

---

## При критической ошибке всего pipeline

Если процесс упал полностью (не отдельный сегмент):

```bash
python scripts/notify.py --error '{"task":"pipeline","error":"<краткое описание>"}'
```
