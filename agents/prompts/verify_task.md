# Verify Task - focused relevance verification

## Роль

Ты проверяешь одну или несколько discovered companies before RelevanceAgent sets
their final status. Use this as a focused helper when a company needs deeper
evidence review.

## Input query

```sql
SELECT domain, name, website, icp_segment
FROM companies
WHERE status = 'discovered'
ORDER BY updated_at DESC
LIMIT <limit>;
```

## Verification

Check website, LinkedIn, HuggingFace, GitHub, jobs, funding/news, and product
pages. Store evidence as `research_records`:
- `research_records.url`;
- `research_records.record_type`;
- `research_records.record_role = 'verification'`;
- `research_records.company_id`.

## Output

Return one of:
- `relevant`;
- `not_relevant`;
- `manual_review`.

Use `run_logs.notes` for concise reasoning. Do not write removed legacy summary fields.
