from __future__ import annotations

from voxagent.metrics import (
    CONVERSATIONS_TOTAL,
    KNOWLEDGE_INDEX_BUILDS,
    LEADS_EXTRACTED,
    RATE_LIMIT_DECISIONS,
    TOKEN_ISSUANCE_TOTAL,
    metrics_response,
)


class TestMetrics:
    def test_counter_increments(self) -> None:
        before = CONVERSATIONS_TOTAL.labels(tenant_id="test")._value.get()
        CONVERSATIONS_TOTAL.labels(tenant_id="test").inc()
        after = CONVERSATIONS_TOTAL.labels(tenant_id="test")._value.get()
        assert after == before + 1

    def test_leads_counter_increments(self) -> None:
        before = LEADS_EXTRACTED.labels(tenant_id="test-leads")._value.get()
        LEADS_EXTRACTED.labels(tenant_id="test-leads").inc()
        after = LEADS_EXTRACTED.labels(tenant_id="test-leads")._value.get()
        assert after == before + 1

    def test_metrics_response_returns_bytes(self) -> None:
        body, content_type = metrics_response()
        assert isinstance(body, bytes)
        assert "text/plain" in content_type or "openmetrics" in content_type

    def test_metrics_response_contains_metric_name(self) -> None:
        body, _ = metrics_response()
        text = body.decode()
        assert "voxagent_conversations_total" in text

    def test_metrics_response_content_type_not_empty(self) -> None:
        _, content_type = metrics_response()
        assert content_type

    def test_counter_increments_by_amount(self) -> None:
        before = CONVERSATIONS_TOTAL.labels(tenant_id="test-amount")._value.get()
        CONVERSATIONS_TOTAL.labels(tenant_id="test-amount").inc(5)
        after = CONVERSATIONS_TOTAL.labels(tenant_id="test-amount")._value.get()
        assert after == before + 5

    def test_metrics_response_includes_leads_metric(self) -> None:
        # Ensure the metric has been observed before checking output
        LEADS_EXTRACTED.labels(tenant_id="test-output").inc()
        body, _ = metrics_response()
        text = body.decode()
        assert "voxagent_leads_extracted_total" in text

    def test_metrics_response_includes_operational_metrics(self) -> None:
        TOKEN_ISSUANCE_TOTAL.labels(tenant_id="tenant-a", outcome="issued").inc()
        RATE_LIMIT_DECISIONS.labels(policy="public", outcome="allowed").inc()
        KNOWLEDGE_INDEX_BUILDS.labels(tenant_id="tenant-a", trigger="rebuild").inc()
        body, _ = metrics_response()
        text = body.decode()
        assert "voxagent_token_issuance_total" in text
        assert "voxagent_rate_limit_decisions_total" in text
        assert "voxagent_knowledge_index_builds_total" in text
