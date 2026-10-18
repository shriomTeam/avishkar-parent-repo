import pytest

from clinic_voice_receptionist.tools.schema import SchemaError, check_args, to_gemini, validate_definition

SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "Full name"},
        "age": {"type": "integer", "minimum": 0, "maximum": 120},
        "service": {"type": "string", "enum": ["botox", "filler"]},
        "wants_text": {"type": "boolean"},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["name"],
}


def test_a_supported_schema_is_accepted_and_translated_for_gemini():
    validate_definition(SCHEMA)
    gemini = to_gemini(SCHEMA)
    assert gemini["type"] == "OBJECT" and gemini["required"] == ["name"]
    assert gemini["properties"]["age"] == {"type": "INTEGER", "minimum": 0, "maximum": 120}
    assert gemini["properties"]["service"]["enum"] == ["botox", "filler"]
    assert gemini["properties"]["tags"]["items"] == {"type": "STRING"}


@pytest.mark.parametrize(
    ("schema", "fragment"),
    [
        ("nope", "JSON object"),
        ({"type": "array", "properties": {}}, "JSON object"),
        ({"type": "object"}, "JSON object"),
        ({"type": "object", "properties": {"a": {"type": "string", "$ref": "#/x"}}}, r"\$ref"),
        ({"type": "object", "properties": {"a": {"type": "string", "oneOf": []}}}, "oneOf"),
        ({"type": "object", "properties": {"a": {"type": "date"}}}, "type must be one of"),
        ({"type": "object", "properties": {"a": {"type": "string"}}, "required": ["b"]}, "required"),
        ({"type": "object", "properties": {"a": {"type": "string", "enum": []}}}, "enum"),
        ({"type": "object", "properties": {"a": {"type": "array"}}}, "items"),
        ({"type": "object", "properties": {"a": {"type": "string", "items": {"type": "string"}}}}, "items only"),
        ({"type": "object", "properties": {"a": {"type": "integer", "minimum": "1"}}}, "minimum"),
        ({"type": "object", "properties": {f"p{i}": {"type": "string"} for i in range(21)}}, "at most"),
        (
            {"type": "object", "properties": {"a": {"type": "object", "properties": {"b": {"type": "object",
             "properties": {"c": {"type": "object", "properties": {}}}}}}}},
            "deeper",
        ),
    ],
)  # fmt: skip
def test_unsupported_schemas_are_rejected_with_a_message_naming_the_problem(schema, fragment):
    with pytest.raises(SchemaError, match=fragment):
        validate_definition(schema)


def test_arguments_are_checked_and_unknown_names_dropped():
    cleaned, errors = check_args(SCHEMA, {"name": "Sam", "age": 30, "service": "botox", "extra": "x"})
    assert errors == {} and cleaned == {"name": "Sam", "age": 30, "service": "botox"}


def test_bad_arguments_are_reported_by_name():
    _, errors = check_args(SCHEMA, {"age": 200, "service": "laser", "wants_text": "yes", "tags": ["a", 1]})
    assert errors == {
        "name": "is required",
        "age": "must be at most 120",
        "service": "must be one of: botox, filler",
        "wants_text": "must be a boolean",
        "tags[1]": "must be a string",
    }


def test_booleans_are_not_numbers_and_empty_required_values_count_as_missing():
    _, errors = check_args(SCHEMA, {"name": "", "age": True})
    assert errors == {"name": "is required", "age": "must be an integer"}
