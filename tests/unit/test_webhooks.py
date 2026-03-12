from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from voxagent.models import LeadRecord
from voxagent.webhooks import dispatch_lead_webhook


@pytest.fixture
def lead() -> LeadRecord:
    return LeadRecord(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        name="Jane Doe",
        email="jane@example.com",
        phone="+15551234567",
        intent="pricing inquiry",
        summary="Asked about enterprise pricing.",
        extracted_at=datetime.now(UTC),
    )


class TestDispatchLeadWebhook:
    @pytest.mark.asyncio
    async def test_sends_correct_payload(self, lead: LeadRecord) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voxagent.webhooks.httpx.AsyncClient", return_value=mock_client):
            await dispatch_lead_webhook("https://hooks.example.com/lead", lead)

        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs.args[0] == "https://hooks.example.com/lead"
        payload = call_kwargs.kwargs["json"]
        assert payload["event"] == "lead.created"
        assert payload["lead"]["name"] == "Jane Doe"
        assert payload["lead"]["email"] == "jane@example.com"
        assert payload["lead"]["tenant_id"] == str(lead.tenant_id)

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self, lead: LeadRecord) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Server Error",
                request=MagicMock(),
                response=mock_response,
            )
        )

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voxagent.webhooks.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(httpx.HTTPStatusError):
                await dispatch_lead_webhook("https://hooks.example.com/lead", lead)

    @pytest.mark.asyncio
    async def test_payload_contains_expected_fields(self, lead: LeadRecord) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("voxagent.webhooks.httpx.AsyncClient", return_value=mock_client):
            await dispatch_lead_webhook("https://hooks.example.com/lead", lead)

        payload = mock_client.post.call_args.kwargs["json"]
        assert "event" in payload
        assert "lead" in payload
        assert "dispatched_at" in payload
        lead_data = payload["lead"]
        assert "id" in lead_data
        assert "tenant_id" in lead_data
        assert "conversation_id" in lead_data
        assert "name" in lead_data
        assert "email" in lead_data
        assert "phone" in lead_data
        assert "intent" in lead_data
        assert "summary" in lead_data
        assert "extracted_at" in lead_data
