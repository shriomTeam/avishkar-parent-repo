"""The settings page mirrors the server's rules in the browser (the server's 422 names no field), so the browser's
copy must not drift. web/lib/limits.json holds the numbers the form uses, and web/unit/fixtures/rule-cases.json holds
cases that both sides run: this file runs them through the model, web/unit/rules.test.ts runs them through the form.
"""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from clinic_lead_response.settings_model import (
    ACK_MAX_LENGTH,
    DAYS,
    MAX_WINDOWS_PER_DAY,
    LeadResponseSettings,
)

WEB = Path(__file__).resolve().parents[1] / "web"
LIMITS = json.loads((WEB / "lib" / "limits.json").read_text())
CASES_FILE = json.loads((WEB / "unit" / "fixtures" / "rule-cases.json").read_text())


def expand(value):
    """{"$repeat": [text, times]} stands for a long string, so the file need not hold a 321-character message."""
    if isinstance(value, list):
        return [expand(v) for v in value]
    if isinstance(value, dict):
        if "$repeat" in value:
            text, times = value["$repeat"]
            return text * times
        return {k: expand(v) for k, v in value.items()}
    return value


CASES = CASES_FILE["cases"]
PROPERTIES = LeadResponseSettings.model_json_schema()["properties"]


def test_the_cases_start_from_the_servers_own_defaults():
    assert CASES_FILE["base"] == LeadResponseSettings().model_dump(mode="json")


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_the_model_agrees_with_the_shared_case(case):
    body = {**CASES_FILE["base"], **expand(case["set"])}
    if case["valid"]:
        LeadResponseSettings.model_validate(body)
    else:
        with pytest.raises(ValidationError):
            LeadResponseSettings.model_validate(body)


def test_the_case_ids_are_unique():
    assert len({c["id"] for c in CASES}) == len(CASES)


@pytest.mark.parametrize("name", ["holding_minutes", "sla_minutes"])
def test_the_number_bounds_equal_the_models(name):
    assert LIMITS[name]["min"] == PROPERTIES[name]["minimum"]
    assert LIMITS[name]["max"] == PROPERTIES[name]["maximum"]


def test_the_other_limits_equal_the_models():
    assert LIMITS["ack_text"]["max_length"] == ACK_MAX_LENGTH
    assert LIMITS["ack_text"]["min_length"] == 1
    assert LIMITS["windows_per_day"] == MAX_WINDOWS_PER_DAY
    assert LIMITS["days"] == list(DAYS)
    assert sorted(LIMITS["escalation_roles"]) == sorted(PROPERTIES["escalation_role"]["enum"])


def test_the_limits_file_holds_exactly_what_the_form_reads():
    assert set(LIMITS) == {"holding_minutes", "sla_minutes", "ack_text", "windows_per_day", "days", "escalation_roles"}


@pytest.mark.parametrize(
    ("key", "field", "other"),
    [
        ("holding_minutes", "holding_minutes", {"sla_minutes": 240}),
        ("sla_minutes", "sla_minutes", {"holding_minutes": 5}),
    ],
)
def test_the_models_edges_are_where_the_file_says(key, field, other):
    low, high = LIMITS[key]["min"], LIMITS[key]["max"]
    for ok in (low, high):
        LeadResponseSettings(**{field: ok, **other})
    for bad in (low - 1, high + 1):
        with pytest.raises(ValidationError):
            LeadResponseSettings(**{field: bad, **other})
