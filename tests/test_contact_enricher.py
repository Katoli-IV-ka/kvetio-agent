"""Tests for contact_enricher."""


# ── Pattern Inference ──────────────────────────────────────────────────────


def test_infer_pattern_first_last():
    from scripts.contact_enricher import _infer_pattern
    contacts = [
        {"first_name": "Sarah", "last_name": "Chen", "email": "sarah.chen@radai.com"},
        {"first_name": "John", "last_name": "Doe", "email": "john.doe@radai.com"},
    ]
    assert _infer_pattern(contacts) == "first.last"


def test_infer_pattern_first_only():
    from scripts.contact_enricher import _infer_pattern
    contacts = [
        {"first_name": "Sarah", "last_name": "Chen", "email": "sarah@radai.com"},
    ]
    assert _infer_pattern(contacts) == "first"


def test_infer_pattern_flast():
    from scripts.contact_enricher import _infer_pattern
    contacts = [
        {"first_name": "Sarah", "last_name": "Chen", "email": "schen@radai.com"},
    ]
    assert _infer_pattern(contacts) == "flast"


def test_infer_pattern_returns_none_when_no_contacts():
    from scripts.contact_enricher import _infer_pattern
    assert _infer_pattern([]) is None


def test_infer_pattern_returns_none_when_missing_names():
    from scripts.contact_enricher import _infer_pattern
    contacts = [{"email": "info@radai.com"}]
    assert _infer_pattern(contacts) is None


# ── Pattern Application ────────────────────────────────────────────────────


def test_apply_pattern_first_last():
    from scripts.contact_enricher import _apply_pattern
    assert _apply_pattern("first.last", "Sarah", "Chen", "radai.com") == "sarah.chen@radai.com"


def test_apply_pattern_first():
    from scripts.contact_enricher import _apply_pattern
    assert _apply_pattern("first", "Sarah", "Chen", "radai.com") == "sarah@radai.com"


def test_apply_pattern_flast():
    from scripts.contact_enricher import _apply_pattern
    assert _apply_pattern("flast", "Sarah", "Chen", "radai.com") == "schen@radai.com"


def test_apply_pattern_firstlast():
    from scripts.contact_enricher import _apply_pattern
    assert _apply_pattern("firstlast", "Sarah", "Chen", "radai.com") == "sarahchen@radai.com"


# ── Guess Emails ───────────────────────────────────────────────────────────


def test_guess_emails_skips_contacts_without_names():
    from scripts.contact_enricher import guess_emails
    contacts = [{"first_name": None, "last_name": None, "email": None}]
    assert guess_emails("radai.com", contacts) == []


def test_guess_emails_skips_contacts_with_existing_email():
    from scripts.contact_enricher import guess_emails
    contacts = [{"first_name": "Sarah", "last_name": "Chen", "email": "sarah.chen@radai.com"}]
    assert guess_emails("radai.com", contacts) == []


def test_guess_emails_infers_pattern_and_fills_missing():
    from scripts.contact_enricher import guess_emails
    contacts = [
        {"first_name": "Sarah", "last_name": "Chen", "email": "sarah.chen@radai.com"},
        {"first_name": "John", "last_name": "Doe", "email": None, "full_name": "John Doe"},
    ]
    result = guess_emails("radai.com", contacts)
    assert len(result) == 1
    assert result[0]["email"] == "john.doe@radai.com"
    assert result[0]["email_status"] == "guessed"
    assert result[0]["email_source"] == "pattern_guesser"
    assert result[0]["confidence"] == "low"


def test_guess_emails_uses_first_last_fallback_when_no_pattern():
    from scripts.contact_enricher import guess_emails
    contacts = [
        {"first_name": "John", "last_name": "Doe", "email": None, "full_name": "John Doe"},
    ]
    result = guess_emails("radai.com", contacts)
    assert len(result) == 1
    # Falls back to "first.last" as the default when no pattern is known
    assert result[0]["email"] == "john.doe@radai.com"


# ── Hunter.io Verify ───────────────────────────────────────────────────────


def test_verify_with_hunter_returns_valid():
    from scripts.contact_enricher import verify_with_hunter
    from unittest.mock import patch, MagicMock

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"result": "valid"}}

    with patch("scripts.contact_enricher.httpx.get", return_value=mock_resp):
        result = verify_with_hunter("john@radai.com", "test-key")
    assert result == "valid"


def test_verify_with_hunter_returns_unknown_on_failure():
    from scripts.contact_enricher import verify_with_hunter
    from unittest.mock import patch

    with patch("scripts.contact_enricher.httpx.get", side_effect=Exception("timeout")):
        result = verify_with_hunter("john@radai.com", "test-key")
    assert result == "unknown"


def test_run_hunter_verify_updates_status_to_valid():
    from scripts.contact_enricher import run_hunter_verify
    from unittest.mock import patch, MagicMock

    contact = {
        "email": "john.doe@radai.com",
        "email_status": "guessed",
        "full_name": "John Doe",
        "company_domain": "radai.com",
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"result": "valid"}}

    with patch("scripts.contact_enricher.httpx.get", return_value=mock_resp):
        result = run_hunter_verify([contact], api_key="test-key")

    assert len(result) == 1
    assert result[0]["email_status"] == "valid"
    assert result[0]["email_source"] == "hunter_verify"
    assert result[0]["email"] == "john.doe@radai.com"


def test_run_hunter_verify_clears_invalid_email():
    from scripts.contact_enricher import run_hunter_verify
    from unittest.mock import patch, MagicMock

    contact = {
        "email": "wrong@radai.com",
        "email_status": "guessed",
        "full_name": "John Doe",
        "company_domain": "radai.com",
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"data": {"result": "invalid"}}

    with patch("scripts.contact_enricher.httpx.get", return_value=mock_resp):
        result = run_hunter_verify([contact], api_key="test-key")

    assert result[0]["email"] is None
    assert result[0]["email_status"] == "invalid"


def test_run_hunter_verify_skips_non_guessed_contacts():
    from scripts.contact_enricher import run_hunter_verify

    contact = {"email": "real@radai.com", "email_status": "valid", "full_name": "Sarah"}
    result = run_hunter_verify([contact], api_key="test-key")
    assert result == []


# ── GitHub Enrichment ──────────────────────────────────────────────────────


def test_enrich_from_github_fills_twitter_and_website():
    from scripts.contact_enricher import enrich_from_github
    from unittest.mock import patch, MagicMock

    contact = {
        "github_username": "jdoe",
        "twitter_handle": None,
        "personal_website": None,
        "full_name": "John Doe",
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "login": "jdoe",
        "twitter_username": "jdoe_x",
        "blog": "https://johndoe.dev",
    }
    with patch("scripts.contact_enricher.httpx.get", return_value=mock_resp):
        result = enrich_from_github([contact])

    assert len(result) == 1
    assert result[0]["twitter_handle"] == "jdoe_x"
    assert result[0]["personal_website"] == "https://johndoe.dev"


def test_enrich_from_github_skips_already_enriched():
    from scripts.contact_enricher import enrich_from_github

    contact = {
        "github_username": "jdoe",
        "twitter_handle": "existing",
        "personal_website": "https://x.com",
        "full_name": "John Doe",
    }
    result = enrich_from_github([contact])
    assert result == []


def test_enrich_from_github_skips_contacts_without_username():
    from scripts.contact_enricher import enrich_from_github

    contact = {"github_username": None, "full_name": "John Doe"}
    result = enrich_from_github([contact])
    assert result == []


# ── HuggingFace Enrichment ─────────────────────────────────────────────────


def test_enrich_from_huggingface_extracts_twitter_from_bio():
    from scripts.contact_enricher import enrich_from_huggingface
    from unittest.mock import patch, MagicMock

    contact = {
        "hf_username": "jdoe",
        "twitter_handle": None,
        "personal_website": None,
        "full_name": "John Doe",
    }
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "user": {"details": "ML researcher. Find me @jdoe_x and https://johndoe.dev"}
    }
    with patch("scripts.contact_enricher.httpx.get", return_value=mock_resp):
        result = enrich_from_huggingface([contact])

    assert len(result) == 1
    assert result[0]["twitter_handle"] == "jdoe_x"
    assert result[0]["personal_website"] == "https://johndoe.dev"


def test_enrich_from_huggingface_skips_contacts_without_username():
    from scripts.contact_enricher import enrich_from_huggingface

    contact = {"hf_username": None, "full_name": "John Doe"}
    result = enrich_from_huggingface([contact])
    assert result == []


# ── Orchestrator ───────────────────────────────────────────────────────────


def test_run_calls_all_steps_in_order(mocker):
    from scripts.contact_enricher import run

    mock_store = mocker.MagicMock()
    mocker.patch("scripts.contact_enricher.SupabaseStore", return_value=mock_store)

    contacts = [
        {
            "company_domain": "radai.com",
            "full_name": "John Doe",
            "first_name": "John",
            "last_name": "Doe",
            "email": None,
            "github_username": None,
            "hf_username": None,
        }
    ]
    mocker.patch("scripts.contact_enricher.list_contacts", return_value=contacts)
    mock_upsert = mocker.patch("scripts.contact_enricher.upsert_contact")
    mocker.patch("scripts.contact_enricher.enrich_from_github", return_value=[])
    mocker.patch("scripts.contact_enricher.enrich_from_huggingface", return_value=[])

    run("radai.com", skip_hunter=True)

    # upsert must have been called at least once (for the guessed email)
    assert mock_upsert.called
    upserted = mock_upsert.call_args_list[0][0][1]
    assert upserted["email_status"] == "guessed"
