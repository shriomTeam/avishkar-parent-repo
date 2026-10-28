import pytest

from clinic_voice_receptionist.tools.builtin import BUILTINS
from clinic_voice_receptionist.tools.fill import fill_args, match_fields, model_schema

LEAD = BUILTINS["create_lead"].schema


def _field(key, data_type="text", required=False):
    return {"key": key, "label": key.title(), "data_type": data_type, "required": required}


def _keys(fields):
    return {arg: m["key"] for arg, m in match_fields(LEAD, fields).items()}


def test_a_field_named_like_the_argument_fills_it():
    assert _keys([_field("first_name"), _field("interest")]) == {"first_name": "first_name", "interest": "interest"}


def test_the_only_phone_or_email_field_fills_that_argument_whatever_its_name():
    fields = [_field("mobile", "phone"), _field("contact_email", "email")]
    assert _keys(fields) == {"phone": "mobile", "email": "contact_email"}


def test_two_phone_fields_fill_nothing_unless_one_is_named_phone():
    two = [_field("mobile", "phone"), _field("work_number", "phone")]
    assert _keys(two) == {}
    assert _keys([*two, _field("phone", "phone")]) == {"phone": "phone"}


def test_a_field_of_the_wrong_type_never_fills_an_argument():
    assert _keys([_field("phone", "text"), _field("email", "text")]) == {}


def test_text_arguments_are_not_matched_by_type_alone():
    assert _keys([_field("caller_name"), _field("reason")]) == {}


def test_filled_arguments_are_hidden_from_the_model():
    filled = match_fields(LEAD, [_field("phone", "phone"), _field("first_name")])
    assert sorted(model_schema(LEAD, filled)["properties"]) == ["email", "interest", "last_name"]


def test_captured_values_win_and_missing_required_ones_are_reported():
    filled = match_fields(LEAD, [_field("phone", "phone", required=True), _field("email", "email")])
    merged, missing = fill_args({"phone": "wrong", "interest": "Botox"}, filled, {"phone": "+14155550123"})
    assert merged == {"phone": "+14155550123", "interest": "Botox"} and missing == []
    merged, missing = fill_args({"phone": "wrong"}, filled, {})
    assert merged == {} and missing == ["Phone"]  # optional email missing: left out, not reported


@pytest.mark.parametrize("name", ["search_knowledge"])
def test_tools_without_matching_arguments_are_untouched(name):
    assert match_fields(BUILTINS[name].schema, [_field("query")]) == {}
