# Discover Verify Task - deprecated

УСТАРЕЛ: этот combined prompt больше не используется для штатного pipeline.

Используй отдельные этапы:
- `discovery_task.md` writes discovered companies and `primary_*` signals.
- `relevance_task.md` sets `relevant`, `not_relevant`, or `manual_review`.
- `source_expansion_task.md` gathers supporting links and sets `sources_gathered`.

Если этот файл открыт вручную, не запускай combined flow. Вернись к
`pipeline_main_task.md`.
