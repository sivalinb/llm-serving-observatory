"""Private, read-only dashboard API. No arbitrary PromQL, targets, files or shell access."""

import asyncio
import json
import math
import os
import re
import time
from collections import OrderedDict
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse

from .assistant import assistant, identity
from .assistant_store import EVENT_KINDS

JOBS = 'job=~"shared-assistant|shared-model"'
NAMES = re.compile(r"(?:assistant_[a-zA-Z0-9_]+|lab_resource_[a-zA-Z0-9_]+|"
                   r"process_[a-zA-Z0-9_]+|python_info|llamacpp:[a-zA-Z0-9_]+|up|scrape_[a-zA-Z0-9_]+)")
WINDOWS = {"15m": 900, "1h": 3600, "6h": 21600, "24h": 86400}
RECIPES = {
    "view:ttft_p95": ("seconds", "Estimated p95 first-content latency from 5-minute histogram rates; unstable with few requests.",
        'histogram_quantile(0.95,sum by (le) (rate(assistant_ttft_seconds_bucket{job="shared-assistant"}[5m])))'),
    "view:ttft_mean": ("seconds", "Mean first-content latency from 5-minute histogram rates; includes retrieval, not browser delay.",
        'sum(rate(assistant_ttft_seconds_sum{job="shared-assistant"}[5m])) / sum(rate(assistant_ttft_seconds_count{job="shared-assistant"}[5m]))'),
    "view:output_tokens_per_second": ("tokens/second", "Output tokens per wall-clock second over five minutes, not per-request decode speed.",
        'sum(rate(assistant_tokens_total{job="shared-assistant",kind="output"}[5m]))'),
    "view:cached_input_share": ("ratio", "Cached input divided by all input over five minutes. Cached input is not added to total tokens.",
        'sum(rate(assistant_tokens_total{job="shared-assistant",kind="cached_input"}[5m])) / sum(rate(assistant_tokens_total{job="shared-assistant",kind="input"}[5m]))'),
}
RULES = {
    "SharedTargetDown": "A private scrape target is unavailable for two minutes.",
    "SharedAnswerFailures": "At least two model answers failed or timed out in ten minutes.",
    "SharedGatewayMemoryPressure": "Gateway cgroup memory exceeds 85% of its limit for five minutes.",
}
SUMMARY_NAMES = (
    "up|assistant_active_requests|assistant_requests_total|assistant_tokens_total|"
    "assistant_citations_total|llamacpp:prompt_tokens_total|llamacpp:prompt_seconds_total|"
    "llamacpp:tokens_predicted_total|llamacpp:tokens_predicted_seconds_total|"
    "llamacpp:prompt_tokens_seconds|llamacpp:predicted_tokens_seconds"
)


def number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def safe_labels(labels):
    # Instance addresses and arbitrary engine labels are never sent to the browser.
    return {key: value for key, value in labels.items()
            if key in {"job", "kind", "status", "result", "le", "version", "implementation"}
            and isinstance(value, str) and re.fullmatch(r"[a-zA-Z0-9_.:+-]{1,64}", value)}


def vectors(data, limit=100):
    rows = data.get("result", [])
    return [{"name": row.get("metric", {}).get("__name__", ""),
             "labels": safe_labels(row.get("metric", {})),
             "timestamp": number(row.get("value", [None, None])[0]),
             "value": number(row.get("value", [None, None])[1])}
            for row in rows[:limit]]


class PrometheusReader:
    def __init__(self, url=None, client=None):
        self.url = (os.getenv("OBSERVATORY_PROMETHEUS_URL", "") if url is None else url).rstrip("/")
        parsed = urlsplit(self.url)
        if self.url and (parsed.scheme not in {"http", "https"} or not parsed.hostname
                         or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Prometheus must be a fixed HTTP(S) base URL without credentials/query")
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(3, connect=1), trust_env=False, follow_redirects=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=1),
        )
        self.cache = OrderedDict()
        self.lock = asyncio.Lock()

    async def close(self):
        await self.client.aclose()

    async def fetch(self, path, params=None):
        async with self.client.stream("GET", self.url + "/api/v1/" + path, params=params) as r:
            r.raise_for_status()
            body = bytearray()
            async for chunk in r.aiter_bytes():
                body.extend(chunk)
                if len(body) > 1024 * 1024:
                    raise ValueError("Telemetry response exceeds budget")
        payload = json.loads(body)
        if payload.get("status") != "success":
            raise ValueError("Telemetry query failed")
        return payload["data"]

    async def cached(self, key, builder):
        if not self.url:
            return {"state": "disabled", "data": None, "fetched_at": None, "age_seconds": None}
        async with self.lock:
            now = time.time()
            old = self.cache.get(key)
            if old is None or now - old["attempted_at"] >= 30:
                try:
                    async with asyncio.timeout(5):
                        data = await builder()
                    if len(json.dumps(data)) > 256 * 1024:
                        raise ValueError("Dashboard data exceeds budget")
                    old = {"data": data, "fetched_at": time.time(), "failed": False}
                except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, AttributeError, TimeoutError):
                    old = {"data": old["data"] if old else None,
                           "fetched_at": old["fetched_at"] if old else None, "failed": True}
                old["attempted_at"] = time.time()
                self.cache[key] = old
                self.cache.move_to_end(key)
                # Bound entry count AND serialized payload; no cache keys contain user identity.
                while len(self.cache) > 24 or sum(len(json.dumps(v)) for v in self.cache.values()) > 2 * 1024**2:
                    self.cache.popitem(last=False)
            age = time.time() - old["fetched_at"] if old["fetched_at"] else None
            usable = age is not None and age <= 120
            return {"state": ("stale" if old["failed"] else "ready") if usable else "unavailable",
                    "data": old["data"] if usable else None, "fetched_at": old["fetched_at"],
                    "age_seconds": age}

    async def catalog(self):
        async def build():
            names = await self.fetch("label/__name__/values", {"match[]": "{" + JOBS + "}",
                                      "start": time.time() - 300, "end": time.time()})
            meta = await self.fetch("metadata", {"limit": 512})
            result = []
            for name in sorted(n for n in names if isinstance(n, str) and NAMES.fullmatch(n))[:512]:
                family = name
                for suffix in ("_bucket", "_sum", "_count", "_created", "_total"):
                    if family not in meta and name.endswith(suffix):
                        family = name[:-len(suffix)]
                entry = (meta.get(family) or [{}])[0]
                result.append({"name": name, "type": str(entry.get("type", "unknown"))[:24],
                               "unit": str(entry.get("unit", ""))[:32],
                               "help": str(entry.get("help", "No exporter description available."))[:300]})
            result = [{"name": name, "type": "calculated", "unit": values[0], "help": values[1]}
                      for name, values in RECIPES.items()] + result
            return {"metrics": result, "limit": 512,
                    "scope": "Collected shared-assistant/shared-model metrics; reviewed label keys only."}
        return await self.cached("catalog", build)

    async def summary(self):
        async def build():
            data = await self.fetch("query", {"query": '{__name__=~"' + SUMMARY_NAMES + '",' + JOBS + '}',
                                              "timeout": "2s"})
            return {"series": vectors(data), "counter_scope": "Since each exporting process started; not lifetime ledger totals."}
        return await self.cached("summary", build)

    async def targets(self):
        async def build():
            data = await self.fetch("targets", {"state": "active"})
            return {"targets": [{"job": t["labels"]["job"],
                                  "health": "up" if t.get("health") == "up" else "down",
                                  "last_scrape": t.get("lastScrape"),
                                  "scrape_seconds": number(t.get("lastScrapeDuration"))}
                                 for t in data.get("activeTargets", [])
                                 if t.get("labels", {}).get("job") in {"shared-assistant", "shared-model"}][:2]}
        return await self.cached("targets", build)

    async def alerts(self):
        async def build():
            data = await self.fetch("rules", {"type": "alert"})
            found = {r["name"]: r for g in data.get("groups", []) if g.get("name") == "shared-host"
                     for r in g.get("rules", []) if r.get("name") in RULES}
            return {"notifications": False, "rules": [
                {"name": name, "description": description,
                 "state": found.get(name, {}).get("state", "not_loaded")
                 if found.get(name, {}).get("state", "not_loaded") in {"inactive", "pending", "firing", "not_loaded"} else "unknown",
                 "healthy": found.get(name, {}).get("health") == "ok",
                 "last_evaluation": found.get(name, {}).get("lastEvaluation")}
                for name, description in RULES.items()]}
        return await self.cached("alerts", build)

    async def chart(self, metric, window):
        catalog = await self.catalog()
        if catalog["state"] not in {"ready", "stale"}:
            return catalog
        if metric not in {m["name"] for m in catalog["data"]["metrics"]}:
            raise HTTPException(404, "Metric is not in this project's collected catalog")
        async def build():
            end = int(time.time() // 30 * 30)
            seconds = WINDOWS[window]
            step = max(30, math.ceil(seconds / 120))
            # No browser-provided selectors, expressions, URLs or resolution values.
            expression = RECIPES[metric][2] if metric in RECIPES else metric + "{" + JOBS + "}"
            data = await self.fetch("query_range", {"query": expression,
                       "start": end - seconds, "end": end, "step": step, "timeout": "2s"})
            rows = data.get("result", [])
            return {"metric": metric, "window": window, "start": end - seconds, "end": end,
                    "step": step, "truncated": len(rows) > 8,
                    "series": [{"labels": safe_labels(row.get("metric", {})),
                                "points": [[number(p[0]), number(p[1])] for p in row.get("values", [])[:121]]}
                               for row in rows[:8]],
                    "note": "Raw exporter values; counters reset on restart. Query timestamps are not scrape freshness."}
        return await self.cached((metric, window), build)


class DashboardLimit:
    def __init__(self):
        self.users = OrderedDict()

    def admit(self, uid):
        now = time.monotonic()
        start, count = self.users.get(uid, (now, 0))
        if now - start >= 60:
            start, count = now, 0
        if count >= 60:
            raise HTTPException(429, "Dashboard request limit; retry in one minute", headers={"Retry-After": "60"})
        self.users[uid] = (start, count + 1)
        self.users.move_to_end(uid)
        while len(self.users) > 512:
            self.users.popitem(last=False)


async def viewer(request: Request, user=Depends(identity)):
    request.app.state.dashboard_limit.admit(user["id"])
    return user


async def operator(request: Request, user=Depends(viewer)):
    if not request.app.state.assistant.store.is_operator(user["id"]):
        raise HTTPException(403, "Operator access required; assistant invites do not grant it")
    return user


def scope_check(svc, user, scope):
    if scope == "all" and not svc.store.is_operator(user["id"]):
        raise HTTPException(403, "Operator access required for global records")
    return scope == "all"


router = APIRouter()


@router.get("/observability")
def page():
    return FileResponse(Path(__file__).parent / "static" / "observability.html")


@router.get("/api/observability/session")
async def session(request: Request, user=Depends(viewer)):
    return {"user_id": user["id"], "is_operator": request.app.state.assistant.store.is_operator(user["id"]),
            "refresh_seconds": 30, "trace_backend": "not_configured", "log_source": "sanitized_application_events"}


@router.get("/api/observability/overview", dependencies=[Depends(operator)])
async def overview(request: Request):
    reader = request.app.state.telemetry
    return {"summary": await reader.summary(), "targets": await reader.targets(),
            "alerts": await reader.alerts(), "gateway_resources": request.app.state.resources.snapshot(),
            "coverage": {"model_cgroup_history": "not_instrumented", "gpu_hbm": "no_gpu_in_cpu_profile",
                         "remote_kv_transfer": "not_instrumented", "traces": "no_persisted_trace_backend",
                         "logs": "application_events_only_not_container_logs"}}


@router.get("/api/observability/catalog", dependencies=[Depends(operator)])
async def catalog(request: Request):
    return await request.app.state.telemetry.catalog()


@router.get("/api/observability/chart", dependencies=[Depends(operator)])
async def chart(request: Request, metric: str = Query(min_length=1, max_length=128, pattern=r"^[a-zA-Z_:][a-zA-Z0-9_:]*$"),
                window: Literal["15m", "1h", "6h", "24h"] = "1h"):
    if metric not in RECIPES and not NAMES.fullmatch(metric):
        raise HTTPException(404, "Metric namespace is not enabled")
    return await request.app.state.telemetry.chart(metric, window)


@router.get("/api/observability/requests")
async def requests(user=Depends(viewer), svc=Depends(assistant),
                   scope: Literal["mine", "all"] = "mine", offset: int = Query(0, ge=0, le=1000),
                   status: Literal["ok", "error", "timeout", "cancelled"] | None = None,
                   request_id: str = Query("", max_length=32, pattern=r"^[a-f0-9]*$")):
    return svc.store.explore(user["id"], global_scope=scope_check(svc, user, scope),
                             offset=offset, status=status, request_id=request_id)


@router.get("/api/observability/events")
async def events(user=Depends(viewer), svc=Depends(assistant), scope: Literal["mine", "all"] = "mine",
                 before: int | None = Query(None, ge=1), kind: str | None = Query(None, max_length=32),
                 request_id: str = Query("", max_length=32, pattern=r"^[a-f0-9]*$")):
    if kind is not None and kind not in EVENT_KINDS:
        raise HTTPException(422, "Unknown event kind")
    return svc.store.events(user["id"], global_scope=scope_check(svc, user, scope),
                            before=before, kind=kind, request_id=request_id)
