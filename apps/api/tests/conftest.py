"""Integration tests run against the local Postgres (pnpm db:up && pnpm db:migrate).
Each test creates its own tenant, so tests never see each other's data."""

from pathlib import Path

import httpx
import pytest

from clinic_api.main import app
from clinic_core.settings import REPO_ROOT
from clinic_core.testing import create_test_tenant

SAMPLES = REPO_ROOT / "packages/integrations/samples/medspa"


@pytest.fixture
def make_tenant():
    return create_test_tenant


@pytest.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def sample():
    """sample("patients.csv") -> bytes of the synthetic med-spa export."""
    return lambda name: Path(SAMPLES / name).read_bytes()
