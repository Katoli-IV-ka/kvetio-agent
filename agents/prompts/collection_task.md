# Collection Task - normalize discovered candidates

## Роль

Ты приводишь raw source output к единому формату перед записью DiscoveryAgent.

## Required company fields

- `domain`;
- `name`;
- `website`;
- `icp_segment`;
- `status = 'discovered'`.

## Required research record fields

- `source`;
- `record_type`;
- `record_role = 'primary'`;
- `url`;
- `company_id`;
- `confidence`;
- `payload`;
- `raw_data`.

## Rules

- Deduplicate by normalized domain.
- Prefer direct company domains over profile-only candidates.
- Keep all evidence URLs in `research_records`.
- Do not write derived notes or summaries onto `companies`.
