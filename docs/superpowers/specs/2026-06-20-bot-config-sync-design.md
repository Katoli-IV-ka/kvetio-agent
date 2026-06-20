# Design: Bot Config Sync + Help Command

**Date:** 2026-06-20
**Status:** Approved
**Scope:** `kvetio-agent/bot/`

---

## Проблема

Бот и агент разошлись в конфигурации pipeline stages. Это блокирует корректный запуск.

### Расхождение stages

| Источник | Список stages |
|---|---|
| **Агент** (`agents/prompts/pipeline_main_task.md`) | `discovery, relevance, **source_expansion**, enrichment, analysis, conclusions` |
| **Бот** (`bot/config.py`, `dialog.py`, `scenarios.py`) | `discovery, relevance, **scoring**, enrichment, analysis, conclusions` |

Стадия `scoring` отсутствует в агенте. Если пользователь выбирает её в /run-визарде, агент
получает неизвестный stage и завершается критической ошибкой.

### Прочие проблемы

- `_start_text()` в `gateway.py` ссылается на команду `/fire` — такой команды не существует.
  Правильно: параметры собирает `/run`, запуск уходит через fire() внутри бота.
- `/help` существует, но не описывает 4 сценария `/ask` и не даёт понимания, что делает каждая команда.
- `/settings` — заглушка без полезного содержимого.

---

## Что меняем

### 1. Переименование стадии: `scoring` → `source_expansion`

Везде в боте заменяем имя стадии, чтобы совпало с агентом.

**bot/config.py:**
- `VALID_STAGES`: `"scoring"` → `"source_expansion"`
- `ENRICH_DEFAULT_STAGES`: `"scoring"` → `"source_expansion"`
- `ENRICH_VALID_STAGES` (производная от `ENRICH_DEFAULT_STAGES`) — обновляется автоматически

**bot/dialog.py:**
- `ALL_STAGES`: `"scoring"` → `"source_expansion"`
- `ENRICH_STAGES`: обновляется автоматически из `ENRICH_DEFAULT_STAGES`
- Описание в `_stages_step()`: `"scoring — рассчитать приоритет"` → `"source_expansion — найти источники и сигналы"`
- Описание в `_enrich_stages_step()`: аналогично

**bot/scenarios.py:**
- `icp_segment.param_descriptions["stages"]`: убрать `scoring`, добавить `source_expansion`
- `enrich_existing.param_descriptions["stages"]`: аналогично
- `enrich_existing.defaults["stages"]`: `"scoring"` → `"source_expansion"`

### 2. Исправление `_start_text()` в gateway.py

Убрать упоминание несуществующей команды `/fire`.

**До:**
```
Бот сам не выполняет pipeline. Он собирает параметры и отправляет запуск
в Claude Code Routine через /fire.
```

**После:**
```
Бот сам не выполняет pipeline. Он собирает параметры через /run или /ask
и запускает Claude Code Routine. После завершения рутина присылает сводку в Telegram.
```

### 3. Улучшение `_help_text()` в gateway.py

Добавить:
- краткое описание каждой команды (что делает, какие параметры)
- блок «Сценарии /ask» с описанием 4 режимов (icp_segment, single_company, startup_research, enrich_existing)
- убрать `/settings` из списка (заглушка без смысла) или заменить полезным описанием

### 4. Убрать `/settings` как бесполезную заглушку

Команда `/settings` отвечает «параметры выбираются через /run» — это не помогает пользователю.
Вариант: удалить обработчик или превратить в alias для `/help`.

---

## Порядок изменений

1. `bot/config.py` — переименовать в VALID_STAGES и ENRICH_DEFAULT_STAGES
2. `bot/dialog.py` — переименовать в ALL_STAGES + обновить тексты описаний
3. `bot/scenarios.py` — переименовать в описаниях и defaults
4. `bot/gateway.py` — исправить _start_text(), улучшить _help_text(), превратить /settings в alias /help

---

## Тесты

После изменений прогнать:
```bash
python -m pytest tests/test_bot_dialog.py tests/test_bot_gateway_ask.py -v
```

Ожидаем: все тесты проходят. Если тесты содержат `"scoring"` — обновить их тоже.

---

## Не входит в скоуп

- Изменение логики wizard-шагов
- Добавление новых команд
- Изменение схемы БД
- setMyCommands (регистрация команд в меню Telegram)
