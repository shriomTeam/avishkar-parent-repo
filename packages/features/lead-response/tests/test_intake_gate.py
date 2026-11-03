"""How the inbound route is mounted: public, off by default, and outside the generated API client."""

import httpx
import pytest
from lr_api import build_app, client_for, headers
from lr_intake import PATH, PUBLIC, TOKEN, Intake, count, form_bytes, reference_signature, twilio_pairs

from clinic_db.models.lead_response import Message
from clinic_lead_response.feature import feature
from clinic_lead_response.intake.parse import parse_form


def platform_app():
    """Mounted the way apps/api does it: the feature router behind staff sign-in and entitlement, the public router
    (``websocket_router``) without them."""
    app = build_app()
    app.include_router(feature.websocket_router, prefix=PATH)
    return app


def test_the_feature_still_says_it_is_not_available():
    assert feature.available is False  # the API gate never reads this; the test below shows why it matters


def test_the_public_router_has_exactly_the_inbound_and_receipt_routes():
    paths = {(route.path, tuple(sorted(route.methods))) for route in feature.websocket_router.routes}
    assert paths == {
        ("/in/{channel}/{tenant}", ("POST",)),
        ("/status/{channel}/{tenant}", ("POST",)),
    }


def test_no_route_of_the_public_router_is_in_the_openapi_schema():
    assert all(route.include_in_schema is False for route in feature.websocket_router.routes)
    schema = platform_app().openapi()
    assert [path for path in schema["paths"] if "/in/" in path] == []
    assert "TwiML" not in str(schema) and "MessageSid" not in str(schema)


def test_the_staff_router_is_still_in_the_schema():
    assert any(path.endswith("/settings") for path in platform_app().openapi()["paths"])


async def test_staff_routes_need_a_sign_in_but_the_public_route_does_not(monkeypatch, make_tenant):
    tenant = await make_tenant()
    Intake(monkeypatch)  # replaces the platform settings the route reads
    app = platform_app()
    async with client_for(app) as client:
        no_auth = await client.get(f"{PATH}/settings")
        assert no_auth.status_code in (401, 403, 422)
        body = form_bytes(twilio_pairs())
        signature = reference_signature(TOKEN, f"{PUBLIC}{PATH}/in/sms/{tenant}", parse_form(body))
        public = await client.post(
            f"{PATH}/in/sms/{tenant}",
            content=body,
            headers={"content-type": "application/x-www-form-urlencoded", "x-twilio-signature": signature},
        )
    assert public.status_code == 200
    assert await count(tenant, Message) == 1


async def test_it_works_for_a_clinic_whose_feature_is_on_even_though_available_is_false(monkeypatch, make_tenant):
    tenant = await make_tenant()
    assert (await Intake(monkeypatch).post(tenant)).status_code == 200
    assert await count(tenant, Message) == 1


async def test_a_staff_header_does_not_open_the_public_route(monkeypatch, make_tenant):
    tenant = await make_tenant()
    intake = Intake(monkeypatch)
    response = await intake.post(tenant, sign=False, headers=headers(tenant))
    assert response.status_code == 403
    assert await count(tenant, Message) == 0


@pytest.mark.parametrize("blank", ["", "   "])
async def test_a_blank_public_address_switches_everything_off(monkeypatch, make_tenant, blank):
    tenant = await make_tenant()
    response = await Intake(monkeypatch, base=blank).post(tenant)
    assert response.status_code == 503
    assert await count(tenant, Message) == 0


async def test_the_real_settings_are_off_unless_the_address_is_set(monkeypatch):
    from clinic_lead_response.config import IntakeSettings

    monkeypatch.delenv("LEAD_RESPONSE_PUBLIC_API_URL", raising=False)
    assert IntakeSettings(_env_file=None).public_base is None


async def test_a_route_that_does_not_exist_is_404_not_a_leak(monkeypatch):
    Intake(monkeypatch)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=platform_app()), base_url="http://test") as client:
        assert (await client.post(f"{PATH}/in/sms")).status_code in (404, 405)
        assert (await client.post(f"{PATH}/in")).status_code in (404, 405)
