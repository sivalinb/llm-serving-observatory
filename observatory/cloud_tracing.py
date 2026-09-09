"""Opt-in OCI export: allowlisted spans, no payloads, bounded buffering and rate.

The budget is per process and resets on restart. OCI's Always Free ingestion limit
is the final cap; this is a best-effort traffic budget, not a billing guarantee.
"""

import math
import re
import threading
import time
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode
from prometheus_client import Counter

EXPORTED = Counter("assistant_cloud_spans_total", "APM export attempts and drops", ["result"])
NAMES = {"assistant.request", "assistant.retrieval", "assistant.admission", "assistant.model_stream"}
ENUMS = {
    "assistant.backend": {"selfhosted_cpu"},
    "assistant.status": {"ok", "error", "timeout", "cancelled"},
    "error.type": {"TimeoutError", "ValueError", "HTTPStatusError", "ReadError", "ConnectError", "other"},
}
NUMBERS = {"assistant.retrieval_ms", "assistant.ttft_ms", "assistant.output_tokens"}


def endpoint(origin):
    parts = urlsplit(origin)
    if (
        parts.scheme != "https" or parts.username or parts.password or parts.port
        or parts.query or parts.fragment or parts.path not in {"", "/"}
        or not re.fullmatch(r"[a-z0-9-]+\.apm-agt\.us-phoenix-1\.oci\.oraclecloud\.com", parts.hostname or "")
    ):
        raise ValueError("An HTTPS Phoenix APM data-upload origin is required")
    return origin.rstrip("/") + "/20200101/opentelemetry/private/v1/traces"


def read_key(path):
    key_path = Path(path)
    if key_path.is_symlink() or not key_path.is_file() or key_path.stat().st_mode & 0o077:
        raise ValueError("APM key must be a private regular file")
    if key_path.stat().st_size > 256:
        raise ValueError("APM key exceeds its bound")
    value = key_path.read_text().strip()
    if not re.fullmatch(r"[A-Za-z0-9_=-]{16,256}", value):
        raise ValueError("Invalid APM upload key")
    return value


def sanitized(span):
    if span.name not in NAMES:
        return None
    attributes = {}
    for key, value in (span.attributes or {}).items():
        if key in ENUMS and isinstance(value, str):
            if value in ENUMS[key]:
                attributes[key] = value
            elif key == "error.type":
                attributes[key] = "other"
        elif key in NUMBERS and type(value) in {int, float} and math.isfinite(value) and 0 <= value <= 1e9:
            attributes[key] = value
    return ReadableSpan(
        name=span.name, context=span.context, parent=span.parent, kind=span.kind,
        start_time=span.start_time, end_time=span.end_time, attributes=attributes,
        events=(), links=(), status=Status(StatusCode.UNSET),
        resource=Resource({"service.name": "observatory-gateway", "deployment.environment.name": "private-learning"}),
    )


class PrivateExporter(SpanExporter):
    def __init__(self, delegate, budget=900, clock=time.monotonic):
        self.delegate, self.budget, self.clock = delegate, budget, clock
        self.attempts, self.lock = deque(), threading.Lock()

    def export(self, spans):
        clean = [result for span in spans if (result := sanitized(span)) is not None]
        EXPORTED.labels("filtered").inc(len(spans) - len(clean))
        with self.lock:
            now = self.clock()
            while self.attempts and self.attempts[0] <= now - 3600:
                self.attempts.popleft()
            accepted = clean[:max(0, self.budget - len(self.attempts))]
            self.attempts.extend([now] * len(accepted))
        EXPORTED.labels("budget_dropped").inc(len(clean) - len(accepted))
        if not accepted:
            return SpanExportResult.SUCCESS
        try:
            result = self.delegate.export(accepted)
        except Exception:
            result = SpanExportResult.FAILURE  # Never log credentials or response bodies.
        EXPORTED.labels("attempted" if result == SpanExportResult.SUCCESS else "failed").inc(len(accepted))
        return result

    def shutdown(self):
        self.delegate.shutdown()


def processor(origin, key_file):
    transport = OTLPSpanExporter(
        endpoint=endpoint(origin), headers={"Authorization": "dataKey " + read_key(key_file)}, timeout=3,
    )
    return BatchSpanProcessor(
        PrivateExporter(transport), max_queue_size=64, max_export_batch_size=16,
        schedule_delay_millis=5000, export_timeout_millis=4000,
    )
