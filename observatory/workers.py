"""Separate simulated worker services. No GPU tensors cross these endpoints."""

import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import StreamingResponse
from opentelemetry.propagate import extract
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from starlette.requests import Request

from .models import LabRequest
from .resources import ResourceMonitor
from .simulation import Simulator, worker_record
from .telemetry import TRACER


@asynccontextmanager
async def lifespan(app):
    monitor = ResourceMonitor()
    REGISTRY.register(monitor)
    await monitor.start()
    try:
        yield
    finally:
        await monitor.stop()
        REGISTRY.unregister(monitor)


app = FastAPI(title="Observatory simulated worker", lifespan=lifespan)
sim = Simulator()


def authorize(x_worker_token: str = Header(default="")):
    expected = os.getenv("WORKER_TOKEN", "local-development-only")
    if not secrets.compare_digest(x_worker_token, expected):
        raise HTTPException(401, "Worker authorization required")


@app.get("/healthz")
def health():
    return {"status": "ok", "source": "simulated"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.post("/prefill", dependencies=[Depends(authorize)])
async def prefill(req: LabRequest, request: Request):
    record = worker_record()
    with TRACER.start_as_current_span("worker.prefill", context=extract(request.headers)):
        async with asyncio.timeout(60):
            async with sim.slot("prefill", record):
                kv = await sim.prefill(req, record)
    return {"kv": kv, "phases": record["phases"]}


@app.post("/decode", dependencies=[Depends(authorize)])
async def decode(req: LabRequest, request: Request):
    context = extract(request.headers)

    async def stream():
        record = worker_record()
        with TRACER.start_as_current_span("worker.decode", context=context):
            try:
                async with asyncio.timeout(60):
                    async with sim.slot("decode", record):
                        async for word in sim.decode(req, record):
                            yield "data: " + json.dumps({"content": word}) + "\n\n"
                yield "data: " + json.dumps({"phases": record["phases"]}) + "\n\n"
                yield "data: [DONE]\n\n"
            except TimeoutError:
                yield 'data: {"error":"worker_timeout"}\n\n'

    return StreamingResponse(stream(), media_type="text/event-stream")
