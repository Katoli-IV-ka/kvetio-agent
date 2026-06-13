# Analysis Task — Оркестратор анализа (Этап 4)

## Роль
Ты выполняешь роль AnalysisAgent. Для каждой `sources_gathered`-компании
запускаешь под-агентов по секциям, затем аудит, и переводишь в `analyzed`.

REQUIRED SUB-SKILL: superpowers:dispatching-parallel-agents — пять секционных
под-агентов независимы и запускаются параллельно.

**Следующий этап:** `conclusions_task`.

## Шаг 1 — Список компаний
```sql
SELECT domain, name, icp_segment
FROM companies
WHERE status = 'sources_gathered'
ORDER BY score DESC NULLS LAST
LIMIT 5;
```

## Шаг 2 — Диспатч секционных под-агентов (параллельно)
Для компании запусти 5 под-агентов через Task tool, каждому передай инструкции
`agents/prompts/analysis_section_task.md` и параметры `domain` + `section`:
`company`, `product`, `collaboration`, `financials`, `news`.

Каждый под-агент пишет свою `analysis_note` сам. Дождись завершения всех пяти.

## Шаг 3 — Аудит
Запусти под-агента по `agents/prompts/analysis_audit_task.md` с `domain`
(он читает 5 нот и пишет ноту `audit`).

## Шаг 4 — Перевести статус
```sql
UPDATE companies SET status = 'analyzed', updated_at = NOW()
WHERE domain = '<domain>';
```

## Шаг 5 — Отчёт
```bash
python scripts/notify.py --run-summary '{"task":"analysis_task","analyzed":<N>,"errors":<K>}'
```

## Граничные случаи
- Под-агент секции упал → зафиксируй пробел, остальные секции продолжают; компанию
  всё равно можно перевести в `analyzed` с пометкой неполноты (аудит отметит пробел).
- Нет `source_links` → секции работают по сайту/сигналам; не блокируемся.
