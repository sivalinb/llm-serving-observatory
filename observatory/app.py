import json
import logging
import os
import secrets
import time
from contextlib import aclosing, asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from opentelemetry.propagate import extract
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, generate_latest

from .assistant import create_assistant
from .assistant import router as assistant_router
from .hardware import HardwareRequest, estimate_with_sweep
from .models import BenchmarkRequest, ChatRequest, LabRequest
from .resources import ResourceMonitor
from .service import Service, summarize
from .store import Store

logging.basicConfig(level=logging.INFO, format="%(message)s")


def require_key(authorization: str = Header(default="")):
    expected = os.getenv("LAB_API_KEY")
    if expected and not secrets.compare_digest(authorization, "Bearer " + expected):
        raise HTTPException(401, "Bearer API key required")


def create_app(db_path=None, service=None, assistant_service=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.service = service or Service(
            Store(db_path or os.getenv("LAB_DB", "data/lab.sqlite"))
        )
        app.state.resources = ResourceMonitor()
        assistant_path = (
            str(Path(db_path).with_name("assistant.sqlite"))
            if db_path and str(db_path) != ":memory:"
            else ":memory:"
            if db_path
            else os.getenv("ASSISTANT_DB", "data/assistant.sqlite")
        )
        app.state.assistant = assistant_service or create_assistant(assistant_path)
        REGISTRY.register(app.state.resources)
        await app.state.resources.start()
        try:
            yield
        finally:
            await app.state.resources.stop()
            REGISTRY.unregister(app.state.resources)
            await app.state.service.client.aclose()
            app.state.service.store.close()
            await app.state.assistant.client.aclose()
            app.state.assistant.store.close()

    app = FastAPI(title="LLM Serving Observatory", version="0.3.0", lifespan=lifespan)
    app.include_router(assistant_router)
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static, check_dir=False), name="static")

    @app.middleware("http")
    async def headers(request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if request.url.path.startswith("/api/service"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
        )
        if request.url.path in {"/docs", "/redoc"}:
            # FastAPI's built-in documentation loads versioned UI assets from jsDelivr.
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
                "img-src 'self' data: https://fastapi.tiangolo.com; "
                "connect-src 'self'; frame-ancestors 'none'"
            )
        return response

    def svc(request: Request):
        return request.app.state.service

    def check(req, service):
        if req.mode == "upstream" and not service.config()["upstream_available"]:
            raise HTTPException(503, "Set UPSTREAM_URL and UPSTREAM_MODEL to enable real inference")
        if service.inflight >= 16:
            raise HTTPException(429, "Lab is at capacity; retry after a request completes")

    async def encode(events):
        async with aclosing(events):
            async for event in events:
                yield "data: " + json.dumps(event, allow_nan=False) + "\n\n"

    def streamed(events):
        return StreamingResponse(
            encode(events),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/")
    def home():
        return FileResponse(static / "home.html")

    @app.get("/lab")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/healthz")
    def health():
        return {"status": "ok", "version": "0.3.0"}

    @app.post("/api/hardware/estimate", dependencies=[Depends(require_key)])
    def hardware_estimate(req: HardwareRequest):
        return estimate_with_sweep(req)

    @app.get("/api/hardware/resources", dependencies=[Depends(require_key)])
    def hardware_resources(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        return request.app.state.resources.snapshot()

    @app.get("/api/config")
    def config(service=Depends(svc)):
        return service.config()

    @app.get("/metrics")
    def metrics():
        # Bound to localhost / private Docker network; Caddy blocks this path.
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.post("/api/run", dependencies=[Depends(require_key)])
    async def run(req: LabRequest, request: Request, service=Depends(svc)):
        check(req, service)
        return streamed(service.run(req, extract(request.headers)))

    @app.post("/api/benchmark", dependencies=[Depends(require_key)])
    async def benchmark(req: BenchmarkRequest, service=Depends(svc)):
        check(req.request, service)
        if service.benchmark_busy:
            raise HTTPException(409, "One benchmark at a time; wait for the current run")
        service.benchmark_busy = True
        return streamed(service.benchmark(req))

    @app.get("/api/records", dependencies=[Depends(require_key)])
    def records(service=Depends(svc)):
        records = service.store.list(limit=100)
        return {
            "records": records,
            "summary": summarize(records, 1),
            "note": "Last 100 retained requests; use benchmarks or Prometheus for rates.",
        }

    @app.get("/api/benchmarks", dependencies=[Depends(require_key)])
    def benchmarks(service=Depends(svc)):
        return service.store.list("benchmark", 20)

    @app.get("/api/records/{record_id}", dependencies=[Depends(require_key)])
    def record(record_id: str, service=Depends(svc)):
        result = service.store.get(record_id)
        if result is None:
            raise HTTPException(404, "Record not found")
        return result

    @app.post("/v1/chat/completions", dependencies=[Depends(require_key)])
    async def chat(req: ChatRequest, request: Request, service=Depends(svc)):
        real = req.model != "simulator"
        if real and req.model != os.getenv("UPSTREAM_MODEL"):
            raise HTTPException(400, "Model must match the configured UPSTREAM_MODEL")
        text = "\n".join(m.content for m in req.messages)
        if len(text) > 32000:
            raise HTTPException(422, "Combined message length exceeds 32000 characters")
        lab = LabRequest(
            mode="upstream" if real else "combined",
            prompt=text,
            input_tokens=max(1, len(text) // 4),
            output_tokens=req.max_tokens,
            cache_enabled=False,
        )
        check(lab, service)
        messages = [m.model_dump() for m in req.messages]
        events = service.run(lab, extract(request.headers), messages, req.temperature)

        async def chunks():
            identifier = ""
            async with aclosing(events):
                async for event in events:
                    if event["type"] == "start":
                        identifier = "chatcmpl-" + event["id"]
                    elif event["type"] == "token":
                        yield (
                            "data: "
                            + json.dumps(
                                {
                                    "id": identifier,
                                    "object": "chat.completion.chunk",
                                    "created": int(time.time()),
                                    "model": req.model,
                                    "choices": [
                                        {
                                            "index": 0,
                                            "delta": {"content": event["content"]},
                                            "finish_reason": None,
                                        }
                                    ],
                                }
                            )
                            + "\n\n"
                        )
                    elif event["type"] == "result":
                        r = event["record"]
                        if r["status"] != "ok":
                            yield 'data: {"error":{"message":"Inference failed; see request trace"}}\n\n'
                        else:
                            yield (
                                "data: "
                                + json.dumps(
                                    {
                                        "id": identifier,
                                        "object": "chat.completion.chunk",
                                        "created": int(time.time()),
                                        "model": req.model,
                                        "choices": [
                                            {
                                                "index": 0,
                                                "delta": {},
                                                "finish_reason": r["finish_reason"],
                                            }
                                        ],
                                    }
                                )
                                + "\n\n"
                            )
                            if (req.stream_options or {}).get("include_usage"):
                                yield (
                                    "data: "
                                    + json.dumps(
                                        {
                                            "id": identifier,
                                            "object": "chat.completion.chunk",
                                            "created": int(time.time()),
                                            "model": req.model,
                                            "choices": [],
                                            "usage": usage(r),
                                        }
                                    )
                                    + "\n\n"
                                )
                yield "data: [DONE]\n\n"

        if req.stream:
            return StreamingResponse(
                chunks(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"}
            )
        content = ""
        async with aclosing(events):
            async for event in events:
                if event["type"] == "token":
                    content += event["content"]
                elif event["type"] == "result":
                    r = event["record"]
        if r["status"] != "ok":
            raise HTTPException(502, "Inference failed; see request trace")
        return {
            "id": "chatcmpl-" + r["id"],
            "object": "chat.completion",
            "created": int(time.time()),
            "model": req.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": r["finish_reason"],
                }
            ],
            "usage": usage(r),
            "lab_source": r["source"],
        }

    return app


def usage(record):
    tokens = record["tokens"]
    return {
        "prompt_tokens": tokens.get("input"),
        "completion_tokens": tokens.get("output"),
        "total_tokens": tokens.get("total"),
        "completion_tokens_details": {"reasoning_tokens": tokens.get("reasoning")},
        "prompt_tokens_details": {"cached_tokens": tokens.get("cached_input")},
    }


app = create_app()
