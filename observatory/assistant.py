"""Invite-only, single-CPU-request documentation service. The lab remains separate."""

import asyncio
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from opentelemetry.propagate import extract, inject
from prometheus_client import Counter, Gauge, Histogram
from pydantic import BaseModel, Field

from .assistant_store import AssistantStore, Rejected
from .retrieval import CORPUS_VERSION, citation_check, prompt, search
from .telemetry import BUCKETS, TRACER
from .upstream import normalize_usage

REQUESTS = Counter("assistant_requests_total", "Admitted requests by terminal status", ["status"])
DENIED = Counter("assistant_admission_denied_total", "Admission denials", ["reason"])
ACTIVE = Gauge("assistant_active_requests", "Active real assistant requests; maximum one")
LATENCY = Histogram("assistant_request_seconds", "Admission to stream completion", buckets=BUCKETS)
TTFT = Histogram(
    "assistant_ttft_seconds", "Question processing to first visible model content", buckets=BUCKETS
)
GAPS = Histogram(
    "assistant_chunk_gap_seconds", "Content chunk gaps, NOT per-token latency", buckets=BUCKETS
)
TOKENS = Counter("assistant_tokens_total", "Provider-reported counts; subsets overlap", ["kind"])
CITATIONS = Counter(
    "assistant_citations_total", "Syntactic citation check, not factual accuracy", ["result"]
)


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    url: str = "http://model:8080/v1"
    model: str = "servingops-cpu"
    deadline: float = 90
    monthly_tokens: int = 1000000
    context: int = 4096
    max_output_tokens: int = 256

    def __post_init__(self):
        parsed = urlsplit(self.url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Assistant URL must be an operator-configured HTTP(S) base URL")
        if not (
            1 <= self.deadline <= 300
            and self.monthly_tokens > 0
            and self.context >= 1024
            and 16 <= self.max_output_tokens <= 256
        ):
            raise ValueError("Invalid assistant capacity settings")

    @classmethod
    def from_env(cls):
        # This profile never configures a paid managed provider or accepts a caller-selected URL.
        return cls(
            enabled=os.getenv("ASSISTANT_ENABLE_CPU", "false").lower() == "true",
            url=os.getenv("ASSISTANT_CPU_URL", "http://model:8080/v1"),
            model=os.getenv("ASSISTANT_CPU_MODEL", "servingops-cpu"),
            deadline=float(os.getenv("ASSISTANT_DEADLINE_SECONDS", "90")),
            monthly_tokens=int(os.getenv("ASSISTANT_MONTHLY_TOKENS", "1000000")),
            context=int(os.getenv("ASSISTANT_CONTEXT_TOKENS", "4096")),
            max_output_tokens=int(os.getenv("ASSISTANT_MAX_OUTPUT_TOKENS", "256")),
        )


class Question(BaseModel):
    question: str = Field(min_length=3, max_length=800)
    max_tokens: int | None = Field(default=None, ge=16, le=256)


class Redemption(BaseModel):
    invite: str = Field(min_length=20, max_length=100)
    name: str = Field(min_length=1, max_length=40)


async def bounded_events(response):
    """Bound untrusted upstream framing as well as total response bytes."""
    buffer, total = b"", 0
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        buffer += chunk
        if total > 2 * 1024 * 1024 or len(buffer) > 65536:
            raise ValueError("Upstream stream size limit")
        while b"\n\n" in buffer or b"\r\n\r\n" in buffer:
            # Normalize CRLF only after bytes have arrived, including split CR/LF boundaries.
            crlf, lf = buffer.find(b"\r\n\r\n"), buffer.find(b"\n\n")
            width, end = (4, crlf) if crlf >= 0 and (lf < 0 or crlf < lf) else (2, lf)
            block, buffer = buffer[:end], buffer[end + width :]
            data = b"\n".join(
                line[5:].lstrip() for line in block.splitlines() if line.startswith(b"data:")
            )
            if data == b"[DONE]":
                return
            if data:
                event = json.loads(data)
                if not isinstance(event, dict):
                    raise ValueError("Expected an event object")
                yield event
    if buffer.strip():
        raise ValueError("Truncated SSE event")


class GuardedStream(StreamingResponse):
    """Release an admission even if ASGI disconnects before iterating the body."""

    def __init__(self, events, cleanup):
        self.cleanup = cleanup
        super().__init__(
            events,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            await self.body_iterator.aclose()
            self.cleanup()


class Assistant:
    def __init__(self, store, settings=None, client=None):
        self.store = store
        self.settings = settings or Settings.from_env()
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.settings.deadline, connect=5),
            limits=httpx.Limits(max_connections=2),
            trust_env=False,
        )

    def status(self):
        return {
            "service": "ServingOps Cloud",
            "release": "0.3.0",
            "region_target": "us-phoenix-1",
            "search": "ready",
            "inference": "configured" if self.settings.enabled else "disabled",
            "backend": "self-hosted CPU",
            "max_concurrent_answers": 1,
            "max_output_tokens": self.settings.max_output_tokens,
            "default_output_tokens": min(192, self.settings.max_output_tokens),
            "context_tokens": self.settings.context,
            "deadline_seconds": self.settings.deadline,
            "corpus_version": CORPUS_VERSION,
            "availability": "single-node beta; no HA guarantee",
            "hardware": "CPU and host RAM; no GPU/HBM in this profile",
        }

    def prepare(self, user, req, idem, context):
        started = time.perf_counter()
        if not self.settings.enabled:
            raise Rejected("AI answers disabled; document search is available", 503)
        output_tokens = (
            min(192, self.settings.max_output_tokens) if req.max_tokens is None else req.max_tokens
        )
        if output_tokens > self.settings.max_output_tokens:
            DENIED.labels("output_tokens").inc()
            raise Rejected(
                f"This profile allows at most {self.settings.max_output_tokens} output tokens", 422
            )
        sources = search(req.question)
        retrieval_ms = (time.perf_counter() - started) * 1000
        if not sources:
            raise Rejected("No relevant approved sources; try a serving-related question", 422)
        messages = prompt(req.question, sources)
        # UTF-8 bytes + framing allowance are deliberately conservative, not tokenizer measurement.
        reserved = len(json.dumps(messages, ensure_ascii=False).encode()) + 256 + output_tokens
        if reserved > self.settings.context:
            raise Rejected("Question and references exceed the conservative context budget", 422)
        try:
            rid = self.store.reserve(
                user, idem, reserved, self.settings.monthly_tokens, self.settings.deadline
            )
        except Rejected as exc:
            DENIED.labels(exc.reason).inc()
            raise
        record = {
            "id": rid,
            "status": "cancelled",
            "backend": "selfhosted_cpu",
            "created": time.time(),
            "corpus_version": CORPUS_VERSION,
            "reserved_tokens_estimate": reserved,
            "max_output_tokens": output_tokens,
            "tokens": normalize_usage({}),
            "ttft_ms": None,
            "duration_ms": None,
            "chunk_count": 0,
            "retrieval_ms": retrieval_ms,
            "citations": "not_checked",
            "source_ids": [s["document_id"] for s in sources],
        }
        finalized = False
        ACTIVE.inc()

        def finish():
            nonlocal finalized
            if finalized:
                return
            finalized = True
            record["duration_ms"] = (time.perf_counter() - started) * 1000
            self.store.finish(rid, record)
            ACTIVE.dec()
            REQUESTS.labels(record["status"]).inc()
            LATENCY.observe(record["duration_ms"] / 1000)
            for kind, value in record["tokens"].items():
                if value is not None:
                    TOKENS.labels(kind).inc(value)

        async def events():
            answer, saw_finish, last = "", False, None
            with TRACER.start_as_current_span("assistant.request", context=context) as span:
                record["trace_id"] = f"{span.get_span_context().trace_id:032x}"
                span.set_attribute("assistant.backend", "selfhosted_cpu")
                span.set_attribute("assistant.corpus", CORPUS_VERSION)
                span.set_attribute("assistant.retrieval_ms", retrieval_ms)
                try:
                    yield encode({"type": "sources", "request_id": rid, "sources": sources})
                    headers = {}
                    inject(headers)
                    body = {
                        "model": self.settings.model,
                        "messages": messages,
                        "max_tokens": output_tokens,
                        "temperature": 0,
                        "stream": True,
                        "stream_options": {"include_usage": True},
                    }
                    async with asyncio.timeout(self.settings.deadline):
                        with TRACER.start_as_current_span("assistant.model_stream"):
                            async with self.client.stream(
                                "POST",
                                self.settings.url.rstrip("/") + "/chat/completions",
                                json=body,
                                headers=headers,
                            ) as response:
                                response.raise_for_status()
                                async for event in bounded_events(response):
                                    if "error" in event:
                                        raise ValueError("Upstream error")
                                    if event.get("usage"):
                                        record["tokens"] = normalize_usage(event["usage"])
                                    for choice in event.get("choices", []):
                                        if choice.get("finish_reason"):
                                            saw_finish = True
                                            reason = choice["finish_reason"]
                                            record["finish_reason"] = (
                                                reason
                                                if reason in {"stop", "length", "content_filter"}
                                                else "other"
                                            )
                                        content = choice.get("delta", {}).get("content")
                                        if isinstance(content, str) and content:
                                            now = time.perf_counter()
                                            if last is None:
                                                record["ttft_ms"] = (now - started) * 1000
                                                TTFT.observe(record["ttft_ms"] / 1000)
                                            else:
                                                GAPS.observe(now - last)
                                            last = now
                                            answer += content
                                            if len(answer.encode()) > 32768:
                                                raise ValueError("Output too large")
                                            record["chunk_count"] += 1
                                            yield encode({"type": "delta", "content": content})
                    if not saw_finish or not answer.strip():
                        raise ValueError("Incomplete or empty model response")
                    record["status"] = "ok"
                    record["citations"] = citation_check(answer, sources)
                    CITATIONS.labels(record["citations"]).inc()
                except (asyncio.CancelledError, GeneratorExit):
                    record["status"] = "cancelled"
                    raise
                except Exception as exc:
                    record["status"] = "timeout" if isinstance(exc, TimeoutError) else "error"
                    # Do not record exception text/provider bodies (may contain private content).
                    span.set_attribute("error.type", type(exc).__name__)
                    yield encode(
                        {
                            "type": "error",
                            "message": "Model request failed or timed out. "
                            "Use document search, or retry later with a new request ID.",
                        }
                    )
                finally:
                    finish()
                yield encode({"type": "result", "record": record})

        return GuardedStream(events(), finish)


def encode(event):
    return "data: " + json.dumps(event, allow_nan=False) + "\n\n"


router = APIRouter()


def assistant(request: Request):
    return request.app.state.assistant


def translate(exc):
    return HTTPException(
        exc.status, exc.reason, headers={"Retry-After": "10"} if exc.status == 429 else None
    )


def identity(authorization: str = Header(default="", max_length=200), svc=Depends(assistant)):
    try:
        if not authorization.startswith("Bearer "):
            raise Rejected("Bearer personal access key required", 401)
        return svc.store.authenticate(authorization.removeprefix("Bearer "))
    except Rejected as exc:
        raise translate(exc) from None


@router.get("/assistant")
def page():
    return FileResponse(Path(__file__).parent / "static" / "assistant.html")


@router.get("/api/service/status")
def status(svc=Depends(assistant)):
    return svc.status()


@router.post("/api/service/redeem")
def redeem(req: Redemption, svc=Depends(assistant)):
    try:
        return svc.store.redeem(req.invite, req.name.strip())
    except Rejected as exc:
        raise translate(exc) from None


@router.get("/api/service/me")
def me(user=Depends(identity), svc=Depends(assistant)):
    return {"user": user, "usage": svc.store.usage(user["id"]),
            "is_operator": svc.store.is_operator(user["id"])}


@router.post("/api/service/search")
def documents(req: Question, user=Depends(identity)):
    return {"sources": search(req.question), "corpus_version": CORPUS_VERSION}


@router.post("/api/service/answer")
async def answer(
    req: Question,
    request: Request,
    idempotency_key: str = Header(pattern=r"^[A-Za-z0-9_-]{16,80}$"),
    user=Depends(identity),
    svc=Depends(assistant),
):
    try:
        return svc.prepare(user, req, idempotency_key, extract(request.headers))
    except Rejected as exc:
        code = "disabled" if exc.status == 503 else exc.reason
        if code not in {"capacity", "daily_requests", "daily_tokens", "monthly_tokens",
                        "rate_limit", "duplicate_request", "disabled"}:
            code = "validation"
        svc.store.event("request_rejected", uid=user["id"], code=code)
        raise translate(exc) from None


@router.get("/api/service/history")
def records(user=Depends(identity), svc=Depends(assistant)):
    return {"records": svc.store.records(user["id"])}


@router.delete("/api/service/history")
def delete_records(user=Depends(identity), svc=Depends(assistant)):
    svc.store.delete_history(user["id"])
    return {"deleted": "request metadata", "retained": "quota/idempotency ledger up to 90 days"}


@router.post("/api/service/rotate-key")
def rotate(user=Depends(identity), svc=Depends(assistant)):
    return {"api_key": svc.store.rotate(user["id"])}


@router.post("/api/service/revoke-key")
def revoke(user=Depends(identity), svc=Depends(assistant)):
    svc.store.revoke(user["id"])
    return {"revoked": True}


def create_assistant(path):
    return Assistant(AssistantStore(path))
