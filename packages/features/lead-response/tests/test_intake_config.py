"""The one setting intake adds. Pure tests: no database, no network."""

import pytest

from clinic_lead_response.config import IntakeSettings, get_intake_settings


def make(value: str | None, monkeypatch) -> IntakeSettings:
    monkeypatch.delenv("LEAD_RESPONSE_PUBLIC_API_URL", raising=False)
    if value is not None:
        monkeypatch.setenv("LEAD_RESPONSE_PUBLIC_API_URL", value)
    return IntakeSettings(_env_file=None)


def test_unset_means_intake_is_off(monkeypatch):
    assert make(None, monkeypatch).public_base is None


@pytest.mark.parametrize(
    ("value", "base"),
    [
        ("https://prod-avishkar-api-123.us-central1.run.app", "https://prod-avishkar-api-123.us-central1.run.app"),
        ("https://prod-avishkar-api-123.us-central1.run.app/", "https://prod-avishkar-api-123.us-central1.run.app"),
        ("  https://api.example.test  ", "https://api.example.test"),
        ("http://localhost:8000", "http://localhost:8000"),
        ("https://abc.ngrok-free.app", "https://abc.ngrok-free.app"),
    ],
)
def test_a_plain_address_is_kept_without_the_trailing_slash(value, base, monkeypatch):
    assert make(value, monkeypatch).public_base == base


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "api.example.test",
        "ftp://api.example.test",
        "https://",
        "https://api.example.test/features",
        "https://api.example.test/?a=1",
        "https://api.example.test#x",
        "https://user:pw@api.example.test",
        "https://api.example.test:notaport",
        "not a url",
    ],
)
def test_anything_else_switches_intake_off(value, monkeypatch):
    assert make(value, monkeypatch).public_base is None


def test_the_cached_accessor_reads_the_environment(monkeypatch):
    monkeypatch.setenv("LEAD_RESPONSE_PUBLIC_API_URL", "https://cached.example.test")
    get_intake_settings.cache_clear()
    try:
        assert get_intake_settings().public_base == "https://cached.example.test"
    finally:
        get_intake_settings.cache_clear()
