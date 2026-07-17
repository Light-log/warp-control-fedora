import pytest

from warp_control.domains import expand_host_rule, normalize_host, parse_hosts


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("https://Example.COM/path?q=1#fragment", "example.com"),
        ("example.COM", "example.com"),
        ("https://user:secret@Example.com:8443/path", "example.com"),
        ("*.crm.example.com", "crm.example.com"),
        ("Example.com.", "example.com"),
        ("https://münich.example/path", "xn--mnich-kva.example"),
    ],
)
def test_normalize_host_returns_canonical_ascii_host(value, expected):
    assert normalize_host(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "/only/a/path",
        "https:///missing-host",
        "127.0.0.1",
        "https://[2001:db8::1]/",
        "bad_label.example",
        "-bad.example",
        "bad-.example",
        "two..dots.example",
        "example .com",
        "example.com\nmalicious.test",
        "**.example.com",
        "localhost",
    ],
)
def test_normalize_host_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        normalize_host(value)


def test_expand_host_rule_returns_immutable_exact_rule():
    assert expand_host_rule("Example.com", include_subdomains=False) == (
        "example.com",
    )


def test_expand_host_rule_returns_exact_then_wildcard_for_subdomains():
    assert expand_host_rule("Example.com", include_subdomains=True) == (
        "example.com",
        "*.example.com",
    )


def test_parse_hosts_normalizes_deduplicates_sorts_and_ignores_noise():
    output = """
    Excluded routes:
      Example.com
      *.sub.Example.com
      https://münich.example/path
      example.com
      not_a_host
      192.0.2.1
    """

    assert parse_hosts(output) == (
        "example.com",
        "sub.example.com",
        "xn--mnich-kva.example",
    )


def test_parse_hosts_accepts_arbitrary_whitespace():
    assert parse_hosts("beta.example\talpha.example\n beta.example") == (
        "alpha.example",
        "beta.example",
    )
