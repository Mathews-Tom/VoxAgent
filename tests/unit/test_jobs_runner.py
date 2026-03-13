from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from voxagent.models import (
    ConversationEvent,
    ConversationRecord,
    JobRecord,
    LeadRecord,
    TenantConfig,
)


def _job_payload(**payload: object) -> JobRecord:
    return JobRecord(
        job_type=str(payload.pop("job_type", "lead_extraction")),
        payload=dict(payload),
        idempotency_key=str(payload.get("idempotency_key", uuid.uuid4())),
    )


class TestLeadExtractionJobs:
    @pytest.mark.asyncio
    @patch("voxagent.jobs.runner.get_tenant", new_callable=AsyncMock)
    @patch("voxagent.jobs.runner.list_conversation_events", new_callable=AsyncMock)
    @patch("voxagent.jobs.runner.get_conversation", new_callable=AsyncMock)
    async def test_lead_extraction_enqueues_webhook_job(
        self,
        mock_get_conversation: AsyncMock,
        mock_list_events: AsyncMock,
        mock_get_tenant: AsyncMock,
    ) -> None:
        from voxagent.jobs.runner import _handle_lead_extraction

        tenant_id = uuid.uuid4()
        conversation_id = uuid.uuid4()
        lead_id = uuid.uuid4()
        mock_get_conversation.return_value = ConversationRecord(
            id=conversation_id,
            tenant_id=tenant_id,
            visitor_id="visitor-1",
            room_name="room-1",
            transcript=[{"role": "user", "content": "need help"}],
            started_at=datetime.now(UTC),
        )
        mock_list_events.return_value = [
            ConversationEvent(
                conversation_id=conversation_id,
                role="user",
                content="need help",
                sequence_number=0,
            )
        ]
        mock_get_tenant.return_value = TenantConfig(
            id=tenant_id,
            name="Acme",
            domain="acme.example",
            webhook_url="https://hooks.example.com/lead",
        )
        with (
            patch("voxagent.leads.extract_lead", new_callable=AsyncMock) as mock_extract_lead,
            patch("voxagent.jobs.runner.enqueue_job", new_callable=AsyncMock) as mock_enqueue_job,
        ):
            mock_extract_lead.return_value = LeadRecord(
                id=lead_id,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                email="alice@example.com",
            )

            await _handle_lead_extraction(
                MagicMock(),
                MagicMock(),
                _job_payload(
                    tenant_id=str(tenant_id),
                    conversation_id=str(conversation_id),
                    visitor_id="visitor-1",
                ),
            )

            mock_enqueue_job.assert_called_once()
            queued_job = mock_enqueue_job.call_args.args[1]
            assert queued_job.job_type == "lead_webhook"
            assert queued_job.payload["lead_id"] == str(lead_id)


class TestJobFailureTransitions:
    @pytest.mark.asyncio
    @patch("voxagent.jobs.runner.mark_job_failed", new_callable=AsyncMock)
    async def test_failed_job_marks_retry_state(self, mock_mark_failed: AsyncMock) -> None:
        from voxagent.jobs.runner import _run_job

        job = JobRecord(
            job_type="unknown",
            payload={"tenant_id": "tenant-1"},
            idempotency_key="unknown:1",
        )

        await _run_job(MagicMock(), MagicMock(), job)

        mock_mark_failed.assert_called_once()

    @pytest.mark.asyncio
    @patch("voxagent.jobs.runner.mark_job_failed", new_callable=AsyncMock)
    async def test_unknown_payload_version_marks_retry_state(
        self, mock_mark_failed: AsyncMock
    ) -> None:
        from voxagent.jobs.runner import _run_job

        job = JobRecord(
            job_type="lead_extraction",
            payload={"tenant_id": "tenant-1", "payload_version": 99},
            idempotency_key="lead_extraction:bad-version",
        )

        await _run_job(MagicMock(), MagicMock(), job)

        mock_mark_failed.assert_called_once()


class TestLeadWebhookJobs:
    @pytest.mark.asyncio
    @patch("voxagent.jobs.runner.get_lead", new_callable=AsyncMock)
    @patch("voxagent.jobs.runner.get_tenant", new_callable=AsyncMock)
    async def test_lead_webhook_dispatches_existing_lead(
        self,
        mock_get_tenant: AsyncMock,
        mock_get_lead: AsyncMock,
    ) -> None:
        from voxagent.jobs.runner import _handle_lead_webhook

        tenant_id = uuid.uuid4()
        lead_id = uuid.uuid4()
        mock_get_tenant.return_value = TenantConfig(
            id=tenant_id,
            name="Acme",
            domain="acme.example",
            webhook_url="https://hooks.example.com/lead",
        )
        mock_get_lead.return_value = LeadRecord(
            id=lead_id,
            tenant_id=tenant_id,
            conversation_id=uuid.uuid4(),
            email="alice@example.com",
        )

        with patch(
            "voxagent.webhooks.dispatch_lead_webhook",
            new_callable=AsyncMock,
        ) as mock_dispatch:
            await _handle_lead_webhook(
                MagicMock(),
                _job_payload(
                    job_type="lead_webhook",
                    tenant_id=str(tenant_id),
                    lead_id=str(lead_id),
                ),
            )

            mock_dispatch.assert_called_once()


class TestKnowledgeRebuildJobs:
    @pytest.mark.asyncio
    @patch("voxagent.jobs.runner.rebuild_index", new_callable=AsyncMock)
    async def test_knowledge_rebuild_executes_rebuild(self, mock_rebuild_index: AsyncMock) -> None:
        from voxagent.jobs.runner import _handle_knowledge_rebuild

        tenant_id = uuid.uuid4()

        await _handle_knowledge_rebuild(
            MagicMock(),
            _job_payload(job_type="knowledge_rebuild", tenant_id=str(tenant_id)),
        )

        mock_rebuild_index.assert_awaited_once()
