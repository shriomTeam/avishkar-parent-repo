"""A tiny local HTTP server for tool tests. Each test says how it should answer."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager

Handler = Callable[[dict, int], Awaitable[tuple[int, dict, bytes]]]


def json_reply(body, status: int = 200, headers: dict | None = None) -> tuple[int, dict, bytes]:
    return status, {"Content-Type": "application/json", **(headers or {})}, json.dumps(body).encode()


@asynccontextmanager
async def serve(handler: Handler):
    """Yields (base_url, recorded_requests)."""
    requests: list[dict] = []

    async def on_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            head = (await reader.readuntil(b"\r\n\r\n")).decode().split("\r\n")
            method, target, _ = head[0].split(" ")
            headers = {k.lower(): v for k, v in (line.split(": ", 1) for line in head[1:] if ": " in line)}
            body = await reader.readexactly(int(headers.get("content-length", 0)))
            request = {"method": method, "target": target, "headers": headers, "body": body}
            requests.append(request)
            status, reply_headers, payload = await handler(request, len(requests))
            extra = "".join(f"{k}: {v}\r\n" for k, v in reply_headers.items())
            status_line = f"HTTP/1.1 {status} Reply\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n"
            writer.write(f"{status_line}{extra}\r\n".encode() + payload)
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(on_connection, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}", requests
    finally:
        server.close()
        await server.wait_closed()
