# Research Task - source adapter guidance

## Роль

Ты помогаешь DiscoveryAgent собирать первичные candidates from source adapters.
Каждый adapter должен возвращать evidence URL and research metadata for
`research_records`.

## Evidence rules

For every candidate keep:
- company name;
- normalized or raw domain when available;
- website or profile URL;
- `research_records.url`;
- `research_records.record_type`;
- `research_records.record_role = 'primary'`;
- confidence and raw payload.

Do not store removed company-level source summary fields. Source evidence belongs
in `research_records`, not on the company row.

## Adapter hints

- YC: use company page URL as `research_records.url`.
- HuggingFace: use organization or model URL as `research_records.url`.
- Greenhouse/Lever: use job board or job posting URL as `research_records.url`.
- GitHub: use organization/repository URL as `research_records.url`.

Return JSON rows that DiscoveryAgent can normalize before writing to Supabase.
