# NLP Intent Agent для Kvetio Bot

**Дата:** 2026-06-18  
**Статус:** Approved  
**Затронутые файлы:** `bot/`, `docs/`

---

## Контекст

Бот сейчас предлагает только один способ запуска — 5-шаговый wizard через inline-кнопки (`/run`). Wizard жёстко привязан к одному сценарию: ICP-поиск по сегментам. Новые сценарии (анализ конкретной компании, исследование стартапа) там нет места.

Задача: добавить NLP-вход через `/ask`, который:
1. Принимает свободный текст от пользователя
2. Разбирает намерение через Google Gemini Flash (бесплатный API)
3. Уточняет недостающие параметры через диалог в Telegram
4. Формирует точные параметры запуска и дёргает Claude Code Routine один раз

`/run`-wizard остаётся без изменений.

---

## Архитектура

```
/ask <text>
      │
      ▼
bot/gateway.py          ← новый handler /ask + plain-text follow-up
      │
      ▼
bot/session.py          ← in-memory dict[chat_id → BotSession]
      │
      ▼
bot/intent_agent.py     ← Gemini Flash API (structured JSON output)
      │
      ▼
ParsedIntent            ← {mode, params, missing_fields, clarification_question}
      │
   missing? ──yes──► бот задаёт один вопрос → follow-up → повтор (макс. 3 хода)
      │no
      ▼
confirmation message    ← [🚀 Запустить] [✏️ Уточнить] [❌ Отмена]
      │
      ▼
bot/routine.py          ← config_to_text(RunConfig) → fire(text)
      │
      ▼
Claude Code Routine     ← вызывается ровно один раз с готовыми параметрами
```

**Ключевой принцип:** Gemini Flash — только для разбора намерения (дёшево, быстро). Claude Code Routine — только для выполнения (один вызов, точные параметры).

---

## Новые файлы

### `bot/scenarios.py` — реестр сценариев

Центральная точка расширения. Добавить новый сценарий = добавить запись в `SCENARIOS`. Система промптов, валидация и confirmation-сообщение генерируются из этого реестра автоматически.

```python
@dataclass
class ScenarioSpec:
    name: str                    # человекочитаемое название
    description: str             # описание для Gemini-промпта
    required_params: list[str]   # без них нельзя запустить
    optional_params: list[str]   # берутся из defaults если не указаны
    param_descriptions: dict[str, str]  # описания для Gemini
    defaults: dict[str, Any]     # значения по умолчанию

SCENARIOS: dict[str, ScenarioSpec] = {
    "icp_segment": ScenarioSpec(
        name="ICP Pipeline",
        description="Поиск и квалификация компаний по ICP-сегментам",
        required_params=["segments"],
        optional_params=["limit_per_segment", "stages", "dry_run", "notion_sync"],
        param_descriptions={
            "segments": "список сегментов из: medical-imaging, autonomous-vehicles, "
                        "speech-and-audio, generative-ai, agriculture-ai, robotics-ai, video-photo-ai",
            "limit_per_segment": "максимум компаний на сегмент (1–200), по умолчанию 5",
            "stages": "'full' или подмножество: discovery, relevance, scoring, enrichment, analysis, conclusions",
            "dry_run": "true/false, по умолчанию false",
            "notion_sync": "true/false, по умолчанию true",
        },
        defaults={"limit_per_segment": 5, "stages": "full", "dry_run": False, "notion_sync": True},
    ),
    "single_company": ScenarioSpec(
        name="Анализ компании",
        description="Полный анализ одной конкретной компании",
        required_params=["company_name"],
        optional_params=["company_url", "stages", "notion_sync"],
        param_descriptions={
            "company_name": "название компании",
            "company_url": "URL сайта компании (опционально)",
            "stages": "'full' или подмножество стадий",
            "notion_sync": "true/false, по умолчанию true",
        },
        defaults={"stages": "full", "notion_sync": True},
    ),
    "startup_research": ScenarioSpec(
        name="Исследование стартапа",
        description="Исследование стартапа на основе информации от пользователя",
        required_params=["description"],
        optional_params=["company_name", "company_url", "focus_areas", "notion_sync"],
        param_descriptions={
            "description": "что делает стартап, раунд, размер команды — всё что знает пользователь",
            "company_name": "название компании (если известно)",
            "company_url": "URL сайта (если известен)",
            "focus_areas": "конкретные направления для исследования (опционально)",
            "notion_sync": "true/false, по умолчанию true",
        },
        defaults={"notion_sync": True},
    ),
    # Будущие сценарии добавляются здесь:
    # "employees":     ScenarioSpec(...),
    # "review":        ScenarioSpec(...),
    # "group_research": ScenarioSpec(...),
}
```

### `bot/intent_agent.py` — клиент Gemini Flash

Один HTTP-запрос к Gemini Flash с системным промптом, сгенерированным из `SCENARIOS`. Возвращает структурированный `ParsedIntent`.

```python
@dataclass
class ParsedIntent:
    mode: str                           # ключ из SCENARIOS
    params: dict[str, Any]              # собранные параметры
    missing_fields: list[str]           # чего не хватает для запуска
    clarification_question: str | None  # вопрос пользователю, если missing
    confidence: float                   # 0.0–1.0

async def parse_intent(messages: list[dict]) -> ParsedIntent:
    """
    messages — история диалога в формате Gemini:
      [{"role": "user", "parts": [{"text": "..."}]}, ...]
    
    Системный промпт содержит:
    - описание всех сценариев из SCENARIOS
    - инструкцию вернуть JSON в формате ParsedIntent
    - список допустимых значений для каждого параметра
    
    Возвращает ParsedIntent. При ошибке парсинга — fallback с
    clarification_question="Не понял запрос. Уточни, что хочешь запустить?"
    """
```

**Конфигурация (env vars):**
- `GEMINI_API_KEY` — API-ключ Google AI Studio
- `GEMINI_MODEL` — по умолчанию `gemini-2.0-flash-lite`

**Системный промпт** строится динамически из `SCENARIOS` при старте приложения, не хардкодится. Это означает, что добавление нового сценария в `scenarios.py` автоматически обучает Gemini его распознавать.

### `bot/session.py` — in-memory сессии

```python
@dataclass
class BotSession:
    chat_id: str
    messages: list[dict]              # история для Gemini (накапливается)
    parsed_intent: ParsedIntent | None
    state: Literal["clarifying", "confirming"]
    clarification_count: int          # счётчик уточнений, макс. 3
    created_at: datetime

class SessionStore:
    """
    dict[str, BotSession] по chat_id.
    Lazy cleanup: при каждом обращении удаляет сессии старше 30 минут.
    Потокобезопасность: asyncio.Lock на dict.
    """
    
    async def get(self, chat_id: str) -> BotSession | None: ...
    async def set(self, session: BotSession) -> None: ...
    async def delete(self, chat_id: str) -> None: ...
```

---

## Изменения в существующих файлах

### `bot/config.py`

Добавляется `RunMode` и поле `run_mode` в `RunConfig`. Существующая валидация не ломается — для `icp_segment` все проверки остаются как есть.

```python
RunMode = Literal["icp_segment", "single_company", "startup_research"]

@dataclass
class RunConfig:
    run_mode: RunMode = "icp_segment"   # новое поле
    # ... существующие поля без изменений ...
    
    # Новые поля для новых режимов:
    company_name: str = ""
    company_url: str = ""
    startup_description: str = ""
    focus_areas: list[str] = field(default_factory=list)

    def validate(self) -> None:
        if self.run_mode == "icp_segment":
            # существующая валидация без изменений
            ...
        elif self.run_mode == "single_company":
            if not self.company_name:
                raise ValueError("company_name is required for single_company mode")
        elif self.run_mode == "startup_research":
            if not self.startup_description:
                raise ValueError("description is required for startup_research mode")
```

### `bot/routine.py`

`config_to_text()` ветвится на `run_mode`:

```python
def config_to_text(cfg: RunConfig) -> str:
    if cfg.run_mode == "icp_segment":
        # существующий формат + префикс mode=
        return (
            f"mode=icp_segment; "
            f"segments={','.join(cfg.segments)}; "
            f"limit={cfg.limit_per_segment}; "
            f"stages={stages}; "
            f"dry_run={'true' if cfg.dry_run else 'false'}; "
            f"notion_sync={'true' if cfg.notion_sync else 'false'}"
        )
    elif cfg.run_mode == "single_company":
        parts = [f"mode=single_company", f"company={cfg.company_name}"]
        if cfg.company_url:
            parts.append(f"company_url={cfg.company_url}")
        parts += [f"stages={stages}", f"notion_sync={'true' if cfg.notion_sync else 'false'}"]
        return "; ".join(parts)
    elif cfg.run_mode == "startup_research":
        parts = [f"mode=startup_research", f"description={cfg.startup_description}"]
        if cfg.company_name:
            parts.append(f"company={cfg.company_name}")
        if cfg.focus_areas:
            parts.append(f"focus_areas={','.join(cfg.focus_areas)}")
        parts.append(f"notion_sync={'true' if cfg.notion_sync else 'false'}")
        return "; ".join(parts)
```

### `bot/gateway.py`

Добавляется:

1. **`/ask` command handler** — создаёт сессию, вызывает `parse_intent`, начинает диалог.

2. **Plain-text handler** — если у пользователя есть активная сессия (`state == "clarifying"`), добавляет сообщение в историю и снова вызывает `parse_intent`. Если сессии нет — игнорирует (поведение как сейчас).

3. **Callback handler для `/ask`-подтверждения** — отдельный prefix `"a1:"` для кнопок confirm/edit/cancel, чтобы не конфликтовать с `"r1:"` от wizard'а.

```python
# Новые обработчики в _handle_message:
elif command == "/ask":
    prompt = " ".join(args)  # текст после /ask (может быть пустым)
    await _handle_ask_command(chat_id, prompt, tg)

# Новый обработчик plain text (не-команды):
async def _handle_message(...):
    if not text.startswith("/"):
        session = await session_store.get(chat_id)
        if session and session.state == "clarifying":
            await _handle_ask_followup(chat_id, text, session, tg)
        return
```

---

## UX: диалог в Telegram

### Сценарий 1 — однозначный запрос
```
User:  /ask Проанализируй компанию OpenAI
Bot:   🔍 Понял запрос

       Сценарий: Анализ компании
       Компания: OpenAI

       [🚀 Запустить]  [✏️ Уточнить]  [❌ Отмена]
```

### Сценарий 2 — нужно уточнение
```
User:  /ask Исследуй стартап
Bot:   Расскажи о стартапе — название, чем занимаются,
       размер команды или раунд (если знаешь)?

User:  Synthesia, делают AI-видео из текста, Series C
Bot:   🔍 Понял запрос

       Сценарий: Исследование стартапа
       Компания: Synthesia
       Описание: AI-видео из текста, Series C

       [🚀 Запустить]  [✏️ Уточнить]  [❌ Отмена]
```

### Сценарий 3 — ICP через NLP
```
User:  /ask Найди медицинские AI компании, лимит 10
Bot:   🔍 Понял запрос

       Сценарий: ICP Pipeline
       Сегменты: medical-imaging
       Лимит: 10
       Стадии: полный pipeline

       [🚀 Запустить]  [✏️ Уточнить]  [❌ Отмена]
```

### Правила диалога
- Максимум **3 хода уточнений** — после третьего бот подтверждает то, что есть
- **Кнопка "Уточнить"** → бот спрашивает "Что хочешь изменить?" → Gemini перепарсивает с полной историей
- **Сессия живёт 30 минут** — потом удаляется, `/ask` нужно начать заново
- `/ask` без текста → бот сразу спрашивает "Что хочешь исследовать?"

---

## Расширяемость

Добавить новый сценарий в будущем (например, `employees`, `review`, `group_research`):

1. Добавить `ScenarioSpec` в `SCENARIOS` в `bot/scenarios.py`
2. Добавить поля в `RunConfig` в `bot/config.py` (если нужны новые параметры)
3. Добавить ветку в `config_to_text()` в `bot/routine.py`
4. Написать соответствующую ветку в CLAUDE.md рутины

Системный промпт Gemini и валидация обновляются автоматически.

---

## Gemini Flash: настройка

### 1. Получить API-ключ
1. Открыть [Google AI Studio](https://aistudio.google.com)
2. Войти под Google-аккаунтом
3. **Get API key → Create API key** — выбрать существующий проект или создать новый
4. Скопировать ключ

### 2. Добавить в окружение бота
```bash
# .env (локально)
GEMINI_API_KEY=AIzaSy...
GEMINI_MODEL=gemini-2.0-flash-lite   # или gemini-2.0-flash

# Production (Vercel / Railway / Fly.io — куда деплоится бот)
# Добавить GEMINI_API_KEY в env vars через UI деплой-платформы
```

### 3. Добавить зависимость
```bash
pip install google-genai
# или через pyproject.toml:
# google-genai>=1.0.0
```

### 4. Бесплатные лимиты Gemini Flash Lite (актуально на 2026-06)
- `gemini-2.0-flash-lite`: 1500 req/day, 1M tokens/min — достаточно для intent-разбора
- `gemini-2.0-flash`: 1500 req/day, 4M tokens/min — если нужна чуть большая точность

---

## Файловая структура после изменений

```
bot/
  __init__.py
  config.py          ← изменён: RunMode, новые поля RunConfig
  dialog.py          ← без изменений (wizard /run)
  gateway.py         ← изменён: /ask handler, plain-text handler
  intent_agent.py    ← НОВЫЙ: Gemini Flash клиент
  routine.py         ← изменён: config_to_text поддерживает run_mode
  scenarios.py       ← НОВЫЙ: реестр сценариев
  session.py         ← НОВЫЙ: in-memory сессии
  set_webhook.py     ← без изменений
```

---

## Ограничения и решения

| Ограничение | Решение |
|---|---|
| In-memory сессии теряются при рестарте | Приемлемо: пользователь просто начинает `/ask` заново. При необходимости — мигрировать в Supabase позже. |
| Gemini может неверно распознать сегмент | Список допустимых значений явно указан в промпте; fallback — Gemini возвращает `missing_fields=["segments"]` и просит уточнить. |
| Callback_data для confirm/edit конфликтует с wizard | Prefix `"a1:"` для `/ask`-кнопок, `"r1:"` остаётся для wizard. |
| Рутина пока не умеет `single_company` / `startup_research` | Бот уже может формировать правильный текст; реализация в рутине — отдельный этап. |
