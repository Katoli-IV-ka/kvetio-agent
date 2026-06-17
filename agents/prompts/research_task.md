# Research Task - source adapter guidance

## Роль

Ты помогаешь DiscoveryAgent собирать первичные candidates from source adapters.
Каждый adapter должен возвращать evidence URL and signal metadata for `signals`.

## Evidence rules

For every candidate keep:
- company name;
- normalized or raw domain when available;
- website or profile URL;
- `signals.evidence_url`;
- `signals.signal_type` prefixed with `primary_`;
- confidence and raw payload.

Do not store removed company-level source summary fields. Source evidence belongs
in `signals`, not on the company row.

## Adapter hints

- YC: use company page URL as `signals.evidence_url`.
- HuggingFace: use organization or model URL as `signals.evidence_url`.
- Greenhouse/Lever: use job board or job posting URL as `signals.evidence_url`.
- GitHub: use organization/repository URL as `signals.evidence_url`.

Return JSON rows that DiscoveryAgent can normalize before writing to Supabase.
