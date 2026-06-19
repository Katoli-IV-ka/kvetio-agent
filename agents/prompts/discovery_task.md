# Discovery Task - первичный сбор кандидатов

## Роль

Ты выполняешь роль DiscoveryAgent. Для заданного ICP segment находишь новые
компании-кандидаты, дедуплицируешь по normalized domain и записываешь только
первичные факты.

Discovery не делает relevance filtering и не решает релевантность. Его задача -
создать `companies.status = 'discovered'` и `signals` с первичным evidence.

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
- `signals.url`, `signals.signal_type` prefixed with `primary_`;
- `signals.company_id`, `signals.payload`, `signals.confidence`.

Не храни агрегированные source summaries на строке company. Latest evidence is
derived from `signals`.

## Отчет

```bash
python scripts/notify.py --run-summary '{"task":"discovery_task","found":<N>,"errors":0}'
```
