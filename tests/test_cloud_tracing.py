from types import SimpleNamespace

import pytest
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExportResult
from opentelemetry.trace import SpanContext, SpanKind, Status, StatusCode, TraceFlags

from observatory.cloud_tracing import PrivateExporter, endpoint, read_key, sanitized


def span(name="assistant.request"):
    return ReadableSpan(
        name=name, context=SpanContext(123, 456, False, TraceFlags(1)), kind=SpanKind.INTERNAL,
        start_time=100, end_time=200,
        attributes={"prompt": "SECRET", "user.id": "PRIVATE", "assistant.backend": "selfhosted_cpu",
                    "assistant.status": "ok", "assistant.ttft_ms": 123.4, "assistant.output_tokens": float("nan"),
                    "error.type": "PrivateExceptionName"},
        events=(SimpleNamespace(name="SECRET"),), links=(), status=Status(StatusCode.ERROR, "SECRET"),
    )


def test_no_payloads_or_error_text_leave_gateway():
    clean = sanitized(span())
    assert clean.attributes == {"assistant.backend": "selfhosted_cpu", "assistant.status": "ok",
                                "assistant.ttft_ms": 123.4, "error.type": "other"}
    assert not clean.events and not clean.links and not clean.status.description
    assert clean.context.trace_id == 123 and clean.start_time == 100 and clean.end_time == 200
    assert "host.name" not in clean.resource.attributes
    assert sanitized(span("url with private question")) is None


def test_export_budget_failures_and_window():
    sent, clock = [], [0]
    delegate = SimpleNamespace(export=lambda batch: sent.extend(batch) or SpanExportResult.SUCCESS, shutdown=lambda: None)
    exporter = PrivateExporter(delegate, budget=2, clock=lambda: clock[0])
    exporter.export([span(), span(), span()])
    exporter.export([span()])
    assert len(sent) == 2
    clock[0] = 3601
    exporter.export([span()])
    assert len(sent) == 3
    delegate.export = lambda batch: (_ for _ in ()).throw(ValueError("SECRET"))
    assert exporter.export([span()]) == SpanExportResult.FAILURE
    assert len(exporter.attempts) == 2  # Failures consume the budget too.


@pytest.mark.parametrize("value", ["http://a.apm-agt.us-phoenix-1.oci.oraclecloud.com", "https://evil.com",
    "https://a.apm-agt.us-phoenix-1.oci.oraclecloud.com/?key=secret", "https://user:password@a.apm-agt.us-phoenix-1.oci.oraclecloud.com",
    "https://a.apm-agt.us-ashburn-1.oci.oraclecloud.com", "https://a.apm-agt.us-phoenix-1.oci.oraclecloud.com.evil.com"])
def test_endpoint_is_exact_and_private(value):
    with pytest.raises(ValueError):
        endpoint(value)


def test_private_key_file_and_origin(tmp_path):
    key = tmp_path / "key"
    key.write_text("a" * 32)
    key.chmod(0o600)
    assert read_key(key) == "a" * 32
    key.chmod(0o644)
    with pytest.raises(ValueError):
        read_key(key)
    assert endpoint("https://test.apm-agt.us-phoenix-1.oci.oraclecloud.com/").endswith("/private/v1/traces")
