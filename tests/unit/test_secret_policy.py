"""ADR 0001: the pure secret-policy rules and how destinations are read."""

from __future__ import annotations

import httpx
import pytest

from activities.browser import PlaywrightRobotActivity
from activities.network import EmailActivity, HttpRequestActivity, SftpActivity
from activities.sql import SqlQueryActivity
from app.domain.destinations import destination_host
from app.domain.secret_policy import (
    SecretPolicy,
    check_use,
    host_matches,
    placement_violations,
    valid_host_pattern,
)


@pytest.mark.parametrize(
    ("host", "pattern", "expected"),
    [
        ("api.example.com", "api.example.com", True),
        ("API.Example.COM.", "api.example.com", True),
        ("a.example.com", "*.example.com", True),
        ("a.b.example.com", "*.example.com", True),
        ("example.com", "*.example.com", False),
        ("badexample.com", "*.example.com", False),
        ("example.com.evil.net", "*.example.com", False),
        ("api.example.com", "example.com", False),
        ("::1", "[::1]", True),
        ("10.0.0.5", "10.0.0.5", True),
        ("", "api.example.com", False),
    ],
)
def test_host_matching_is_exact_or_subdomains_only(host: str, pattern: str, expected: bool) -> None:
    assert host_matches(host, pattern) is expected


@pytest.mark.parametrize(
    ("pattern", "valid"),
    [
        ("api.example.com", True),
        ("*.example.com", True),
        ("10.1.2.3", True),
        ("[fd00::1]", True),
        ("*.com", False),
        ("*", False),
        ("a*.example.com", False),
        ("api.example.com/path", False),
        ("https://api.example.com", False),
        ("-bad.example.com", False),
        ("", False),
    ],
)
def test_host_patterns_are_validated(pattern: str, valid: bool) -> None:
    assert valid_host_pattern(pattern) is valid


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.com\\@evil.example.net/",
        "http://evil.example.net#@api.example.com",
        "http://api.example.com@evil.example.net/",
        "https://EVIL.example.net./x",
        "http://[::1]:8080/",
        "http://0x7f.1/",
        "http://bücher.example/",
    ],
)
def test_url_hosts_are_read_with_the_parser_the_client_connects_with(url: str) -> None:
    """Whatever host httpx would connect to is the host the policy is checked against."""
    expected = httpx.URL(url).raw_host.decode("ascii").lower().rstrip(".")
    assert destination_host(url) == expected


@pytest.mark.parametrize(
    ("value", "host"),
    [
        (None, None),
        ("", None),
        ("   ", None),
        ("/portal/login", None),
        ("{{ inputs.url }}", ""),
        ("https://{{ secret:x }}/", ""),
        ("ftp://", ""),
        (42, ""),
        ("sftp.example.com", "sftp.example.com"),
        ("SFTP.Example.com.", "sftp.example.com"),
        ("bad host name", ""),
        ("user@host.example.com", ""),
        ("10.0.0.7", "10.0.0.7"),
    ],
)
def test_destination_values_that_cannot_be_read_refuse(value: object, host: str | None) -> None:
    assert destination_host(value) == host


def test_destinations_follow_the_operation_and_the_input_defaults() -> None:
    # Email: SMTP connects only to smtp_host (default localhost); Graph only to its two hosts.
    assert EmailActivity.destination_hosts({"to": ["a@b.c"], "subject": "s"}) == ["localhost"]
    assert EmailActivity.destination_hosts({"provider": "graph"}) == [
        "graph.microsoft.com",
        "login.microsoftonline.com",
    ]
    assert HttpRequestActivity.destination_hosts({"url": "https://api.example.com/x"}) == [
        "api.example.com"
    ]
    assert SftpActivity.destination_hosts({"host": "files.example.com"}) == ["files.example.com"]
    # The robot: a relative login_url belongs to base_url; OTP hosts only for form_otp.
    robot = PlaywrightRobotActivity.destination_hosts(
        {"operation": "form", "base_url": "https://portal.example.com", "login_url": "/login"}
    )
    assert robot == ["portal.example.com"]
    otp = PlaywrightRobotActivity.destination_hosts(
        {"operation": "form_otp", "base_url": "https://portal.example.com"}
    )
    assert otp == ["portal.example.com", "graph.microsoft.com", "login.microsoftonline.com"]
    # A database's address is inside its secret, so it has no destination input.
    assert SqlQueryActivity.destination_hosts({"sql": "SELECT 1"}) is None


def test_literal_only_skips_references_until_dispatch() -> None:
    values = {"url": "{{ inputs.target }}"}
    assert HttpRequestActivity.destination_hosts(values) == [""]
    assert HttpRequestActivity.destination_hosts(values, literal_only=True) == []


def test_placement_allows_secrets_in_credential_inputs_only() -> None:
    inputs = {
        "url": "https://api.example.com",
        "bearer_token": "{{ secret:a }}",
        "headers": {"X-Key": "k {{ secret:b }}"},
        "body": "x {{ secret:c }}",
    }
    found = placement_violations(inputs, "{{ secret:d }}", ("bearer_token", "headers"))
    assert found == ["input 'body'", "foreach"]


POLICY = SecretPolicy("api_key", allowed_hosts=("api.example.com",), environments=("dev",))


def test_rules_two_and_three_refuse_and_name_the_secret_and_the_setting() -> None:
    policies = {"api_key": POLICY}
    ok = check_use(["api_key"], policies, environment="dev", destinations=["api.example.com"])
    assert ok.allowed
    host = check_use(["api_key"], policies, environment="dev", destinations=["127.0.0.1"])
    assert not host.allowed and "127.0.0.1" in host.refusals[0]
    assert "allowed hosts" in host.refusals[0]
    env = check_use(["api_key"], policies, environment="prod", destinations=["api.example.com"])
    assert not env.allowed and "environments" in env.refusals[0]
    unread = check_use(["api_key"], policies, environment="dev", destinations=[""])
    assert not unread.allowed and "could not be read" in unread.refusals[0]
    missing = check_use(["other"], policies, environment="dev", destinations=None)
    assert not missing.allowed and "no policy" in missing.refusals[0]


def test_empty_policies_refuse_and_no_destination_checks_only_the_environment() -> None:
    empty = {"k": SecretPolicy("k")}
    assert not check_use(["k"], empty, environment="dev", destinations=None).allowed
    local = {"k": SecretPolicy("k", environments=("dev",))}
    assert check_use(["k"], local, environment="dev", destinations=None).allowed
    assert not check_use(["k"], local, environment="dev", destinations=["a.example.com"]).allowed
    # A save checks hosts only: the environment is known at dispatch.
    assert check_use(["k"], local, environment=None, destinations=None).allowed
