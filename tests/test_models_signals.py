"""Tests for RawSignal and confidence_to_score (signals redesign)."""

from datetime import date

import pytest

from scripts.models import RawSignal, confidence_to_score


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
