from __future__ import annotations

import json
import logging

from voxagent.logging_config import (
    JSONFormatter,
    conversation_id_var,
    setup_logging,
    tenant_id_var,
)


class TestJSONFormatter:
    def test_formats_as_json(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "hello", (), None)
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "hello"
        assert data["level"] == "INFO"

    def test_includes_conversation_id(self) -> None:
        token = conversation_id_var.set("conv-123")
        try:
            formatter = JSONFormatter()
            record = logging.LogRecord("test", logging.INFO, "", 0, "test", (), None)
            output = formatter.format(record)
            data = json.loads(output)
            assert data["conversation_id"] == "conv-123"
        finally:
            conversation_id_var.reset(token)

    def test_includes_tenant_id(self) -> None:
        token = tenant_id_var.set("tenant-abc")
        try:
            formatter = JSONFormatter()
            record = logging.LogRecord("test", logging.INFO, "", 0, "test", (), None)
            output = formatter.format(record)
            data = json.loads(output)
            assert data["tenant_id"] == "tenant-abc"
        finally:
            tenant_id_var.reset(token)

    def test_null_context_vars(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "test", (), None)
        output = formatter.format(record)
        data = json.loads(output)
        assert data["conversation_id"] is None
        assert data["tenant_id"] is None

    def test_includes_timestamp(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
        output = formatter.format(record)
        data = json.loads(output)
        assert "timestamp" in data
        assert data["timestamp"]

    def test_includes_logger_name(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord("mylogger", logging.WARNING, "", 0, "msg", (), None)
        output = formatter.format(record)
        data = json.loads(output)
        assert data["logger"] == "mylogger"

    def test_warning_level_name(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord("test", logging.WARNING, "", 0, "msg", (), None)
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "WARNING"

    def test_error_level_name(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord("test", logging.ERROR, "", 0, "msg", (), None)
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "ERROR"

    def test_context_vars_isolated_between_calls(self) -> None:
        token = conversation_id_var.set("conv-isolated")
        try:
            formatter = JSONFormatter()
            record = logging.LogRecord("test", logging.INFO, "", 0, "msg", (), None)
            output = formatter.format(record)
            data = json.loads(output)
            assert data["conversation_id"] == "conv-isolated"
        finally:
            conversation_id_var.reset(token)

        # After reset the var reverts to default (None)
        formatter2 = JSONFormatter()
        record2 = logging.LogRecord("test", logging.INFO, "", 0, "msg2", (), None)
        output2 = formatter2.format(record2)
        data2 = json.loads(output2)
        assert data2["conversation_id"] is None


class TestSetupLogging:
    def test_setup_logging_sets_handler(self) -> None:
        setup_logging(level="DEBUG")
        root = logging.getLogger()
        assert len(root.handlers) >= 1
        assert isinstance(root.handlers[0].formatter, JSONFormatter)

    def test_setup_logging_sets_level(self) -> None:
        setup_logging(level="WARNING")
        root = logging.getLogger()
        assert root.level == logging.WARNING
