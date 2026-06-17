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
selected company id and domain in every contacts_store payload. Do not create
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
  "company_domain": "acme.ai",
  "full_name": "Alice Chen",
  "contact_type": "Person",
  "title": "Head of ML",
  "email": "alice@acme.ai",
  "source_vector": "apollo",
  "source_url": "https://app.apollo.io/#/people/alice-chen"
}
```

Write via:

```bash
python scripts/contacts_store.py --upsert
```

Then optional enrichment can call:

```bash
python scripts/contact_enricher.py --domain <domain>
```
