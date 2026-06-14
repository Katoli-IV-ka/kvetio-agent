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
