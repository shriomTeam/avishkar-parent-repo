"""The engine switch. Pure tests: no database, no network."""

import pytest

from clinic_lead_response.config import IntakeSettings, get_intake_settings


def make(value: str | None, monkeypatch) -> IntakeSettings:
    monkeypatch.delenv("LEAD_RESPONSE_ENGINE_ENABLED", raising=False)
    if value is not None:
        monkeypatch.setenv("LEAD_RESPONSE_ENGINE_ENABLED", value)
    return IntakeSettings(_env_file=None)


def test_the_engine_is_off_unless_it_is_switched_on(monkeypatch):
    assert make(None, monkeypatch).engine_enabled is False


@pytest.mark.parametrize("value", ["true", "TRUE", "True", "1", "yes", "YES", "on", "On", " true ", "\ttrue\n"])
def test_a_true_word_switches_it_on(value, monkeypatch):
    assert make(value, monkeypatch).engine_enabled is True


@pytest.mark.parametrize(
    "value", ["", " ", "false", "0", "no", "off", "none", "null", "2", "enabled", "tru", "truee", "yes please", "-1"]
)
def test_anything_else_leaves_it_off_and_never_raises(value, monkeypatch):
    assert make(value, monkeypatch).engine_enabled is False


def test_the_switch_is_separate_from_the_public_address(monkeypatch):
    monkeypatch.setenv("LEAD_RESPONSE_PUBLIC_API_URL", "https://api.example.test")
    settings = make(None, monkeypatch)
    assert settings.public_base == "https://api.example.test" and settings.engine_enabled is False
    monkeypatch.setenv("LEAD_RESPONSE_PUBLIC_API_URL", "")
    assert make("true", monkeypatch).public_base is None and make("true", monkeypatch).engine_enabled is True


def test_it_can_be_given_as_a_value_directly():
    assert IntakeSettings(_env_file=None, engine_enabled=True).engine_enabled is True
    assert IntakeSettings(_env_file=None, engine_enabled=False).engine_enabled is False
    assert IntakeSettings(_env_file=None, engine_enabled="maybe").engine_enabled is False


def test_the_cached_accessor_reads_the_environment(monkeypatch):
    monkeypatch.setenv("LEAD_RESPONSE_ENGINE_ENABLED", "true")
    get_intake_settings.cache_clear()
    try:
        assert get_intake_settings().engine_enabled is True
    finally:
        get_intake_settings.cache_clear()
