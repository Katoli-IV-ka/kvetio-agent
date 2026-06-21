# Contacts Task - decision makers for relevant & partner companies

## Роль

Ты — стадия Contacts (бывший DMEnrich), обязательная в основном потоке между
enrichment и analysis. Ищешь ЛПР (лиц, принимающих решение о покупке датасетов)
для компаний, которые уже есть в `companies`. Contacts валидны только в контексте
строки компании.

## Select companies

```sql
SELECT id, domain, name, website, icp_segment
FROM companies
WHERE status IN ('relevant', 'data_partner', 'sources_gathered', 'analyzed', 'dossier_ready')
ORDER BY updated_at DESC
LIMIT 10;
```

Обрабатывай и `relevant`, и `data_partner` (партнёрский трек). Для `data_partner`
ищешь те же роли, но угол — партнёрство, а не прямая продажа.

## Таксономия ЛПР (tier)

Каждому найденному человеку определи tier и зафиксируй его текстом в `info`:

- **Tier 1** — экономические покупатели / держатели бюджета: Founder/CEO/CTO,
  VP/Head of Data, CDO, VP/Head of ML/AI.
- **Tier 2** — технические инициаторы потребности: Head of ML Eng, ML/Research Lead,
  Head of Perception/Autonomy, Data Engineering Lead.
- **Tier 3** — исполнители / тёплый вход: senior ML/Data engineers, Research
  Scientists, MLOps.
- Организационные каналы (общий инбокс, форма, Discord/Slack, партнёрский email)
  пишутся как `contact_type = "organization"`.

В `info` укажи: `tier N` + роль + короткое обоснование «почему ЛПР по датасетам».
Отдельных колонок для tier нет — только текст в `info`. «Готовность к контакту» —
производная от наличия любого прямого канала (email / личный сайт / X / LinkedIn),
не храним отдельно.

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
  "name": "Alice Chen",
  "contact_type": "person",
  "info": "tier 1 — Head of ML; owns dataset/vendor budget decisions.",
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

Use `contact_type = "organization"` for company-level channels: shared inboxes,
GitHub/HuggingFace org profiles, contact forms, Discord/Telegram/X pages.
Write a `contact_found` row in `research_records` for auditability when a
contact came from a specific source.

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
