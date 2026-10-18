import socket

import pytest

from clinic_voice_receptionist.tools.netguard import BlockedTarget, parse_url, resolve


def test_a_normal_https_url_is_accepted():
    target = parse_url("https://api.example.com/v1/leads?x=1")
    assert (target.scheme, target.host, target.port, target.path_and_query) == (
        "https", "api.example.com", 443, "/v1/leads?x=1",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("url", "fragment"),
    [
        ("http://api.example.com/x", "HTTPS"),
        ("ftp://api.example.com/x", "HTTPS"),
        ("https://user:pass@api.example.com/x", "auth header"),
        ("https://api.example.com:8443/x", "443"),
        ("https:///x", "host"),
        ("https://localhost/x", "not a public"),
        ("https://printer.local/x", "not a public"),
        ("https://metadata.google.internal/x", "not a public"),
        ("https://intranet/x", "not a public"),
        ("https://127.0.0.1/x", "not public"),
        ("https://10.0.0.5/x", "not public"),
        ("https://192.168.1.10/x", "not public"),
        ("https://172.16.0.1/x", "not public"),
        ("https://169.254.169.254/computeMetadata/v1/", "not public"),
        ("https://100.64.0.1/x", "not public"),
        ("https://[::1]/x", "not public"),
        ("https://[fd00::1]/x", "not public"),
        ("https://[::ffff:127.0.0.1]/x", "not public"),
        ("https://0.0.0.0/x", "not public"),
    ],
)
def test_internal_and_unsafe_urls_are_refused(url, fragment):
    with pytest.raises(BlockedTarget, match=fragment):
        parse_url(url)


def test_private_hosts_can_be_allowed_for_development_only():
    assert parse_url("http://127.0.0.1:8001/echo", allow_private=True).port == 8001


def _answers(monkeypatch, *addresses: str):
    def fake(host, port, *args, **kwargs):
        return [
            (socket.AF_INET6 if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in addresses
        ]

    monkeypatch.setattr(socket, "getaddrinfo", fake)


async def test_a_name_that_resolves_to_public_addresses_is_allowed(monkeypatch):
    _answers(monkeypatch, "93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946")
    assert await resolve(parse_url("https://api.example.com/x")) == "93.184.216.34"


@pytest.mark.parametrize("answer", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1", "::ffff:10.0.0.1"])
async def test_a_name_that_points_inside_is_refused(monkeypatch, answer):
    _answers(monkeypatch, answer)
    with pytest.raises(BlockedTarget, match="non-public"):
        await resolve(parse_url("https://evil.example.com/x"))


async def test_one_private_answer_among_public_ones_is_still_refused(monkeypatch):
    _answers(monkeypatch, "93.184.216.34", "10.0.0.8")
    with pytest.raises(BlockedTarget, match="non-public"):
        await resolve(parse_url("https://mixed.example.com/x"))


async def test_a_name_that_does_not_resolve_is_reported(monkeypatch):
    def boom(*args, **kwargs):
        raise socket.gaierror("nope")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    with pytest.raises(BlockedTarget, match="could not be found"):
        await resolve(parse_url("https://nothing.example.com/x"))
