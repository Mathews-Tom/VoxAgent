from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from voxagent.server.routes.leads import router as leads_router
from voxagent.server.routes.tenants import router as tenants_router

# Minimal app without lifespan — no DB connection required.
# Used exclusively to exercise FastAPI's built-in input validation.
_validation_app = FastAPI()
_validation_app.include_router(tenants_router)
_validation_app.include_router(leads_router)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest_asyncio.fixture
async def client():  # type: ignore[override]
    transport = ASGITransport(app=_validation_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestInputValidation:
    async def test_tenant_id_must_be_valid_uuid(self, client: AsyncClient) -> None:
        response = await client.get("/api/tenants/not-a-uuid")
        assert response.status_code == 422

    async def test_sql_injection_in_tenant_id(self, client: AsyncClient) -> None:
        # FastAPI UUID path param validation rejects non-UUID strings
        response = await client.get("/api/tenants/'; DROP TABLE tenants;--")
        assert response.status_code == 422

    async def test_negative_limit_rejected(self, client: AsyncClient) -> None:
        import uuid

        tenant_id = str(uuid.uuid4())
        response = await client.get(f"/api/tenants/{tenant_id}/leads?limit=-1")
        assert response.status_code == 422

    async def test_limit_over_max_rejected(self, client: AsyncClient) -> None:
        import uuid

        tenant_id = str(uuid.uuid4())
        # leads endpoint has le=500; 10000 exceeds that
        response = await client.get(f"/api/tenants/{tenant_id}/leads?limit=10000")
        assert response.status_code == 422

    async def test_negative_offset_rejected(self, client: AsyncClient) -> None:
        import uuid

        tenant_id = str(uuid.uuid4())
        response = await client.get(f"/api/tenants/{tenant_id}/leads?offset=-1")
        assert response.status_code == 422

    async def test_non_integer_limit_rejected(self, client: AsyncClient) -> None:
        import uuid

        tenant_id = str(uuid.uuid4())
        response = await client.get(f"/api/tenants/{tenant_id}/leads?limit=abc")
        assert response.status_code == 422

    async def test_valid_uuid_passes_path_validation(self, client: AsyncClient) -> None:
        import uuid

        tenant_id = str(uuid.uuid4())
        # Valid UUID passes path validation — handler crashes (no DB pool), not 422
        with pytest.raises(AttributeError, match="pool"):
            await client.get(f"/api/tenants/{tenant_id}")

    async def test_export_limit_over_max_rejected(self, client: AsyncClient) -> None:
        import uuid

        tenant_id = str(uuid.uuid4())
        # export endpoint has le=5000; 100000 exceeds that
        response = await client.get(f"/api/tenants/{tenant_id}/leads/export?limit=100000")
        assert response.status_code == 422

    async def test_xss_in_tenant_name_stored_as_is(self, client: AsyncClient) -> None:
        # POST body with XSS payload — FastAPI accepts any string for `name`.
        # Validation passes; handler crashes (no DB pool), proving input wasn't rejected as 422.
        payload = {
            "name": "<script>alert('xss')</script>",
            "domain": "xss.example.com",
        }
        with pytest.raises(AttributeError, match="pool"):
            await client.post("/api/tenants", json=payload)
