"""The browser fixture isolates clients without disabling the production limiter."""

import importlib.util
import os
import uuid
from pathlib import Path

import httpx
import pytest

from clinic_api.main import create_app


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="Needs a disposable migrated test database")
async def test_browser_login_limits_are_stable_per_context_and_independent_between_contexts():
    # Load the standalone test entry point without relying on a shared `tests` namespace.
    spec = importlib.util.spec_from_file_location(
        "isolated_browser_fixture", Path(__file__).with_name("browser_server.py")
    )
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    app = fixture.app
    standard_app = create_app(fixture.settings, google=fixture.BrowserGoogle())
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
    try:
        async with (
            httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:3100") as first,
            httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:3100") as second,
        ):
            path = "/api/v1/auth/google/login"
            assert (await first.get(path)).status_code == 302
            identity = first.cookies.get("browser_test_client")
            assert identity
            for _ in range(19):
                assert (await first.get(path)).status_code == 302
                assert first.cookies.get("browser_test_client") == identity
            denied = await first.get(path)
            assert denied.status_code == 429 and "Retry-After" in denied.headers
            # Same network IP, different cookie jar: another test is not throttled.
            assert (await second.get(path)).status_code == 302
            assert second.cookies.get("browser_test_client") != identity
            assert (await first.get(path)).status_code == 429  # Starting another context did not reset anything.
        # The normal application never trusts this test cookie. Changing it cannot
        # bypass the real client-IP limit, even though the fixture app isolates it.
        standard_transport = httpx.ASGITransport(app=standard_app, client=("normal-client-" + uuid.uuid4().hex, 1234))
        async with httpx.AsyncClient(transport=standard_transport, base_url="http://127.0.0.1:3100") as normal:
            for _ in range(20):
                normal.cookies.set("browser_test_client", uuid.uuid4().hex)
                assert (await normal.get(path)).status_code == 302
            normal.cookies.set("browser_test_client", uuid.uuid4().hex)
            assert (await normal.get(path)).status_code == 429
    finally:
        await app.state.engine.dispose()
        await standard_app.state.engine.dispose()
