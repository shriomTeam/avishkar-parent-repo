"""Run a custom tool: one HTTPS request, with the safeguards that make it safe to do from our servers.

* The address is checked, then we connect to that exact IP (not the name) and still verify the certificate
  against the real host name, so DNS cannot be swapped for an internal address between check and use.
* No redirects, a hard time limit, and a cap on how much of the response we read.
* GET is retried once on a connection error or a server error. POST is never retried.
"""

import asyncio
import ipaddress
import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

from clinic_voice_receptionist.tools.netguard import BlockedTarget, parse_url, resolve

MAX_RESPONSE_BYTES = 65_536
HEADER_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9-]{0,63}$")
FORBIDDEN_HEADERS = {
    "host", "content-length", "content-type", "transfer-encoding", "connection", "upgrade", "te", "trailer",
    "idempotency-key", "user-agent", "accept", "cookie",
}  # fmt: skip


@dataclass
class HttpResult:
    ok: bool
    status: int | None
    data: Any
    error: str | None
    duration_ms: int


def check_header_name(name: str) -> None:
    if not HEADER_NAME.match(name) or name.lower() in FORBIDDEN_HEADERS:
        raise BlockedTarget("Choose a different header name, such as Authorization or X-Api-Key.")


def _query_value(value: Any) -> str:
    return "true" if value is True else "false" if value is False else str(value)


def _parse_body(response: httpx.Response, body: bytes) -> Any:
    text = body.decode(response.encoding or "utf-8", errors="replace")
    if "json" in response.headers.get("content-type", "").lower():
        try:
            return json.loads(text)
        except ValueError:
            pass
    return text[:2000]


async def _send_once(
    *, method: str, target, ip: str, args: dict, headers: dict[str, str], limit: float
) -> tuple[int, Any, str | None]:
    host_header = target.host if target.port in (80, 443) else f"{target.host}:{target.port}"
    ip_host = f"[{ip}]" if isinstance(ipaddress.ip_address(ip), ipaddress.IPv6Address) else ip
    url = httpx.URL(f"{target.scheme}://{ip_host}:{target.port}{target.path_and_query}")
    if method == "GET" and args:
        url = url.copy_merge_params({k: _query_value(v) for k, v in args.items() if not isinstance(v, (dict, list))})
    request = httpx.Request(
        method,
        url,
        headers={**headers, "Host": host_header},
        json=args if method == "POST" else None,
        extensions={"sni_hostname": target.host},  # the certificate is checked against the name, not the IP
    )
    async with httpx.AsyncClient(follow_redirects=False, timeout=limit, trust_env=False) as client:
        response = await client.send(request, stream=True)
        try:
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE_BYTES:
                    raise ValueError("The response was too large.")
                chunks.append(chunk)
        finally:
            await response.aclose()
    return response.status_code, _parse_body(response, b"".join(chunks)), response.headers.get("location")


async def call_http(
    *,
    endpoint: str,
    method: str,
    args: dict,
    timeout_seconds: int,
    idempotency_key: str,
    auth_header: tuple[str, str] | None = None,
    allow_private: bool = False,
) -> HttpResult:
    started = time.monotonic()

    def done(ok: bool, status: int | None, data: Any, error: str | None) -> HttpResult:
        return HttpResult(ok, status, data, error, int((time.monotonic() - started) * 1000))

    try:
        target = parse_url(endpoint, allow_private=allow_private)
        ip = await resolve(target, allow_private=allow_private)
    except BlockedTarget as exc:
        return done(False, None, None, str(exc))
    headers = {"Accept": "application/json", "User-Agent": "avishkar-voice/1", "Idempotency-Key": idempotency_key}
    if auth_header:
        headers[auth_header[0]] = auth_header[1]
    attempts = 2 if method == "GET" else 1
    error = "The request failed."
    try:
        async with asyncio.timeout(timeout_seconds):
            for attempt in range(attempts):
                try:
                    status, data, location = await _send_once(
                        method=method, target=target, ip=ip, args=args, headers=headers, limit=timeout_seconds
                    )
                except httpx.TransportError:
                    error = "Could not connect to the endpoint."
                    if attempt + 1 < attempts:
                        continue
                    return done(False, None, None, error)
                if 300 <= status < 400:
                    where = f" to {location[:200]}" if location else ""
                    return done(
                        False,
                        status,
                        None,
                        f"The endpoint redirected{where}. Redirects are not followed; use the final address instead.",
                    )
                if status >= 500 and attempt + 1 < attempts:
                    error = f"The endpoint answered with status {status}."
                    continue
                return done(
                    status < 400, status, data, None if status < 400 else f"The endpoint answered with status {status}."
                )
    except TimeoutError:
        return done(False, None, None, f"The endpoint did not answer within {timeout_seconds} seconds.")
    except ValueError as exc:  # response too large
        return done(False, None, None, str(exc))
    return done(False, None, None, error)
