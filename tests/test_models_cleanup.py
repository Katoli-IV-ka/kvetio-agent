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


def test_contact_record_matches_compact_contact_schema() -> None:
    contact = ContactRecord(
        company_id="00000000-0000-0000-0000-000000000001",
        name="Jane Advisor",
        info="Advisor to the ML team; possible warm intro path.",
        linkedin_url="https://www.linkedin.com/in/janeadvisor",
        x_url="https://x.com/janeadvisor",
        other_channels=[
            {"type": "github", "url": "https://github.com/janeadvisor"},
        ],
    )

    assert contact.company_id == "00000000-0000-0000-0000-000000000001"
    assert contact.name == "Jane Advisor"
    assert contact.contact_type == "person"
    assert contact.info == "Advisor to the ML team; possible warm intro path."
    assert contact.other_channels == [
        {"type": "github", "url": "https://github.com/janeadvisor"},
    ]
