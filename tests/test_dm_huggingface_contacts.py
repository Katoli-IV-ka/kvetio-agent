"""dm_huggingface_contacts tests via respx."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from httpx import Response

from dm_huggingface_contacts import (
    HF_API,
    fetch_members,
    fetch_user_overview,
    get_hf_org_for_domain,
)
from http_client import HttpClient


def test_get_hf_org_for_domain_finds_org():
    store = MagicMock()
    store.get_research_records_for_company.return_value = [
        {"url": "https://huggingface.co/radai-robolab"},
    ]
    result = get_hf_org_for_domain("radai.com", store)
    assert result == "radai-robolab"


def test_get_hf_org_for_domain_skips_non_hf():
    store = MagicMock()
    store.get_research_records_for_company.return_value = [
        {"url": "https://github.com/radai-robolab"},
    ]
    result = get_hf_org_for_domain("radai.com", store)
    assert result is None


def test_get_hf_org_skips_system_paths():
    store = MagicMock()
    store.get_research_records_for_company.return_value = [
        {"url": "https://huggingface.co/models"},
    ]
    result = get_hf_org_for_domain("radai.com", store)
    assert result is None


@pytest.mark.respx(base_url=HF_API)
def test_fetch_members_returns_list(respx_mock):
    respx_mock.get("/organizations/radai/members").mock(
        return_value=Response(200, json=[
            {"user": "jongwook", "fullname": "Jong Wook Kim"},
            {"user": "hintz", "fullname": "Drew Hintz"},
        ])
    )
    with HttpClient(rate_limit_rps=0) as client:
        members = fetch_members("radai", client)
    assert len(members) == 2
    assert members[0]["user"] == "jongwook"


@pytest.mark.respx(base_url=HF_API)
def test_fetch_user_overview_maps_fields(respx_mock):
    respx_mock.get("/users/jongwook/overview").mock(
        return_value=Response(200, json={
            "user": "jongwook",
            "fullname": "Jong Wook Kim",
            "details": "Research Scientist at Rad.AI",
        })
    )
    with HttpClient(rate_limit_rps=0) as client:
        overview = fetch_user_overview("jongwook", client)
    assert overview["fullname"] == "Jong Wook Kim"
    assert "Research Scientist" in overview["details"]


def test_main_write_calls_contact_writer(mocker):
    from scripts import dm_huggingface_contacts

    mocker.patch("scripts.dm_huggingface_contacts.fetch", return_value=[{"name": "Alice"}])
    writer = mocker.patch("scripts.dm_huggingface_contacts.write_contacts")
    mocker.patch(
        "sys.argv",
        ["dm_huggingface_contacts.py", "--domain", "acme.ai", "--write"],
    )

    dm_huggingface_contacts.main()

    writer.assert_called_once_with(
        domain="acme.ai",
        source="huggingface",
        contacts=[{"name": "Alice"}],
    )
