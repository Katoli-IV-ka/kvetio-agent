# Design: Notion Page Renderer

**Дата:** 2026-06-22
**Статус:** Approved
**Scope:** `kvetio-agent/scripts/notion_render.py` + правки `scripts/notion_sync.py`

---

## Проблема

Текущий `notion_sync.py` синхронизирует только properties Notion-страниц (Company Name, Website, LinkedIn и т.д.). Тело страницы остаётся пустым — нет ни структуры, ни форматированного досье. Эталонный формат страницы предполагает богатое тело: callout-блоки с таблицами, списками, page-mention на контакты. Этот контент нужно рендерить из данных, уже существующих в Supabase, а не синхронизировать напрямую.

---

## Что строим

Новый файл `scripts/notion_render.py` — шаблонизатор Notion-блоков. Принимает структурированные данные из Supabase, возвращает список Notion block payloads готовых к отправке через `blocks.children.append`.

`notion_sync.py` дополняется одним новым вызовом: при первом создании страницы (`create_page`) сразу рендерится и записывается тело.

---

## Структура страницы (эталон)

```
heading_1          "Dossier"
quote              Дата составления / Составил / Статус
divider
callout            О компании
callout            Продукт [основной]
callout            Продукт [второстепенный]   ← если есть второй продукт
divider
callout            Сотрудничество
divider
callout            Финансы
empty_block
divider
callout            Новости
divider
callout            Комплексный анализ и оценка
callout            Вывод для нас
heading_4          дисклеймер (серый курсив)
empty_block
```

---

## Формат блоков

### Общий паттерн «поле-значение»

Каждое поле — один `paragraph`-блок, содержащий **два сегмента rich_text**:

```python
# Сегмент 1 — лейбл
{"type": "text", "text": {"content": "Метка:"}, "annotations": {
    "bold": True, "code": True, "color": "yellow"
}}
# Сегмент 2 — значение
{"type": "text", "text": {"content": " Значение поля"}}
```

Если значения нет — блок целиком пропускается (не ставится «—» или пустая строка).

### Структура callout-блока

```python
{
    "object": "block",
    "type": "callout",
    "callout": {
        "rich_text": [],   # пусто — заголовок внутри children
        "icon": {"type": "emoji", "emoji": EMOJI},
        "color": "default",
        "children": [
            heading_2_block("Название секции"),
            divider_block(),
            # ... поля секции
        ]
    }
}
```

**Все callout-блоки без исключения** начинаются с `heading_2` + `divider`. Отсутствие дивайдера в «О компании» в эталоне — ошибка оформления.

### Поля с переносами строк (Руководство, ЛПР)

Если поле содержит список элементов (например, несколько людей) — всё в **одном paragraph-блоке** через `hard_break` (`"\n"`), не отдельные bullet-блоки:

```python
rich_text = [
    label_segment("Руководство:"),
]
for contact in leaders:
    rich_text += [
        {"type": "text", "text": {"content": "\n- "}, "annotations": {}},
        {"type": "text", "text": {"content": f"{contact['role']} — {contact['name']}"}, "annotations": {"bold": True}},
    ]
    if contact.get("notion_page_id"):
        rich_text.append({
            "type": "mention",
            "mention": {"type": "page", "page": {"id": contact["notion_page_id"]}}
        })
```

### Таблицы

```python
{
    "object": "block",
    "type": "table",
    "table": {
        "table_width": N,
        "has_column_header": True,
        "has_row_header": False,
        "children": [header_row, *data_rows]
    }
}
```

Каждая строка — `table_row` с `cells` (список списков rich_text). Ячейка с page mention:

```python
[{"type": "mention", "mention": {"type": "page", "page": {"id": page_id}}}]
```

Если `notion_page_id` контакта неизвестен — ячейка содержит plain text с именем.

### Новости — вложенные блоки

```python
{
    "type": "bulleted_list_item",
    "bulleted_list_item": {
        "rich_text": [
            {"type": "text", "text": {"content": f"[{month_year}] {title}"},
             "annotations": {"bold": True}}
        ],
        "children": [
            paragraph_block(summary),
            paragraph_block(f"🔗 ", link=url),
        ]
    }
}
```

### heading_4 дисклеймер (footer)

```python
{
    "type": "heading_4",
    "heading_4": {
        "rich_text": [{
            "type": "text",
            "text": {"content": "Документ носит аналитический характер и составлен на основе открытых источников."},
            "annotations": {"italic": True, "color": "gray"}
        }],
        "is_toggleable": False
    }
}
```

---

## Секции и источники данных

### О компании

**Emoji:** 🏢  
**Источник:** `companies` + `dossiers` + `contacts` (где `info` содержит роль «CEO/CTO/…»)

| Поле | Источник в DB |
|---|---|
| Полное название | `companies.name` |
| Год основания | `dossiers.facts['founded_year']` (из `analysis_records` section='company') |
| Штаб-квартира | `analysis_records['company'].facts['hq']` |
| Дополнительные офисы | `analysis_records['company'].facts['offices']` |
| Размер компании | `companies.company_size` |
| Руководство | `contacts` отфильтрованные по tier=1 или содержащие CEO/CTO/VP/Head в `info`; paragraph с inline mentions |
| Основное направление | `companies.description` |
| Второстепенные направления | `analysis_records['company'].facts['secondary_activities']` |
| Положение на рынке | `analysis_records['company'].facts['market_position']` |

### Продукт [основной] и [второстепенный]

**Emoji:** 📦  
**Источник:** `dossiers` + `analysis_records` section=`'product'`

| Поле | Источник |
|---|---|
| Что это | `dossiers.product_category` + `dossiers.ai_use_case` |
| Целевой рынок | `analysis_records['product'].facts['target_market']` |
| Проблема, которую решает | `analysis_records['product'].facts['problem_solved']` |
| Технологии | `analysis_records['product'].facts['technologies']` |
| Функционал | `analysis_records['product'].facts['features']` (bulleted list) |
| Данные, необходимые продукту | `analysis_records['product'].facts['data_needs']` |
| Трудности в разработке | `analysis_records['product'].facts['challenges']` |

Если `facts` содержит второй продукт (`secondary_product`) — рендерится отдельный callout.

### Сотрудничество

**Emoji:** 🤝  
**Источник:** `contacts` + `analysis_records` section=`'collaboration'`

Два блока внутри callout:

**Таблица «Партнёры и поставщики данных»** — из `analysis_records['collaboration'].facts['partners']`:
Колонки: Тип | Компания | Роль

**Таблица «Команда»** — из `contacts` (type='person'):
Колонки: Имя | Должность | LinkedIn / Источник | Контакт (mention)

**ЛПР** — paragraph с inline hard_break из `contacts` с tier=1; формат:
`[Имя] ([должность из info]) — [направление решений]`

**Примечание** — `analysis_records['collaboration'].facts['note']`

### Финансы

**Emoji:** 💰  
**Источник:** `dossiers` + `analysis_records` section=`'financials'`

| Поле | Источник |
|---|---|
| Источники финансирования | `dossiers.funding_stage` |
| История раундов | таблица из `analysis_records['financials'].facts['rounds']` (Год / Раунд / Сумма / Инвесторы) |
| Оценка компании | `analysis_records['financials'].facts['valuation']` |
| Акции / Биржа | `analysis_records['financials'].facts['public_status']` |
| Финансовые показатели | bulleted list из `analysis_records['financials'].facts['metrics']` |
| Анализ динамики | `analysis_records['financials'].facts['dynamics']` |

### Новости

**Emoji:** 📰  
**Источник:** `research_records` (record_type=`'news'`) отсортированные по `observed_at` DESC, лимит 10

Каждый bullet:
- Жирный заголовок: `[Месяц Год] title`
- Дочерний paragraph: `summary`
- Дочерний paragraph: `🔗 [domain](url)`

### Комплексный анализ и оценка

**Emoji:** 🔍  
**Источник:** `dossiers.audit_md` + `analysis_records` section=`'audit'`

| Поле | Источник |
|---|---|
| Общая картина | `analysis_records['audit'].facts['overview']` |
| Таблица «Заявление → Реальная оценка» | `analysis_records['audit'].facts['claims_vs_reality']` |
| Риски | bulleted list из `analysis_records['audit'].facts['risks']` |
| Прогноз | `analysis_records['audit'].facts['forecast']` |

Если `analysis_records['audit']` отсутствует, но есть `dossiers.audit_md` — рендерится как plain paragraph (markdown → paragraph blocks через простой splitter по `\n\n`).

### Вывод для нас

**Emoji:** 🎯  
**Heading:** `heading_3` (а не `heading_2` как в остальных секциях)  
**Источник:** `dossiers.summary_md` + `analysis_records['audit'].facts['our_conclusion']`

| Поле | Источник |
|---|---|
| Почему интересны | bulleted list из `analysis_records['audit'].facts['why_interesting']` |
| Точка входа | `analysis_records['audit'].facts['entry_point']` |
| Угол для питча | `analysis_records['audit'].facts['pitch_angle']` |
| Рекомендуемый следующий шаг | `analysis_records['audit'].facts['next_step']` |

Если отдельные факты недоступны, но есть `dossiers.summary_md` — рендерится как plain text.

---

## Graceful Degradation

Секции рендерятся независимо. Правила:

- **Нет `dossiers`** → пропускаются секции «Продукт», «Финансы», «Анализ», «Вывод»
- **Нет `contacts`** → в «О компании» пропускается «Руководство»; в «Сотрудничество» пропускается таблица команды и ЛПР
- **Нет `research_records` с новостями** → пропускается секция «Новости»
- **Нет `analysis_records`** → структурные поля из `dossiers` всё равно рендерятся
- **Отдельное поле пустое** → этот paragraph пропускается, остальные рендерятся
- **Callout полностью пустой** (все поля None) → callout не создаётся

---

## Логика записи тела

### Когда пишется

1. **Первый sync** (`notion_page_id` у компании ещё нет) → после `create_page` сразу вызывается `render_and_write_body(company_id, page_id)`. Тело записывается однократно.

2. **Явный refresh** → флаг `--refresh-body` в CLI или команда `/notion_sync refresh` в боте. Удаляет все существующие блоки страницы (`blocks.children` — итерация + delete каждого), затем записывает новые.

### Когда НЕ пишется

Повторные `notion_sync.py` (cron, `/notion_sync` без `refresh`) — тело не трогается. Только properties обновляются.

---

## Новый API `NotionGateway`

Добавить в `NotionGateway` два метода:

```python
def list_block_children(self, block_id: str) -> list[dict]:
    """Все дочерние блоки (с пагинацией)."""
    results, cursor = [], None
    while True:
        resp = self._c.blocks.children.list(block_id=block_id, start_cursor=cursor) \
            if cursor else self._c.blocks.children.list(block_id=block_id)
        results.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]
    return results

def delete_block(self, block_id: str) -> None:
    self._c.blocks.delete(block_id=block_id)
```

`append_children` уже существует — используется без изменений.

---

## Интерфейс `notion_render.py`

```python
def build_page_blocks(
    company: dict,
    dossier: dict | None,
    analysis: dict[str, dict],   # section → analysis_record
    contacts: list[dict],
    news: list[dict],
) -> list[dict]:
    """Возвращает список Notion block payloads для тела страницы."""
    ...

def render_and_write_body(
    sync: NotionSync,
    company_id: str,
    page_id: str,
    refresh: bool = False,
) -> None:
    """Собирает данные из DB, строит блоки, записывает в Notion.
    Если refresh=True — сначала удаляет существующие блоки.
    """
    ...
```

---

## Изменения в `notion_sync.py`

В методе `sync_forward` для entity=`'companies'` — после `create_page(...)`:

```python
page = self.notion.create_page(db_id, props)
page_id = page["id"]
self.db.update(...)  # сохранить notion_page_id
# НОВОЕ: записать тело
from notion_render import render_and_write_body
render_and_write_body(self, row[cfg["db_key"]], page_id, refresh=False)
```

CLI: добавить флаг `--refresh-body` в `build_arg_parser`. При наличии флага — вызвать `render_and_write_body(..., refresh=True)` для всех компаний с `notion_page_id`.

---

## Тесты

Новый файл `tests/test_notion_render.py`:

- `test_build_page_blocks_full` — полные данные → все 7 callout-блоков присутствуют
- `test_build_page_blocks_no_dossier` — нет dossier → секции Продукт/Финансы/Анализ/Вывод отсутствуют
- `test_build_page_blocks_no_contacts` → Руководство и таблица команды отсутствуют
- `test_build_page_blocks_no_news` → секция Новости отсутствует
- `test_label_segment_format` — yellow+bold+code аннотации корректны
- `test_news_bullet_has_children` — bullet новости содержит дочерние paragraph-блоки
- `test_contacts_table_mention` — ячейка «Контакт» содержит mention-блок при наличии notion_page_id
- `test_refresh_deletes_existing_blocks` — при refresh=True вызывается delete для каждого существующего блока

---

## Не входит в скоуп

- Изменение схемы Supabase (новых колонок не добавляется)
- Изменение `notion_mapping.yaml`
- Изменение логики properties-sync
- Автоматический refresh по расписанию (только по явному запросу)
- Рендеринг тела для `contacts` и `dossiers` (только `companies`)
