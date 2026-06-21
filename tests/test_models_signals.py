"""Tests for RawSignal and confidence_to_score (signals redesign)."""

from datetime import date
from typing import get_args

import pytest

from scripts.models import (
    ALL_STATUSES,
    ContactRecord,
    RawSignal,
    ResearchRecord,
    SignalType,
    confidence_to_score,
)


def test_data_partner_is_a_valid_status():
    assert "data_partner" in ALL_STATUSES


def test_phase1_record_types_in_signal_type():
    codes = set(get_args(SignalType))
    for code in (
        "form_d",
        "grant",
        "quote",
        "job_count",
        "market_quote",
        "arxiv_paper",
        "data_partner_flag",
    ):
        assert code in codes


def test_confidence_to_score_maps_labels():
    assert confidence_to_score("high") == 0.9
    assert confidence_to_score("medium") == 0.5
    assert confidence_to_score("low") == 0.2
    assert confidence_to_score(0.73) == 0.73


def test_confidence_to_score_unknown_defaults_to_medium():
    assert confidence_to_score("unknown") == 0.5


def test_confidence_to_score_int():
    assert confidence_to_score(1) == 1.0


def test_rawsignal_has_url_and_agent():
    s = RawSignal(
        source="github",
        signal_type="github_repo",
        company_name="Acme",
        domain="acme.com",
        linkedin_url=None,
        url="https://github.com/acme",
        signal_date=date(2026, 6, 1),
        confidence="high",
        agent="discovery",
    )
    assert s.url == "https://github.com/acme"
    assert s.agent == "discovery"


def test_rawsignal_url_required():
    with pytest.raises(ValueError, match="url"):
        RawSignal(
            source="github",
            signal_type="github_repo",
            company_name="Acme",
            domain="acme.com",
            linkedin_url=None,
            url="",
            signal_date=date(2026, 6, 1),
            confidence="high",
        )


def test_rawsignal_payload_and_raw_payload():
    s = RawSignal(
        source="huggingface",
        signal_type="hf_org",
        company_name="Acme AI",
        domain="acme.ai",
        linkedin_url=None,
        url="https://huggingface.co/acme",
        signal_date=date(2026, 6, 1),
        confidence="medium",
        payload={"num_models": 5},
        raw_payload={"raw": "data"},
    )
    assert s.payload == {"num_models": 5}
    assert s.raw_payload == {"raw": "data"}


def test_research_record_has_fields_and_default_role():
    e = ResearchRecord(
        source="github",
        record_type="github_repo",
        company_name="Rad AI",
        domain="radai.com",
        linkedin_url=None,
        url="https://github.com/radai",
        observed_at=date(2026, 6, 19),
        confidence=0.8,
    )
    assert e.record_type == "github_repo"
    assert e.observed_at == date(2026, 6, 19)
    assert e.record_role == "evidence"


def test_rawsignal_is_alias_of_research_record():
    assert RawSignal is ResearchRecord


def test_contact_record_uses_name_and_type():
    c = ContactRecord(company_id="cid", name="Sarah Chen")
    assert c.name == "Sarah Chen"
    assert c.contact_type == "person"
