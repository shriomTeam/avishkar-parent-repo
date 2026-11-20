"""Meta's WhatsApp Cloud API (the Graph API), behind a small interface so tests can use a fake."""

from typing import Protocol

import httpx

from clinic_voice_receptionist.config import get_voice_settings

GRAPH = "https://graph.facebook.com"
TIMEOUT = 15.0


class GraphError(Exception):
    """Meta refused or could not be reached. The message is safe to show staff and never holds the access token."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class WhatsAppGraph(Protocol):
    async def display_number(self, phone_number_id: str, token: str) -> str | None: ...

    async def send_text(self, phone_number_id: str, token: str, to: str, body: str) -> str: ...


class MetaGraph:
    def __init__(self, version: str | None = None):
        self._version = version or get_voice_settings().whatsapp_graph_version

    async def _call(self, method: str, path: str, token: str, **kwargs) -> dict:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                response = await client.request(
                    method, f"{GRAPH}/{self._version}/{path}", headers={"Authorization": f"Bearer {token}"}, **kwargs
                )
        except httpx.HTTPError:
            raise GraphError("Meta could not be reached. Try again in a moment.") from None
        if response.status_code in (400, 401, 403, 404):
            raise GraphError("Meta refused the number id or the access token. Check both and try again.", 422)
        if response.status_code >= 400:
            raise GraphError("Meta answered with an error. Try again in a moment.")
        try:
            return response.json()
        except ValueError:
            raise GraphError("Meta sent an answer that could not be read.") from None

    async def display_number(self, phone_number_id: str, token: str) -> str | None:
        data = await self._call("GET", phone_number_id, token, params={"fields": "display_phone_number"})
        return data.get("display_phone_number")

    async def send_text(self, phone_number_id: str, token: str, to: str, body: str) -> str:
        payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": body}}
        data = await self._call("POST", f"{phone_number_id}/messages", token, json=payload)
        try:
            return data["messages"][0]["id"]
        except (KeyError, IndexError, TypeError):
            raise GraphError("Meta did not confirm the message.") from None
