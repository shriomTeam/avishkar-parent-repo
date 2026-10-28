"""Searching for, buying and releasing phone numbers on Twilio, with plain HTTPS calls (as the SMS provider does).

Buying a number is not repeatable: a second purchase is a second number and a second monthly bill. So a purchase is
never retried here, and its answer is returned or raised, never guessed. Messages in ``TwilioError`` are written to be
shown to staff and never contain the credentials or the request.
"""

import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

log = logging.getLogger("voice.twilio")

BASE = "https://api.twilio.com/2010-04-01/Accounts"
KINDS = {"local": "Local", "toll_free": "TollFree"}


class TwilioError(Exception):
    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class AvailableNumber:
    number: str
    locality: str
    region: str
    kind: str


@dataclass(frozen=True)
class PurchasedNumber:
    sid: str
    number: str


class NumbersClient(Protocol):
    async def search(
        self, *, kind: str, area_code: str | None, contains: str | None, limit: int = 10
    ) -> list[AvailableNumber]: ...

    async def buy(self, *, number: str, friendly_name: str, voice_url: str | None) -> PurchasedNumber: ...

    async def release(self, sid: str) -> None:
        """Give the number back. A number that is already gone is not an error."""

    async def set_voice_url(self, sid: str, voice_url: str) -> None:
        """Point the number's incoming calls at ``voice_url``."""

    async def list_voice_urls(self) -> dict[str, str]:
        """Every number on the account: its Twilio id and the address its incoming calls go to ('' if none)."""


class TwilioNumbers:
    def __init__(self, account_sid: str, auth_token: str, transport: httpx.AsyncBaseTransport | None = None):
        self._sid, self._auth, self._transport = account_sid, (account_sid, auth_token), transport

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        async with httpx.AsyncClient(timeout=15, transport=self._transport) as client:
            return await client.request(method, f"{BASE}/{self._sid}/{path}", auth=self._auth, **kwargs)

    async def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            return await self._request(method, path, **kwargs)
        except httpx.HTTPError:
            raise TwilioError("Twilio could not be reached. Please try again.", 503) from None

    @staticmethod
    def _fail(response: httpx.Response, action: str) -> TwilioError:
        message, code = "", None
        try:
            body = response.json()
            message, code = str(body.get("message") or "")[:200], body.get("code")
        except ValueError:
            pass
        log.warning("twilio %s failed: status %s, code %s", action, response.status_code, code)
        if response.status_code == 401:  # only a 401 means the account details are wrong
            return TwilioError("Twilio did not accept the account details this server has. Check the Twilio settings.")
        if response.status_code == 403 and not message:
            message = (
                "Twilio refused this request. Your Twilio account may need approval, such as a compliance profile."
            )
        return TwilioError(message or f"Twilio could not {action}.", 502 if response.status_code >= 500 else 409)

    async def search(
        self, *, kind: str, area_code: str | None, contains: str | None, limit: int = 10
    ) -> list[AvailableNumber]:
        params: dict[str, str | int] = {"VoiceEnabled": "true", "PageSize": limit}
        if area_code and kind == "local":
            params["AreaCode"] = area_code
        if contains:
            params["Contains"] = contains
        response = await self._call("GET", f"AvailablePhoneNumbers/US/{KINDS[kind]}.json", params=params)
        if response.status_code >= 300:
            raise self._fail(response, "search for numbers")
        return [
            AvailableNumber(
                number=n["phone_number"], locality=n.get("locality") or "", region=n.get("region") or "", kind=kind
            )
            for n in response.json().get("available_phone_numbers", [])
        ]

    async def buy(self, *, number: str, friendly_name: str, voice_url: str | None) -> PurchasedNumber:
        data = {"PhoneNumber": number, "FriendlyName": friendly_name}
        if voice_url:
            data |= {"VoiceUrl": voice_url, "VoiceMethod": "POST"}
        try:
            response = await self._request("POST", "IncomingPhoneNumbers.json", data=data)
        except httpx.HTTPError:
            return await self._bought_without_answer(number)  # the purchase may have gone through unseen
        if response.status_code >= 300:
            raise self._fail(response, "buy this number")
        try:
            body = response.json()
            return PurchasedNumber(sid=body["sid"], number=body["phone_number"])
        except (ValueError, KeyError, TypeError):
            return await self._bought_without_answer(number)  # a 2xx we cannot read still means Twilio did it

    async def _bought_without_answer(self, number: str) -> PurchasedNumber:
        """Twilio may have completed a purchase whose answer we never read. The number was free a moment ago, so if
        it is on the account now it is ours: hand it back to be saved (or given back if saving fails), instead of
        leaving a number that is billed monthly but belongs to no clinic. The purchase itself is never repeated."""
        found: list | None = None
        try:
            response = await self._request("GET", "IncomingPhoneNumbers.json", params={"PhoneNumber": number})
            if response.status_code < 300:
                found = response.json().get("incoming_phone_numbers", [])
        except (httpx.HTTPError, ValueError, AttributeError):
            pass
        if found is None:
            log.error("could not confirm whether Twilio bought %s after a lost answer; check the console", number)
            raise TwilioError(
                "We could not confirm whether Twilio bought this number. Check your Twilio console before trying "
                "again, so you are not billed for two numbers.",
                503,
            )
        if found:
            return PurchasedNumber(sid=found[0]["sid"], number=found[0]["phone_number"])
        raise TwilioError("Twilio could not be reached. Please try again.", 503)

    async def list_voice_urls(self) -> dict[str, str]:
        urls: dict[str, str] = {}
        path, params = "IncomingPhoneNumbers.json", {"PageSize": 1000}
        for _ in range(10):  # a clinic platform holds a handful of numbers; ten pages is far more than enough
            response = await self._call("GET", path, params=params)
            if response.status_code >= 300:
                raise self._fail(response, "list your numbers")
            body = response.json()
            urls |= {n["sid"]: n.get("voice_url") or "" for n in body.get("incoming_phone_numbers", [])}
            next_page = body.get("next_page_uri")
            if not next_page:
                break
            path, params = next_page.split("/Accounts/", 1)[1].split("/", 1)[1], None  # the rest of the address
        return urls

    async def set_voice_url(self, sid: str, voice_url: str) -> None:
        response = await self._call(
            "POST", f"IncomingPhoneNumbers/{sid}.json", data={"VoiceUrl": voice_url, "VoiceMethod": "POST"}
        )
        if response.status_code >= 300:
            raise self._fail(response, "connect this number to your calls")

    async def release(self, sid: str) -> None:
        response = await self._call("DELETE", f"IncomingPhoneNumbers/{sid}.json")
        if response.status_code not in (204, 404):
            raise self._fail(response, "release this number")
