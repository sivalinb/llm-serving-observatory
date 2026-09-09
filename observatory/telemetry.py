"""Bounded metric labels, explicit provenance, and W3C trace propagation."""

import os
from contextlib import contextmanager
from time import perf_counter

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from prometheus_client import Counter, Gauge, Histogram

PROVIDER = TracerProvider(
    resource=Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "observatory-gateway"),
            "service.version": "0.2.0",
        }
    )
)
if os.getenv("OCI_APM_ENDPOINT"):
    from observatory.cloud_tracing import processor

    PROVIDER.add_span_processor(processor(os.environ["OCI_APM_ENDPOINT"], os.environ["OCI_APM_KEY_FILE"]))
elif os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
    PROVIDER.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
trace.set_tracer_provider(PROVIDER)
TRACER = trace.get_tracer("observatory", "0.2.0")
LABELS = ["mode", "source"]
BUCKETS = (0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 0.75, 1, 2, 5, 10, 30, 60, 120)
REQUESTS = Counter(
    "lab_requests_total", "Completed requests by terminal status", LABELS + ["status"]
)
STAGES = Histogram(
    "lab_stage_seconds", "Stage wall duration; seconds", LABELS + ["stage"], buckets=BUCKETS
)
TTFT = Histogram(
    "lab_ttft_seconds", "Gateway dispatch to first visible content", LABELS, buckets=BUCKETS
)
E2E = Histogram(
    "lab_request_seconds",
    "Full request wall time including stream completion",
    LABELS,
    buckets=BUCKETS,
)
TPOT = Histogram(
    "lab_tpot_seconds", "Visible decode duration / (visible tokens - 1)", LABELS, buckets=BUCKETS
)
ITL = Histogram(
    "lab_itl_seconds",
    "Simulator per-token interval; not upstream chunk interval",
    LABELS,
    buckets=BUCKETS,
)
CHUNK_GAP = Histogram(
    "lab_chunk_gap_seconds", "Upstream content chunk arrival interval", LABELS, buckets=BUCKETS
)
TOKENS = Counter(
    "lab_tokens_total",
    "Token accounting; output includes reasoning",
    LABELS + ["kind", "provenance"],
)
TRANSFER = Counter("lab_kv_transfer_bytes_total", "Modeled KV bytes, not actual wire bytes", LABELS)
GOOD = Counter("lab_slo_requests_total", "Requests meeting both TTFT and TPOT targets", LABELS)
ACTIVE = Gauge("lab_active_requests", "Gateway in-flight requests")
CACHE = Gauge("lab_prefix_cache_bytes", "Modeled prefix cache bytes", ["pool"])
CACHE_CAPACITY = Gauge("lab_prefix_cache_capacity_bytes", "Modeled prefix cache capacity", ["pool"])
EVICTIONS = Counter("lab_cache_evictions_total", "Simulated prefix LRU evictions", ["pool"])
HITS = Counter("lab_prefix_queries_total", "Simulated prefix lookups", ["pool", "result"])
WAITING = Gauge("lab_worker_waiting", "Requests awaiting simulated worker", ["pool"])
RUNNING = Gauge("lab_worker_running", "Requests occupying simulated worker", ["pool"])


@contextmanager
def phase(record, name):
    begin = perf_counter()
    with TRACER.start_as_current_span(name, attributes={"lab.source": record["source"]}):
        try:
            yield
        finally:
            duration = perf_counter() - begin
            record["phases"].append(
                {
                    "name": name,
                    "offset_ms": (begin - record["_start"]) * 1000,
                    "duration_ms": duration * 1000,
                    "clock": record.get("clock", "gateway"),
                }
            )
            STAGES.labels(record["mode"], record["source"], name).observe(duration)


def observe_record(record):
    mode, source = record["mode"], record["source"]
    REQUESTS.labels(mode, source, record["status"]).inc()
    E2E.labels(mode, source).observe(record["duration_ms"] / 1000)
    if record.get("ttft_ms") is not None:
        TTFT.labels(mode, source).observe(record["ttft_ms"] / 1000)
    if record.get("tpot_ms") is not None:
        TPOT.labels(mode, source).observe(record["tpot_ms"] / 1000)
    for kind, value in record.get("tokens", {}).items():
        if value is not None:
            TOKENS.labels(mode, source, kind, record["token_provenance"]).inc(value)
    if record.get("kv_transfer_bytes"):
        TRANSFER.labels(mode, source).inc(record["kv_transfer_bytes"])
    if record.get("slo_met"):
        GOOD.labels(mode, source).inc()
