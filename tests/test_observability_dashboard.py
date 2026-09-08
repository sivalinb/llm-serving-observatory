import asyncio
import json
import re
import time
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from observatory.app import create_app
from observatory.assistant_store import AssistantStore
from observatory.observability import DashboardLimit, PrometheusReader, safe_labels

ROOT = Path(__file__).resolve().parents[1]


def credentials(store):
    data = store.redeem(store.invite(), "Dashboard test")
    return data["user_id"], {"Authorization": "Bearer " + data["api_key"]}


def receipt(store, uid, ident):
    user = dict(store.db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    rid = store.reserve(user, ident, 500, 100000, 90)
    record = {"id": rid, "status": "ok", "created": time.time(), "tokens": {"input": 100, "output": 20, "total": 120},
              "ttft_ms": 20, "duration_ms": 50, "retrieval_ms": 1, "trace_id": "a" * 32}
    store.finish(rid, record)
    return rid


class PromFixture:
    def __init__(self):
        self.calls = []
        self.failed = False

    def __call__(self, request):
        self.calls.append(request)
        if self.failed:
            return httpx.Response(503, text="PRIVATE upstream failure detail")
        path = request.url.path
        if path.endswith("/label/__name__/values"):
            assert 'shared-assistant|shared-model' in request.url.params['match[]']
            data = ["assistant_tokens_total", "lab_resource_process_rss_bytes", "llamacpp:prompt_tokens_total", "other_private_secret"]
        elif path.endswith("/metadata"):
            data = {"assistant_tokens": [{"type": "counter", "help": "Reported tokens", "unit": "tokens"}]}
        elif path.endswith("/query_range"):
            assert "shared-assistant" in request.url.params["query"]
            assert request.url.params["timeout"] == "2s"
            data = {"resultType": "matrix", "result": [
                {"metric": {"job": "shared-assistant", "kind": "input", "instance": "PRIVATE-HOST", "tenant": "PRIVATE-ID"},
                 "values": [[1000 + i, "NaN" if i == 0 else "0"] for i in range(130)]}
                for _ in range(10)]}
        elif path.endswith("/query"):
            data = {"resultType": "vector", "result": [{"metric": {"__name__": "assistant_tokens_total", "job": "shared-assistant", "kind": "input", "instance": "PRIVATE-HOST"}, "value": [time.time(), "0"]}]}
        elif path.endswith("/targets"):
            data = {"activeTargets": [{"labels": {"job": "shared-assistant"}, "health": "up", "lastScrape": "2026-09-08T00:00:00Z", "lastError": "PRIVATE-ERROR", "scrapeUrl": "PRIVATE-URL"}, {"labels": {"job": "unrelated"}}]}
        elif path.endswith("/rules"):
            data = {"groups": [{"name": "shared-host", "rules": [{"name": "SharedTargetDown", "state": "inactive", "health": "ok", "annotations": {"secret": "PRIVATE"}}]}, {"name": "unrelated", "rules": [{"name": "PRIVATE"}]}]}
        else:
            raise AssertionError(path)
        return httpx.Response(200, json={"status": "success", "data": data})

    def reader(self):
        return PrometheusReader("http://private-prometheus:9090", httpx.AsyncClient(transport=httpx.MockTransport(self)))


def test_default_denial_role_grant_and_immediate_revoke(tmp_path):
    fixture = PromFixture()
    app = create_app(db_path=tmp_path / "lab.sqlite", assistant_only=True, telemetry=fixture.reader())
    with TestClient(app) as client:
        store = app.state.assistant.store
        uid, key = credentials(store)
        for path in ["session", "overview", "catalog", "chart?metric=assistant_tokens_total", "requests", "events"]:
            response = client.get("/api/observability/" + path)
            assert response.status_code == 401
            assert response.headers["cache-control"] == "no-store"
        assert client.get("/api/observability/session", headers=key).json()["is_operator"] is False
        for path in ["overview", "catalog", "chart?metric=assistant_tokens_total", "requests?scope=all", "events?scope=all"]:
            assert client.get("/api/observability/" + path, headers=key).status_code == 403
        assert not fixture.calls
        assert client.post("/api/observability/operator", headers=key).status_code == 404
        assert client.get("/api/observability/session?is_operator=true", headers=key).json()["is_operator"] is False
        store.set_operator(uid, True)
        result = client.get("/api/observability/overview", headers=key)
        assert result.status_code == 200 and result.json()["summary"]["state"] == "ready"
        assert "PRIVATE" not in result.text and "unrelated" not in result.text
        assert result.headers["vary"] == "Authorization"
        store.set_operator(uid, False)
        assert client.get("/api/observability/overview", headers=key).status_code == 403
        store.revoke(uid)
        assert client.get("/api/observability/session", headers=key).status_code == 401


def test_request_and_event_ownership_and_history_delete(tmp_path):
    app = create_app(db_path=tmp_path / "lab.sqlite", assistant_only=True)
    with TestClient(app) as client:
        store = app.state.assistant.store
        uid, key = credentials(store)
        other, other_key = credentials(store)
        rid = receipt(store, uid, "a")
        receipt(store, other, "b")
        own = client.get("/api/observability/requests?user_id=" + other, headers=key).json()["records"]
        assert len(own) == 1 and own[0]["id"] == rid
        assert client.get("/api/observability/requests?request_id=" + rid, headers=other_key).json()["records"] == []
        assert client.get("/api/observability/events?request_id=" + rid, headers=other_key).json()["events"] == []
        events = client.get("/api/observability/events?request_id=" + rid, headers=key).json()["events"]
        assert {e["kind"] for e in events} == {"request_admitted", "request_finished"}
        assert any(e["trace_id"] == "a" * 32 for e in events)
        store.set_operator(uid, True)
        assert len(client.get("/api/observability/requests?scope=all", headers=key).json()["records"]) == 2
        client.delete("/api/service/history", headers=key)
        assert client.get("/api/observability/requests", headers=key).json()["records"] == []
        assert client.get("/api/observability/events?request_id=" + rid, headers=key).json()["events"] == []
        assert store.usage(uid)["requests_today"] == 1


def test_events_closed_schema_coalescing_retention_and_pagination(tmp_path):
    store = AssistantStore(tmp_path / "s.sqlite")
    uid, _ = credentials(store)
    with pytest.raises(TypeError):
        store.event("request_rejected", uid=uid, message="PASSWORD")
    with pytest.raises(ValueError):
        store.event("PASSWORD")
    store.event("request_rejected", uid=uid, code="PASSWORD", trace_id="SECRET", rid="PROMPT", duration_ms=float("nan"))
    assert "PASSWORD" not in str(list(store.db.iterdump()))
    for _ in range(100):
        store.event("request_rejected", uid=uid, code="capacity")
    assert len(store.events(uid)["events"]) == 2
    store.db.execute("UPDATE service_events SET created=0")
    assert store.events(uid)["events"] == []
    for _ in range(2005):
        store.event("request_admitted", uid=uid, rid="a" * 32)
    assert store.db.execute("SELECT count(*) FROM service_events").fetchone()[0] == 2000
    first = store.events(uid)
    second = store.events(uid, before=first["next_before"])
    assert len(first["events"]) == len(second["events"]) == 50
    assert not {e["id"] for e in first["events"]} & {e["id"] for e in second["events"]}
    store.close()


def test_operator_grants_and_events_survive_backup(tmp_path):
    store = AssistantStore(tmp_path / "s.sqlite")
    uid, key = credentials(store)
    assert not store.is_operator(uid)
    with pytest.raises(ValueError):
        store.set_operator("missing", True)
    store.set_operator(uid, True)
    store.backup(tmp_path / "backup.sqlite")
    restored = AssistantStore(tmp_path / "backup.sqlite")
    assert restored.authenticate(key["Authorization"][7:])["id"] == uid
    assert restored.is_operator(uid)
    assert restored.events(uid)["events"][0]["kind"] == "operator_granted"
    assert (tmp_path / "backup.sqlite").stat().st_mode & 0o777 == 0o600
    restored.close()
    store.close()


@pytest.mark.asyncio
async def test_catalog_metadata_scope_and_bounded_charts():
    fixture = PromFixture()
    reader = fixture.reader()
    data = (await reader.catalog())["data"]
    names = {m["name"] for m in data["metrics"]}
    assert "other_private_secret" not in names and "view:ttft_p95" in names
    metric = next(m for m in data["metrics"] if m["name"] == "assistant_tokens_total")
    assert metric["help"] == "Reported tokens" and metric["type"] == "counter"
    for window, seconds in [("15m", 900), ("1h", 3600), ("6h", 21600), ("24h", 86400)]:
        packet = await reader.chart("assistant_tokens_total", window)
        chart = packet["data"]
        assert chart["end"] - chart["start"] == seconds
        assert chart["truncated"] and len(chart["series"]) == 8
        assert len(chart["series"][0]["points"]) == 121
        assert chart["series"][0]["points"][0][1] is None
        assert chart["series"][0]["points"][1][1] == 0
        assert "PRIVATE" not in json.dumps(chart)
    with pytest.raises(Exception, match="404"):
        await reader.chart("assistant_not_discovered", "1h")
    await reader.close()


@pytest.mark.asyncio
async def test_cache_coalesces_queries_stale_expiry_and_no_error_leaks():
    fixture = PromFixture()
    reader = fixture.reader()
    results = await asyncio.gather(*(reader.summary() for _ in range(8)))
    assert len(fixture.calls) == 1 and all(r["state"] == "ready" for r in results)
    assert results[0]["data"]["series"][0]["value"] == 0
    fixture.failed = True
    reader.cache["summary"]["attempted_at"] -= 31
    reader.cache["summary"]["fetched_at"] -= 31
    result = await reader.summary()
    assert result["state"] == "stale" and result["data"] is not None
    assert "PRIVATE" not in json.dumps(result)
    await reader.summary()
    assert len(fixture.calls) == 2  # Negative caching also prevents retry storms.
    reader.cache["summary"]["attempted_at"] -= 31
    reader.cache["summary"]["fetched_at"] -= 121
    result = await reader.summary()
    assert result["state"] == "unavailable" and result["data"] is None
    await reader.close()


@pytest.mark.asyncio
async def test_disabled_oversized_and_redirected_backend():
    reader = PrometheusReader(url="")
    assert (await reader.summary())["state"] == "disabled"
    await reader.close()
    for response in [httpx.Response(200, content=b"x" * (1024**2 + 1)), httpx.Response(302, headers={"Location": "http://other-host"})]:
        calls = []
        def handler(request):
            calls.append(request)
            return response
        reader = PrometheusReader("http://private-prometheus", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        assert (await reader.summary())["state"] == "unavailable"
        assert len(calls) == 1
        await reader.close()
    for url in ["file:///etc/passwd", "http://user:secret@host", "http://host?target=other", "http://host#x"]:
        with pytest.raises(ValueError):
            PrometheusReader(url)


def test_query_injection_limits_and_safe_labels(tmp_path):
    fixture = PromFixture()
    app = create_app(db_path=tmp_path / "lab.sqlite", assistant_only=True, telemetry=fixture.reader())
    with TestClient(app) as client:
        uid, key = credentials(app.state.assistant.store)
        app.state.assistant.store.set_operator(uid, True)
        for query in ["metric=up%7D%20or%20secret", "metric=assistant_tokens_total&window=7d", "metric=http://other-host"]:
            assert client.get("/api/observability/chart?" + query, headers=key).status_code == 422
        assert client.get("/api/observability/chart?metric=secret", headers=key).status_code == 404
        for path in ["requests?offset=1001", "requests?request_id=%25", "events?before=0", "events?kind=arbitrary"]:
            assert client.get("/api/observability/" + path, headers=key).status_code == 422
        assert not fixture.calls
    assert safe_labels({"instance": "private", "job": "shared-model", "kind": "<script>", "tenant": "secret"}) == {"job": "shared-model"}


def test_dashboard_rate_budget():
    limiter = DashboardLimit()
    for _ in range(60):
        limiter.admit("user")
    with pytest.raises(Exception, match="429"):
        limiter.admit("user")
    start, _ = limiter.users["user"]
    limiter.users["user"] = (start - 61, 60)
    limiter.admit("user")
    for i in range(600):
        limiter.admit(str(i))
    assert len(limiter.users) == 512


@pytest.mark.asyncio
async def test_cache_count_is_bounded():
    reader = PrometheusReader("http://private-prometheus")
    async def build():
        return {"data": 1}
    for index in range(40):
        await reader.cached(str(index), build)
    assert len(reader.cache) == 24
    await reader.close()


def test_dashboard_assets_private_export_and_dom_contract(tmp_path):
    source = (ROOT / "observatory/static/observability.html").read_text()
    script = (ROOT / "observatory/static/observability.js").read_text()
    ids = re.findall(r'id="([^"]+)"', source)
    assert len(ids) == len(set(ids))
    assert set(re.findall(r"\$\('([^']+)'\)", script)) <= set(ids)
    assert "innerHTML" not in script and "localStorage" not in script and "sessionStorage" not in script
    assert "AbortController" in script and "visibilitychange" in script and "pagehide" in script
    assert "no arbitrary PromQL" in source and "not a Docker log terminal" in source
    import runpy
    build = runpy.run_path(str(ROOT / "scripts/build_portfolio.py"))["build"]
    build(tmp_path)
    assert not (tmp_path / "observability").exists()
    assert not any("observability" in p.name for p in tmp_path.rglob("*"))
