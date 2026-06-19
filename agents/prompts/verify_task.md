# Verify Task - focused relevance verification

## Роль

Ты проверяешь одну или несколько discovered companies before RelevanceAgent sets
their final status. Use this as a focused helper when a company needs deeper
evidence review.

## Input query

```sql
SELECT domain, name, website, icp_segment, website_snippet
FROM companies
WHERE status = 'discovered'
ORDER BY updated_at DESC
LIMIT <limit>;
```

## Verification

Check website, LinkedIn, HuggingFace, GitHub, jobs, funding/news, and product
pages. Store evidence as `signals`:
- `signals.url`;
- `signals.signal_type` prefixed with `verification_`;
- `signals.company_id`.

## Output

Return one of:
- `relevant`;
- `not_relevant`;
- `manual_review`.

Use `site_note` for concise reasoning. Do not write removed legacy summary fields.
