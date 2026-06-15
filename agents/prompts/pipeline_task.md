# Pipeline Task — Полный запуск pipeline лидогенерации

## Роль
Ты выполняешь роль PipelineAgent. Запускаешь полный pipeline последовательно:
**discovery** → **relevance** → **scoring** → **enrichment** → **analysis** → **conclusions** → **notify**.

Если на каком-то этапе возникает критическая ошибка по одному сегменту — зафиксируй её,
отправь notify об ошибке и продолжай со следующим сегментом.
Не останавливайся полностью из-за одного сегмента.

---

## Шаг 0 — Параметры запуска

Рутина может передать параметры в поле `text`. Формат:
```
segments=seg1,seg2; limit=30; stages=full; dry_run=false; notion_sync=true
```

Если `text` содержит `segments=...` — используй указанные сегменты и параметры.
Если `text` пустой или не содержит `segments=` — читай все активные сегменты из конфига (шаг 1).

Параметры по умолчанию:
- `segments`: все из `config/icp.yaml`
- `limit`: 30
- `stages`: full (все этапы)
- `dry_run`: false
- `notion_sync`: true

---

## Шаг 1 — Прочитать активные сегменты (если не заданы в text)

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

## Шаг 3 — Discovery → Relevance для каждого сегмента

Для каждого сегмента из списка:

1. Прочитай инструкции: `cat agents/prompts/discovery_task.md`
2. Выполни Discovery для сегмента (`segment` = текущий, `limit` = 30) → компании в статусе `discovered`.
3. Прочитай инструкции: `cat agents/prompts/relevance_task.md`
4. Выполни Relevance для тех же `discovered`-компаний → `relevant`/`not_relevant`/`manual_review`.

Если на каком-то сегменте критическая ошибка — зафиксируй, notify об ошибке, продолжай со следующего.

---

## Шаг 4 — Триаж-гейт (scoring)

Прочитай `agents/prompts/scoring_task.md` и выполни: `relevant` → `qualified`/`triaged_out`.

---

## Шаг 5 — Глубокие этапы для `qualified`

Только для компаний в статусе `qualified`, по очереди:

1. `cat agents/prompts/enrichment_task.md` → выполни (сбор ссылок → `sources_gathered`).
2. `cat agents/prompts/analysis_task.md` → выполни (анализ по секциям → `analyzed`).
3. `cat agents/prompts/conclusions_task.md` → выполни (досье → `dossier_ready`).
4. Синхронизация в Notion (детерминированный скрипт, не MCP):
   ```bash
   python scripts/notion_sync.py --entity companies --all
   python scripts/notion_sync.py --entity contacts --all
   python scripts/notion_sync.py --entity dossiers
   ```

Ошибка на одной компании — зафиксируй, notify, продолжай со следующей.

---

## Шаг 6 — Итоговое покрытие

```bash
python scripts/supabase_store.py --coverage
```

---

## Шаг 7 — Финальное уведомление

Подсчитай итоги по всем сегментам и отправь сводку:

```bash
python scripts/notify.py --run-summary '{"task":"pipeline","found":<N>,"qualified":<N>,"dossier_ready":<N>,"errors":<N>}'
```

Замени `<N>` на реальные числа из шагов 3–6.

---

## При критической ошибке всего pipeline

Если процесс упал полностью (не отдельный сегмент):

```bash
python scripts/notify.py --error '{"task":"pipeline","error":"<краткое описание>"}'
```
