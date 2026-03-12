from __future__ import annotations

import logging
from datetime import UTC, datetime

import httpx

from voxagent.models import LeadRecord

logger = logging.getLogger(__name__)


async def dispatch_lead_webhook(
    webhook_url: str,
    lead: LeadRecord,
) -> None:
    payload = {
        "event": "lead.created",
        "lead": {
            "id": str(lead.id),
            "tenant_id": str(lead.tenant_id),
            "conversation_id": str(lead.conversation_id),
            "name": lead.name,
            "email": lead.email,
            "phone": lead.phone,
            "intent": lead.intent,
            "summary": lead.summary,
            "extracted_at": lead.extracted_at.isoformat(),
        },
        "dispatched_at": datetime.now(UTC).isoformat(),
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(
            webhook_url,
            json=payload,
            timeout=30.0,
        )
        response.raise_for_status()

    logger.info(
        "Webhook dispatched to %s for lead %s (status %d)",
        webhook_url,
        lead.id,
        response.status_code,
    )
