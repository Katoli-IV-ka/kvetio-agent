"""dm_github fetcher tests via respx."""

from __future__ import annotations

import pytest
from httpx import Response

from dm_github import (
    GH_API,
    extract_org_login,
    fetch_commit_authors,
    fetch_org_members,
    fetch_user_profile,
    is_real_email,
)
from http_client import HttpClient


def test_extract_org_login_simple():
    assert extract_org_login("https://github.com/radai-robolab") == "radai-robolab"


def test_extract_org_login_with_repo():
    assert extract_org_login("https://github.com/radai-robolab/some-repo") == "radai-robolab"


def test_extract_org_login_non_github():
    assert extract_org_login("https://huggingface.co/radai") is None


def test_extract_org_login_empty():
    assert extract_org_login("") is None


def test_is_real_email_valid():
    assert is_real_email("hintz@radai.com") is True


def test_is_real_email_noreply():
    assert is_real_email("146999853+user@users.noreply.github.com") is False


def test_is_real_email_none():
    assert is_real_email(None) is False


@pytest.mark.respx(base_url=GH_API)
def test_fetch_org_members_returns_logins(respx_mock):
    respx_mock.get("/orgs/test-org/members").mock(
        return_value=Response(200, json=[
            {"login": "user1", "id": 1},
            {"login": "user2", "id": 2},
        ])
    )
    with HttpClient(rate_limit_rps=0) as client:
        members = fetch_org_members("test-org", client)
    assert len(members) == 2
    assert members[0]["login"] == "user1"


@pytest.mark.respx(base_url=GH_API)
def test_fetch_user_profile_maps_fields(respx_mock):
    respx_mock.get("/users/jongwook").mock(
        return_value=Response(200, json={
            "login": "jongwook",
            "name": "Jong Wook Kim",
            "email": "jongwook@radai.com",
            "bio": "Research Scientist",
            "twitter_username": "jongwookk",
            "blog": "https://jongwook.kim",
            "company": "@radai",
        })
    )
    with HttpClient(rate_limit_rps=0) as client:
        profile = fetch_user_profile("jongwook", client)
    assert profile["name"] == "Jong Wook Kim"
    assert profile["contact_type"] == "person"
    assert profile["info"] == "Research Scientist"
    assert profile["email"] == "jongwook@radai.com"
    assert profile["x_url"] == "https://x.com/jongwookk"
    assert profile["other_channels"] == [
        {"type": "github", "url": "https://github.com/jongwook"},
        {"type": "personal_website", "url": "https://jongwook.kim"},
    ]


@pytest.mark.respx(base_url=GH_API)
def test_fetch_commit_authors_filters_noreply(respx_mock):
    respx_mock.get("/orgs/test-org/repos").mock(
        return_value=Response(200, json=[
            {"name": "main-repo", "stargazers_count": 100},
        ])
    )
    respx_mock.get("/repos/test-org/main-repo/commits").mock(
        return_value=Response(200, json=[
            {
                "commit": {
                    "author": {
                        "name": "Real User",
                        "email": "real@company.com",
                        "date": "2026-01-01",
                    }
                },
                "author": {"login": "realuser"},
            },
            {
                "commit": {
                    "author": {
                        "name": "Ghost",
                        "email": "1234+ghost@users.noreply.github.com",
                        "date": "2026-01-01",
                    }
                },
                "author": {"login": "ghost"},
            },
        ])
    )
    with HttpClient(rate_limit_rps=0) as client:
        authors = fetch_commit_authors("test-org", client, max_repos=1)
    assert len(authors) == 1
    assert authors[0]["email"] == "real@company.com"
    assert authors[0]["name"] == "Real User"
    assert authors[0]["contact_type"] == "person"
    assert authors[0]["info"] == "Commit author in test-org/main-repo"
    assert authors[0]["other_channels"] == [
        {"type": "github", "url": "https://github.com/realuser"},
    ]


def test_fetch_user_profile_includes_twitter_handle():
    from scripts.dm_github import fetch_user_profile
    from unittest.mock import MagicMock

    fake_client = MagicMock()
    fake_client.get_json.return_value = {
        "login": "jdoe",
        "name": "John Doe",
        "email": "john@radai.com",
        "twitter_username": "johndoe_x",
        "blog": "https://johndoe.dev",
        "bio": "ML at Rad AI",
        "company": "Rad AI",
    }
    result = fetch_user_profile("jdoe", fake_client)
    assert result["x_url"] == "https://x.com/johndoe_x"


def test_fetch_user_profile_twitter_handle_none_when_absent():
    from scripts.dm_github import fetch_user_profile
    from unittest.mock import MagicMock

    fake_client = MagicMock()
    fake_client.get_json.return_value = {
        "login": "jdoe",
        "name": "John Doe",
        "twitter_username": None,
        "blog": None,
        "email": None,
        "bio": None,
        "company": None,
    }
    result = fetch_user_profile("jdoe", fake_client)
    assert result["x_url"] is None


def test_main_write_calls_contact_writer(mocker):
    from scripts import dm_github

    mocker.patch("scripts.dm_github.fetch", return_value=[{"name": "Alice"}])
    writer = mocker.patch("scripts.dm_github.write_contacts")
    mocker.patch("sys.argv", ["dm_github.py", "--domain", "sift.com", "--write"])

    dm_github.main()

    writer.assert_called_once_with(
        domain="sift.com",
        source="github",
        contacts=[{"name": "Alice"}],
    )


def test_main_without_write_does_not_call_contact_writer(mocker, capsys):
    from scripts import dm_github

    mocker.patch("scripts.dm_github.fetch", return_value=[{"name": "Alice"}])
    writer = mocker.patch("scripts.dm_github.write_contacts")
    mocker.patch("sys.argv", ["dm_github.py", "--domain", "sift.com"])

    dm_github.main()

    writer.assert_not_called()
    assert "Alice" in capsys.readouterr().out
