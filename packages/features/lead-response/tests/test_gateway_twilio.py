"""The Twilio adapter, against a fake Twilio (httpx.MockTransport). No test here can reach the real network."""

import base64
import logging
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest

import clinic_lead_response.gateway.provider as provider_module
import clinic_lead_response.gateway.twilio as twilio_module
from clinic_lead_response.gateway.provider import (
    GlobalNumberResolver,
    NotConfiguredProvider,
    ProviderRequest,
)
from clinic_lead_response.gateway.retry import ErrorKind
from clinic_lead_response.gateway.twilio import TwilioProvider, build_default_provider

SID = "ACtest0000000000000000000000000000"
TOKEN = "tokentokentoken-secret-0000"
BODY = "Zebra-Quartz sentinel wording that must never be logged"
TO = "+14155550142"
FROM = "+14155550100"


def request(**kw):
    values = {
        "to": TO,
        "from_number": FROM,
        "body": BODY,
        "message_id": uuid.uuid4(),
        "attempt": 1,
        "trace_id": uuid.uuid4(),
    }
    return ProviderRequest(**{**values, **kw})


def provider(handler):
    return TwilioProvider(SID, TOKEN, transport=httpx.MockTransport(handler))


def reply(http_status, /, **json):
    return lambda req: httpx.Response(http_status, json=json)


async def send(handler, **kw):
    return await provider(handler).send(request(**kw))


# --- what is sent --------------------------------------------------------------------------------------------------


async def test_the_request_is_a_form_post_to_the_messages_endpoint_with_basic_auth():
    seen = []

    def handler(req):
        seen.append(req)
        return httpx.Response(201, json={"sid": "SM1", "status": "queued"})

    await send(handler)
    (req,) = seen
    assert req.method == "POST" and str(req.url) == f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json"
    assert req.headers["authorization"] == "Basic " + base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    assert req.headers["content-type"].startswith("application/x-www-form-urlencoded")
    form = parse_qs(req.content.decode())
    assert form == {"To": [TO], "From": [FROM], "Body": [BODY]}


async def test_the_status_callback_is_sent_only_when_there_is_one():
    forms = []

    def handler(req):
        forms.append(parse_qs(req.content.decode()))
        return httpx.Response(201, json={"sid": "SM1", "status": "queued"})

    await send(handler)
    await send(handler, status_callback_url="https://example.test/in/sms/t/status?m=1")
    assert "StatusCallback" not in forms[0]
    assert forms[1]["StatusCallback"] == ["https://example.test/in/sms/t/status?m=1"]


async def test_the_body_is_form_encoded_so_odd_text_survives():
    forms = []

    def handler(req):
        forms.append(parse_qs(req.content.decode()))
        return httpx.Response(201, json={"sid": "SM1", "status": "queued"})

    await send(handler, body="Café & more = 100% – line\nbreak")
    assert forms[0]["Body"] == ["Café & more = 100% – line\nbreak"]


# --- what comes back -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize("status", [200, 201])
async def test_an_accepted_message_returns_its_sid_and_status(status):
    result = await send(reply(status, sid="SM123", status="queued"))
    assert result.accepted and result.provider_message_id == "SM123" and result.provider_status == "queued"
    assert result.error is None


@pytest.mark.parametrize(
    ("status", "code", "kind"),
    [
        (400, 21610, ErrorKind.OPT_OUT),
        (400, 21211, ErrorKind.INVALID_NUMBER),
        (400, 21614, ErrorKind.INVALID_NUMBER),
        (400, 21214, ErrorKind.INVALID_NUMBER),
        (400, 21217, ErrorKind.INVALID_NUMBER),
        (401, 20003, ErrorKind.CONFIG),
        (429, 20429, ErrorKind.RETRYABLE),
        (400, 21611, ErrorKind.RETRYABLE),
        (400, 21408, ErrorKind.PERMANENT),
        (400, 21612, ErrorKind.PERMANENT),
        (400, 21619, ErrorKind.PERMANENT),
        (400, 21212, ErrorKind.PERMANENT),
        (400, 99999, ErrorKind.PERMANENT),
    ],
)
async def test_twilio_error_codes_are_classified(status, code, kind):
    result = await send(reply(status, code=code, message="a number +14155550142 is bad", status=status))
    assert not result.accepted
    assert result.error.kind is kind and result.error.code == str(code) and result.error.http_status == status


async def test_twilios_error_text_is_dropped_because_it_can_echo_numbers():
    result = await send(reply(400, code=21211, message=f"The 'To' number {TO} is not valid"))
    assert TO not in repr(result) and "not valid" not in repr(result)


@pytest.mark.parametrize("status", [500, 502, 503, 504])
async def test_a_server_error_without_a_body_is_ambiguous_not_retryable(status):
    result = await send(lambda req: httpx.Response(status, text="oops"))
    assert result.error.kind is ErrorKind.AMBIGUOUS and result.error.code == f"http_{status}"


async def test_a_429_without_a_twilio_code_is_retryable_and_keeps_retry_after():
    result = await send(lambda req: httpx.Response(429, text="slow down", headers={"Retry-After": "12"}))
    assert result.error.kind is ErrorKind.RETRYABLE and result.error.retry_after == 12.0


@pytest.mark.parametrize(("header", "expected"), [("30", 30.0), ("0", 0.0), ("abc", None), ("-5", None), (None, None)])
async def test_retry_after_is_read_defensively(header, expected):
    headers = {} if header is None else {"Retry-After": header}
    result = await send(lambda req: httpx.Response(429, json={"code": 20429}, headers=headers))
    assert result.error.retry_after == expected


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404, text="not found"),
        httpx.Response(400, json=["not", "a", "dict"]),
        httpx.Response(400, json={"code": True}),
        httpx.Response(400, json={"code": "21610"}),
        httpx.Response(400, content=b"\xff\xfe not json"),
    ],
)
async def test_an_unreadable_or_odd_error_body_is_a_permanent_failure_never_a_crash(response):
    result = await send(lambda req: response)
    assert not result.accepted and result.error.kind is ErrorKind.PERMANENT


async def test_a_201_without_a_sid_is_not_treated_as_accepted():
    result = await send(reply(201, status="queued"))
    assert not result.accepted


# --- transport failures --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exception", "kind", "code"),
    [
        (httpx.ConnectError("no route"), ErrorKind.RETRYABLE, "connect_error"),
        (httpx.ConnectTimeout("slow"), ErrorKind.RETRYABLE, "connect_error"),
        (httpx.PoolTimeout("busy"), ErrorKind.RETRYABLE, "connect_error"),
        (httpx.ReadTimeout("silent"), ErrorKind.AMBIGUOUS, "timeout"),
        (httpx.WriteTimeout("stuck"), ErrorKind.AMBIGUOUS, "timeout"),
        (httpx.ReadError("reset"), ErrorKind.AMBIGUOUS, "broken_connection"),
        (httpx.RemoteProtocolError("cut off"), ErrorKind.AMBIGUOUS, "broken_connection"),
    ],
)
async def test_network_failures_never_raise_and_say_whether_the_message_may_exist(exception, kind, code):
    def handler(req):
        raise exception

    result = await send(handler)
    assert not result.accepted and result.error.kind is kind and result.error.code == code


# --- secrets and logs ------------------------------------------------------------------------------------------------


def test_the_credentials_never_appear_in_the_providers_repr():
    text = repr(provider(reply(201, sid="SM1")))
    assert TOKEN not in text and SID not in text


async def test_nothing_personal_or_secret_is_logged_by_a_send(caplog):
    with caplog.at_level(logging.DEBUG):
        await send(reply(201, sid="SM1", status="queued"))
        await send(reply(400, code=21610, message=f"blocked {TO}"))
    for secret in (BODY, TO, TO[-10:], TOKEN):
        assert secret not in caplog.text


# --- reading the platform's global settings ------------------------------------------------------------------------


def settings(**kw):
    values = {
        "messaging_provider": "twilio",
        "twilio_account_sid": SID,
        "twilio_auth_token": TOKEN,
        "twilio_from_number": FROM,
    }
    return SimpleNamespace(**{**values, **kw})


def test_twilio_is_used_only_when_the_platform_is_set_up_for_it(monkeypatch):
    monkeypatch.setattr(twilio_module, "get_settings", lambda: settings())
    assert isinstance(build_default_provider(), TwilioProvider)


@pytest.mark.parametrize(
    "overrides",
    [{"messaging_provider": "console"}, {"twilio_account_sid": ""}, {"twilio_auth_token": ""}],
)
def test_anything_less_is_a_provider_that_fails_every_attempt(monkeypatch, overrides):
    monkeypatch.setattr(twilio_module, "get_settings", lambda: settings(**overrides))
    assert isinstance(build_default_provider(), NotConfiguredProvider)


async def test_the_not_configured_provider_never_pretends_to_send():
    result = await NotConfiguredProvider().send(request())
    assert (
        not result.accepted and result.error.kind is ErrorKind.CONFIG and result.error.code == "provider_not_configured"
    )


async def test_the_global_number_resolver_returns_the_platform_number(monkeypatch):
    monkeypatch.setattr(provider_module, "get_settings", lambda: settings())
    assert await GlobalNumberResolver().resolve(uuid.uuid4(), uuid.uuid4()) == FROM


async def test_the_global_number_resolver_says_none_when_no_number_is_set(monkeypatch):
    monkeypatch.setattr(provider_module, "get_settings", lambda: settings(twilio_from_number=""))
    assert await GlobalNumberResolver().resolve(uuid.uuid4(), uuid.uuid4()) is None
