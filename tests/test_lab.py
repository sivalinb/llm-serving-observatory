import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags, set_span_in_context
from pydantic import ValidationError

from observatory.app import create_app
from observatory.models import BenchmarkRequest, LabRequest
from observatory.service import Service, percentile, summarize
from observatory.simulation import KV_BYTES_PER_TOKEN, PrefixCache
from observatory.store import Store
from observatory.upstream import normalize_usage, sse_json


@pytest.fixture
def fast():
    return LabRequest(
        input_tokens=8,
        output_tokens=4,
        prefix_tokens=4,
        prefill_tps=100000,
        decode_tps=1000,
        transfer_mb_s=100000,
        transfer_latency_ms=0,
    )


@pytest.fixture
async def service():
    s = Service(Store(":memory:"))
    yield s
    await s.client.aclose()
    s.store.close()


async def test_simulation_ledger_cache_and_transfer(service, fast):
    first = await service.collect(fast)
    second = await service.collect(fast)
    assert first["status"] == "ok"
    assert first["tokens"]["total"] == 12
    assert first["tokens"]["cached_input"] == 0
    assert second["tokens"]["cached_input"] == 4
    assert first["kv_transfer_bytes"] == 8 * KV_BYTES_PER_TOKEN
    assert first["tpot_ms"] > 0
    assert len(first["itl_ms"]) == 3
    assert service.inflight == 0
    assert "prompt" not in json.dumps(service.store.list())


async def test_combined_has_no_transfer(service, fast):
    record = await service.collect(fast.model_copy(update={"mode": "combined"}))
    assert record["kv_transfer_bytes"] == 0
    assert not any(p["name"] == "kv.transfer" for p in record["phases"])


async def test_reasoning_is_subset_and_single_visible_tpot_null(service, fast):
    r = await service.collect(fast.model_copy(update={"reasoning_tokens": 3}))
    assert r["tokens"]["output"] == 4
    assert r["tokens"]["visible_output"] == 1
    assert r["tokens"]["total"] == 12
    assert r["tpot_ms"] is None
    assert r["slo_met"] is None


async def test_transfer_failure_is_retained_and_capacity_recovers(service, fast):
    r = await service.collect(fast.model_copy(update={"fault": "transfer_failure"}))
    assert r["status"] == "error"
    assert r["ttft_ms"] is None
    assert service.inflight == 0
    assert (await service.collect(fast))["status"] == "ok"


async def test_cancel_releases_combined_slot(service, fast):
    request = fast.model_copy(update={"mode": "combined", "output_tokens": 100, "decode_tps": 10})
    task = asyncio.create_task(service.collect(request))
    await asyncio.sleep(0.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert service.inflight == 0
    assert service.store.list()[0]["status"] == "cancelled"
    assert (
        await asyncio.wait_for(service.collect(fast.model_copy(update={"mode": "combined"})), 2)
    )["status"] == "ok"


async def test_close_immediately_after_start_releases_request(service, fast):
    generator = service.run(fast)
    assert (await anext(generator))["type"] == "start"
    await generator.aclose()
    assert service.inflight == 0
    assert service.store.list()[0]["status"] == "cancelled"


def test_cache_eviction_and_oversize(fast):
    cache = PrefixCache("test", 4 * KV_BYTES_PER_TOKEN)
    cache.insert(fast)
    assert cache.lookup(fast) == 4
    other = fast.model_copy(update={"prefix_key": "other"})
    cache.insert(other)
    assert cache.lookup(fast) == 0
    assert cache.bytes == cache.capacity
    cache.insert(fast.model_copy(update={"prefix_tokens": 8}))
    assert cache.bytes == cache.capacity


def test_usage_unknowns_and_no_double_count():
    usage = normalize_usage(
        {
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "prompt_tokens_details": {"cached_tokens": 80},
            "completion_tokens_details": {"reasoning_tokens": 10},
        }
    )
    assert usage["total"] == 140
    assert usage["visible_output"] == 30
    assert normalize_usage({"prompt_tokens": 100, "completion_tokens": 40})["reasoning"] is None
    assert normalize_usage({})["total"] is None
    assert normalize_usage({"prompt_tokens": -1})["input"] is None


async def test_upstream_multitoken_chunks_and_usage(service, fast, monkeypatch):
    monkeypatch.setenv("UPSTREAM_URL", "http://engine/v1")
    monkeypatch.setenv("UPSTREAM_MODEL", "test-model")
    events = [
        {"choices": [{"delta": {"role": "assistant"}}]},
        {"choices": [{"delta": {"content": "several words at once"}}]},
        {"choices": [{"delta": {"content": " second chunk"}, "finish_reason": "stop"}]},
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 8}},
    ]

    def respond(request):
        assert json.loads(request.content)["model"] == "test-model"
        assert "traceparent" in request.headers
        return httpx.Response(
            200,
            text="".join("data: " + json.dumps(e) + "\n\n" for e in events) + "data: [DONE]\n\n",
        )

    await service.client.aclose()
    service.client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    r = await service.collect(fast.model_copy(update={"mode": "upstream"}))
    assert r["status"] == "ok"
    assert r["tokens"]["output"] == 8
    assert r["visible_chunks"] == 2
    assert r["itl_ms"] == []
    assert len(r["chunk_gaps_ms"]) == 1
    assert r["tpot_ms"] is None  # unknown reasoning split; no guessed token counts


async def test_upstream_error_does_not_leak_body(service, fast, monkeypatch):
    monkeypatch.setenv("UPSTREAM_URL", "http://engine/v1")
    monkeypatch.setenv("UPSTREAM_MODEL", "test-model")
    await service.client.aclose()
    service.client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(401, text="secret-token"))
    )
    r = await service.collect(fast.model_copy(update={"mode": "upstream"}))
    assert r["status"] == "error"
    assert "secret-token" not in json.dumps(r)


async def test_incomplete_upstream_is_error(service, fast, monkeypatch):
    monkeypatch.setenv("UPSTREAM_URL", "http://engine/v1")
    monkeypatch.setenv("UPSTREAM_MODEL", "test-model")
    await service.client.aclose()
    service.client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n'
            )
        )
    )
    r = await service.collect(fast.model_copy(update={"mode": "upstream"}))
    assert r["status"] == "error"


async def test_sse_crlf_and_multiline():
    response = httpx.Response(
        200, text=': ping\r\ndata: {"a":\r\ndata: 1}\r\n\r\ndata: [DONE]\r\n\r\n'
    )
    assert [e async for e in sse_json(response)] == [{"a": 1}]


async def test_benchmark_counts_warmups_and_percentiles(service, fast):
    events = [
        e
        async for e in service.benchmark(
            BenchmarkRequest(request=fast, requests=3, concurrency=2, warmup=1)
        )
    ]
    experiment = events[-1]["experiment"]
    assert experiment["status"] == "ok"
    assert len(experiment["results"]) == 2
    assert all(r["summary"]["requests"] == 3 for r in experiment["results"])
    assert len(service.store.list()) == 8
    assert service.benchmark_busy is False
    assert percentile([0, 10], 0.95) == 9.5
    assert summarize([], 1)["ttft_p95_ms"] is None


async def test_trace_parent_propagated(service, fast):
    parent = SpanContext(0x123456789, 0x12345678, True, TraceFlags(1))
    events = [
        e async for e in service.run(fast, context=set_span_in_context(NonRecordingSpan(parent)))
    ]
    assert events[-1]["record"]["trace_id"] == format(parent.trace_id, "032x")


def test_validation():
    with pytest.raises(ValidationError):
        LabRequest(output_tokens=4, reasoning_tokens=4)
    with pytest.raises(ValidationError):
        LabRequest(transfer_mb_s=0)
    with pytest.raises(ValidationError):
        LabRequest(prefill_tps=float("nan"))


def test_http_auth_chat_and_unknown_fields(monkeypatch):
    monkeypatch.setenv("LAB_API_KEY", "test-key")
    with TestClient(create_app(":memory:")) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/api/records").status_code == 401
        assert client.post("/api/run", json={}).status_code == 401
        h = {"Authorization": "Bearer test-key"}
        assert client.post("/api/run", headers=h, json={"unknown": 1}).status_code == 422
        response = client.post(
            "/v1/chat/completions",
            headers=h,
            json={"messages": [{"role": "user", "content": "hello"}], "max_tokens": 2},
        )
        assert response.status_code == 200
        assert response.json()["usage"]["completion_tokens"] == 2
        assert client.get("/api/records", headers=h).json()["records"][0]["status"] == "ok"
        assert client.get("/api/records/missing", headers=h).status_code == 404


def test_stream_chat_protocol():
    with TestClient(create_app(":memory:")) as client:
        r = client.post(
            "/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 2,
                "stream": True,
                "stream_options": {"include_usage": True},
            },
        )
        assert r.text.endswith("data: [DONE]\n\n")
        assert '"usage"' in r.text
        assert '"finish_reason": "length"' in r.text
