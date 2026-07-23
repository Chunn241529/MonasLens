import json
import logging

from monas_lens.logging_config import JsonFormatter, OperationFilter, operation_context


def test_json_logs_include_operation_id() -> None:
    record = logging.LogRecord(
        name="monas_lens.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="indexed",
        args=(),
        exc_info=None,
    )

    with operation_context("operation-123"):
        payload = json.loads(JsonFormatter().format(record))

    assert payload["message"] == "indexed"
    assert payload["operation_id"] == "operation-123"


def test_operation_filter_adds_safe_default() -> None:
    record = logging.LogRecord(
        name="monas_lens.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="ready",
        args=(),
        exc_info=None,
    )

    assert OperationFilter().filter(record)
    assert record.operation_id == "-"
