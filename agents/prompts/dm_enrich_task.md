# DM Enrich Task - contacts for relevant companies

## Роль

Ты ищешь decision makers only for companies that already exist in `companies`.
Contacts are valid only in the context of a company row.

## Select companies

```sql
SELECT id, domain, name, website, icp_segment
FROM companies
WHERE status IN ('relevant', 'sources_gathered', 'analyzed', 'dossier_ready')
ORDER BY updated_at DESC
LIMIT 10;
```

Only write contacts for companies selected from the companies table. Use the
selected company id in every contacts_store payload. Do not create
contacts for a company that does not exist in companies.

## Contact sources

- GitHub profiles;
- HuggingFace profiles;
- team pages;
- Apollo;
- Wellfound;
- arXiv;
- contact pages.

## Contact payload

```json
{
  "company_id": "00000000-0000-0000-0000-000000000001",
  "first_name": "Alice",
  "last_name": "Chen",
  "info": "Head of ML; likely owns dataset/vendor decisions.",
  "email": "alice@acme.ai",
  "phone": "+1-555-0100",
  "linkedin_url": "https://www.linkedin.com/in/alicechen",
  "x_url": "https://x.com/alicechen",
  "facebook_url": null,
  "instagram_url": null,
  "other_channels": [
    {"type": "github", "url": "https://github.com/alicechen"},
    {"type": "personal_website", "url": "https://alicechen.dev"}
  ]
}
```

Do not put `email`, `phone`, `linkedin_url`, `x_url`, `facebook_url`, or
`instagram_url` into `other_channels`. These are primary channels and must live
only in their dedicated fields.

Write via:

```bash
python scripts/contacts_store.py --upsert
```

Then optional enrichment can call:

```bash
python scripts/contact_enricher.py --domain <domain>
```
