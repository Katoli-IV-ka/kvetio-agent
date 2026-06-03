import pytest

from normalize import normalize_company_name, normalize_domain


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://www.acme.ai/about", "acme.ai"),
        ("http://ACME.AI", "acme.ai"),
        ("acme.ai", "acme.ai"),
        ("research.acme.ai/team", "acme.ai"),
        ("https://foo.bar.co.uk", "bar.co.uk"),
        ("  https://www.example.com/  ", "example.com"),
    ],
)
def test_normalize_domain_ok(raw: str, expected: str) -> None:
    assert normalize_domain(raw) == expected


@pytest.mark.parametrize("bad", ["", "   ", "not-a-url", "http://"])
def test_normalize_domain_invalid(bad: str) -> None:
    with pytest.raises(ValueError):
        normalize_domain(bad)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Acme, Inc.", "acme"),
        ("The Acme Corporation", "acme"),
        ("Foo Bar GmbH", "foo bar"),
        ("BAZ LLC", "baz"),
    ],
)
def test_normalize_company_name(raw: str, expected: str) -> None:
    assert normalize_company_name(raw) == expected
