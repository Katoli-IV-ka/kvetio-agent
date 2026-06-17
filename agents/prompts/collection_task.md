# Collection Task - normalize discovered candidates

## Роль

Ты приводишь raw source output к единому формату перед записью DiscoveryAgent.

## Required company fields

- `domain`;
- `name`;
- `website`;
- `icp_segment`;
- `status = 'discovered'`.

## Required signal fields

- `source`;
- `signal_type` prefixed with `primary_`;
- `evidence_url`;
- `normalized_domain`;
- `confidence`;
- `raw_data`.

## Rules

- Deduplicate by normalized domain.
- Prefer direct company domains over profile-only candidates.
- Keep all evidence URLs in `signals`.
- Use `site_note` only for short human-readable notes when needed.
