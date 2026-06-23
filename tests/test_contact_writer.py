"""Tests for shared contact writer."""

from __future__ import annotations

from unittest.mock import MagicMock


def test_best_evidence_url_prefers_linkedin():
    from scripts.contact_writer import best_evidence_url

    assert best_evidence_url(
        "acme.ai",
        {
            "linkedin_url": "https://linkedin.com/in/alice",
            "other_channels": [{"type": "github", "url": "https://github.com/alice"}],
        },
    ) == "https://linkedin.com/in/alice"


def test_best_evidence_url_uses_other_channel_then_domain():
    from scripts.contact_writer import best_evidence_url

    assert best_evidence_url(
        "acme.ai",
        {"other_channels": [{"type": "github", "url": "https://github.com/alice"}]},
    ) == "https://github.com/alice"
    assert best_evidence_url("acme.ai", {"other_channels": []}) == "https://acme.ai"


def test_write_contacts_skips_missing_name(mocker, caplog):
    from scripts.contact_writer import write_contacts

    store = MagicMock()
    mocker.patch("scripts.contact_writer.SupabaseStore", return_value=store)
    upsert = mocker.patch("scripts.contact_writer.upsert_contact", return_value="contact-1")

    result = write_contacts(
        domain="acme.ai",
        source="github",
        contacts=[{"name": "", "contact_type": "person"}],
    )

    assert result == {"found": 1, "written": 0, "skipped": 1, "audit_errors": 0}
    upsert.assert_not_called()
    assert "Skipping contact without name" in caplog.text


def test_write_contacts_writes_contact_and_audit(mocker):
    from scripts.contact_writer import write_contacts

    store = MagicMock()
    mocker.patch("scripts.contact_writer.SupabaseStore", return_value=store)
    mocker.patch("scripts.contact_writer.upsert_contact", return_value="contact-1")

    result = write_contacts(
        domain="acme.ai",
        source="github",
        contacts=[
            {
                "name": "Alice Chen",
                "contact_type": "person",
                "info": "tier 1 - CTO",
                "email": "alice@acme.ai",
                "other_channels": [{"type": "github", "url": "https://github.com/alice"}],
            }
        ],
    )

    assert result == {"found": 1, "written": 1, "skipped": 0, "audit_errors": 0}
    store.upsert_research_record.assert_called_once()
    entry = store.upsert_research_record.call_args.args[0]
    assert entry.record_type == "contact_found"
    assert entry.record_role == "evidence"
    assert entry.source == "github"
    assert entry.agent == "contact_writer"
    assert entry.payload["contact_id"] == "contact-1"
    assert store.upsert_research_record.call_args.kwargs["domain"] == "acme.ai"


def test_write_contacts_continues_when_audit_fails(mocker, caplog):
    from scripts.contact_writer import write_contacts

    store = MagicMock()
    store.upsert_research_record.side_effect = RuntimeError("audit down")
    mocker.patch("scripts.contact_writer.SupabaseStore", return_value=store)
    mocker.patch("scripts.contact_writer.upsert_contact", return_value="contact-1")

    result = write_contacts(
        domain="acme.ai",
        source="github",
        contacts=[{"name": "Alice Chen", "contact_type": "person"}],
    )

    assert result == {"found": 1, "written": 1, "skipped": 0, "audit_errors": 1}
    assert "contact_found audit write failed" in caplog.text
