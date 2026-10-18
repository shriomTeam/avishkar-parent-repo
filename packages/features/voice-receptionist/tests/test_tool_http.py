import asyncio
import json

from support_http import json_reply, serve

from clinic_voice_receptionist.tools.http_tool import call_http


async def _call(url, **kwargs):
    defaults = dict(endpoint=url, method="POST", args={}, timeout_seconds=3, idempotency_key="k1", allow_private=True)
    return await call_http(**(defaults | kwargs))


async def test_post_sends_json_headers_and_the_auth_header():
    async def handler(request, n):
        return json_reply({"id": 7})

    async with serve(handler) as (url, requests):
        result = await _call(
            url + "/leads", args={"name": "Sam"}, auth_header=("X-Api-Key", "s3cret"), idempotency_key="call:1"
        )
    assert (result.ok, result.status, result.data, result.error) == (True, 200, {"id": 7}, None)
    request = requests[0]
    assert request["method"] == "POST" and request["target"] == "/leads"
    assert json.loads(request["body"]) == {"name": "Sam"}
    assert request["headers"]["x-api-key"] == "s3cret"
    assert request["headers"]["idempotency-key"] == "call:1"
    assert request["headers"]["user-agent"] == "avishkar-voice/1"
    assert request["headers"]["host"].startswith("127.0.0.1:")


async def test_get_sends_arguments_as_query_text_and_skips_nested_values():
    async def handler(request, n):
        return json_reply({"ok": True})

    async with serve(handler) as (url, requests):
        await _call(url + "/hours?day=mon", method="GET", args={"on": True, "n": 3, "tags": ["a"], "x": {"y": 1}})
    target = requests[0]["target"]
    assert target.startswith("/hours?") and "day=mon" in target and "on=true" in target and "n=3" in target
    assert "tags" not in target and "x=" not in target and requests[0]["body"] == b""


async def test_get_is_retried_once_after_a_server_error_but_post_never_is():
    async def flaky(request, n):
        return json_reply({"error": "busy"}, 503) if n == 1 else json_reply({"ok": True})

    async with serve(flaky) as (url, requests):
        result = await _call(url, method="GET")
    assert result.ok and len(requests) == 2

    async def always_down(request, n):
        return json_reply({"error": "down"}, 500)

    async with serve(always_down) as (url, requests):
        post = await _call(url, method="POST")
        await _call(url, method="GET")
    assert not post.ok and post.status == 500 and "status 500" in post.error
    assert len(requests) == 1 + 2  # one POST attempt, two GET attempts


async def test_client_errors_are_returned_with_the_body_and_not_retried():
    async def handler(request, n):
        return json_reply({"error": "bad phone"}, 422)

    async with serve(handler) as (url, requests):
        result = await _call(url, method="GET")
    assert (result.ok, result.status, result.data) == (False, 422, {"error": "bad phone"}) and len(requests) == 1


async def test_redirects_are_not_followed():
    async def handler(request, n):
        return 302, {"Location": "http://169.254.169.254/latest/meta-data/"}, b""

    async with serve(handler) as (url, requests):
        result = await _call(url)
    assert not result.ok and len(requests) == 1
    assert "redirected to http://169.254.169.254/latest/meta-data/" in result.error and "final address" in result.error


async def test_a_slow_endpoint_times_out():
    async def handler(request, n):
        await asyncio.sleep(3)
        return json_reply({})

    async with serve(handler) as (url, _):
        result = await _call(url, timeout_seconds=1)
    assert not result.ok and "within 1 seconds" in result.error and result.duration_ms < 2500


async def test_an_oversized_response_is_refused():
    async def handler(request, n):
        return 200, {"Content-Type": "text/plain"}, b"x" * 70_000

    async with serve(handler) as (url, _):
        result = await _call(url)
    assert not result.ok and "too large" in result.error


async def test_plain_text_answers_are_kept_as_text():
    async def handler(request, n):
        return 200, {"Content-Type": "text/plain"}, b"Open 9 to 5"

    async with serve(handler) as (url, _):
        result = await _call(url, method="GET")
    assert result.ok and result.data == "Open 9 to 5"


async def test_nothing_is_sent_to_a_private_address_unless_development_allows_it():
    async def handler(request, n):
        return json_reply({})

    async with serve(handler) as (url, requests):
        result = await _call(url, allow_private=False)
    assert not result.ok and "HTTPS" in result.error and requests == []


async def test_a_refused_connection_is_reported_plainly():
    result = await _call("http://127.0.0.1:9/x", method="POST")
    assert not result.ok and "connect" in result.error
