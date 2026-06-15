# Conclusions Task — Сборка досье и публикация (Этап 5)

## Роль
Ты выполняешь роль ConclusionAgent. Для каждой `analyzed`-компании собираешь
финальное досье из нот этапа 4, пишешь его в `dossiers`, публикуешь в Notion и
переводишь в `dossier_ready`.

**Это финальный этап pipeline.** Аутрич остаётся ручным.

## Шаг 1 — Список компаний
```sql
SELECT domain, name, website, icp_segment, score, score_bucket, ai_direction
FROM companies WHERE status = 'analyzed'
ORDER BY score DESC NULLS LAST LIMIT 5;
```

## Шаг 2 — Загрузить ноты
```bash
python scripts/dossier_store.py --list-analysis-notes <domain>
```
Ожидаются ноты: company, product, collaboration, financials, news, audit.

## Шаг 3 — Собрать саммари (Markdown, 6 разделов)
Скомпонуй `summary_md` строго из фактов нот, сохраняя ссылки-провенанс:

```markdown
## О компании
<размер, локация, дата основания, глава, направления, динамика позиции>

## Продукт
<интересующий продукт(ы): дата старта, результаты, цель/проблема/рынок, технологии, трудности, пивоты>

## Сотрудничество
<партнёры (особенно поставщики данных), команда, руководство/ЛПР>

## Финансовое здоровье
<раунды, инвесторы, признаки роста/burn; биржевой график — если публичная>

## Новости
<актуальные за 6–12 мес, без повторов инфоповодов: заголовок = суть + ссылка>
```

### Аудит
`audit_md` — из ноты `audit` (критическая оценка, прогноз, вывод для продажи data services, точки контакта, угол оффера).

## Шаг 4 — Записать досье
```bash
echo '{
  "company_domain":"<domain>",
  "summary_md":"<summary_md>",
  "sections":{ "company":"...", "product":"...", "collaboration":"...", "financials":"...", "news":"..." },
  "audit_md":"<audit_md>",
  "table_fields":{
    "name":"<name>", "website":"<website>", "segment":"<segment>",
    "score":<score>, "bucket":"<bucket>",
    "sales_opportunity":"<из audit>", "contact_angle":"<из audit>"
  },
  "version":"v1"
}' | python scripts/dossier_store.py --upsert-dossier
```

> Полный список полней таблицы ещё не финализирован — `table_fields` провизорный.
> При обновлении набора полей менять только этот блок.

## Шаг 5 — Синхронизация в Notion

Публикация в Notion полностью детерминирована и вынесена в скрипт — ad-hoc MCP-вызовы
здесь не используем. Запусти синк компаний (reverse+forward) и публикацию досье в тело
страницы:

```bash
python scripts/notion_sync.py --entity companies --all
python scripts/notion_sync.py --entity dossiers
```

`notion_page_id` записывается скриптом в БД автоматически — отдельный UPDATE не нужен.
Если поле в Notion ещё не создано (после правки `config/notion_mapping.yaml`):

```bash
python scripts/notion_sync.py --ensure-schema --entity companies
```

## Шаг 6 — Перевести статус
```sql
UPDATE companies SET status = 'dossier_ready', updated_at = NOW()
WHERE domain = '<domain>';
```

## Шаг 7 — Уведомления
```bash
python scripts/notify.py --run-summary '{"task":"conclusions_task","dossier_ready":<N>,"errors":<K>}'
```
Hot-лид (score ≥ threshold_qualified) → `python scripts/notify.py --hot-lead '{...}'`.
