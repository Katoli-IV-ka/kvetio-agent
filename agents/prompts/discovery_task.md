# Discovery Task - первичный сбор кандидатов

## Роль

Ты выполняешь роль DiscoveryAgent. Для заданного ICP segment находишь новые
компании-кандидаты, дедуплицируешь по normalized domain и записываешь только
первичные факты.

Discovery не делает relevance filtering и не решает релевантность. Его задача -
создать `companies.status = 'discovered'` и `research_records` с первичным evidence.

## Параметры

| Параметр | По умолчанию | Описание |
|---|---:|---|
| `segment` | required | ICP segment |
| `limit` | 5 | Максимум новых компаний |
| `dry_run` | false | Не писать в Supabase |

## Источники

Используй enabled sources из `config/sources.yaml`:

```bash
python scripts/huggingface.py --segment <segment> --max-models 1000
python scripts/yc_browser.py --segment <segment> --limit <limit>
python scripts/github.py --segment <segment> --limit <limit> --dry-run
python scripts/greenhouse.py --segment <segment>
```

## Запись

Для каждой принятой компании:
- `companies.domain`, `name`, `website`, `icp_segment`, `status = 'discovered'`;
- `research_records.url`, `research_records.record_type`;
- `research_records.record_role = 'primary'`;
- `research_records.company_id`, `research_records.payload`, `research_records.confidence`.

Не храни агрегированные source summaries на строке company. Latest evidence is
derived from `research_records`.

## Отчет

```bash
python scripts/notify.py --run-summary '{"task":"discovery_task","found":<N>,"errors":0}'
```
