from __future__ import annotations

from models import ALL_STATUSES, ContactRecord


def test_all_statuses_match_cleanup_design() -> None:
    assert ALL_STATUSES == (
        "discovered",
        "relevant",
        "not_relevant",
        "manual_review",
        "sources_gathered",
        "analyzed",
        "dossier_ready",
    )


def test_contact_record_supports_company_id_and_related_person() -> None:
    contact = ContactRecord(
        company_id="00000000-0000-0000-0000-000000000001",
        company_domain="acme.ai",
        full_name="Jane Advisor",
        contact_type="Related Person",
        title="Advisor",
    )

    assert contact.company_id == "00000000-0000-0000-0000-000000000001"
    assert contact.company_domain == "acme.ai"
    assert contact.contact_type == "Related Person"
    assert contact.title == "Advisor"
