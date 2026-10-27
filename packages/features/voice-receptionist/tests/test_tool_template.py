import json

import pytest

from clinic_voice_receptionist.tools import template
from clinic_voice_receptionist.tools.template import TemplateError, inspect, render

ENDPOINT = "https://api.example.com/patients/{{field.phone}}/notes?call={{call.id}}"
TEMPLATE = {
    "patient": {"name": "{{field.name}}", "age": "{{field.age}}"},
    "note": "Wants {{arg.reason}} - {{field.name}}",
    "source": "voice",
    "extra": "{{arg.extra}}",
}


def test_inspect_lists_every_placeholder_in_the_body_and_the_endpoint():
    used = inspect(TEMPLATE, ENDPOINT)
    assert used.fields == {"name", "age", "phone"} and used.args == {"reason", "extra"} and used.call == {"id"}


@pytest.mark.parametrize(
    ("body", "endpoint", "fragment"),
    [
        ({"a": "{{field.x"}, "https://a.example.com", "not a placeholder"),
        ({"a": "{{whatever.x}}"}, "https://a.example.com", "not a placeholder"),
        ({"{{field.x}}": "v"}, "https://a.example.com", "not in names"),
        ({"a": "{{call.secret}}"}, "https://a.example.com", "Unknown call detail"),
        ({"a": "b"}, "https://{{field.host}}.example.com/x", "host name"),
        ({"a": "b"}, "https://api.example.com{{field.path}}", "host name"),
        (["a"], "https://a.example.com", "JSON object"),
    ],
)
def test_bad_templates_are_refused_with_a_message(body, endpoint, fragment):
    with pytest.raises(TemplateError, match=fragment):
        inspect(body, endpoint)


def test_values_keep_their_type_when_alone_and_become_text_inside_a_sentence():
    fields = {"name": 'Sam "the man" O\'Neil\n', "age": 42, "phone": "+14155550123"}
    out = render(TEMPLATE, ENDPOINT, fields=fields, args={"reason": "Botox"}, call={"id": "c1"})
    assert out.body["patient"] == {"name": fields["name"], "age": 42}
    assert out.body["note"] == f"Wants Botox - {fields['name']}" and out.body["source"] == "voice"
    assert "extra" not in out.body  # an argument the model left out is dropped, not sent as null
    json.dumps(out.body)  # the structure is always valid JSON, whatever the values contain


def test_endpoint_values_are_url_encoded_and_cannot_change_the_address():
    nasty = "../../admin?x=1#@evil.com/"
    out = render(None, ENDPOINT, fields={"phone": nasty}, args={}, call={"id": "c 1"})
    assert out.endpoint == "https://api.example.com/patients/" + template.quote(nasty, safe="") + "/notes?call=c%201"
    assert out.body is None
    assert "evil.com" not in out.endpoint.split("/")[2]


def test_an_argument_the_url_needs_but_the_model_did_not_give_is_reported():
    out = render(None, "https://api.example.com/a/{{arg.id}}", fields={}, args={}, call={})
    assert out.missing_args == ["id"]


def test_the_model_is_only_asked_for_arguments_the_template_uses():
    schema = {
        "type": "object",
        "properties": {"reason": {"type": "string"}, "extra": {"type": "string"}, "unused": {"type": "string"}},
        "required": ["reason", "unused"],
    }
    shown = template.model_schema(schema, inspect(TEMPLATE, ENDPOINT))
    assert sorted(shown["properties"]) == ["extra", "reason"] and shown["required"] == ["reason"]
