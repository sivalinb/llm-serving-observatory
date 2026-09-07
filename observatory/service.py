import asyncio
import json
import logging
import os
import platform
import uuid
from contextlib import aclosing
from datetime import datetime, timezone
from time import perf_counter

import httpx
from opentelemetry import trace
from opentelemetry.propagate import inject

from . import telemetry as t
from .simulation import KV_BYTES_PER_TOKEN, Simulator
from .upstream import sse_json, stream_upstream

logger = logging.getLogger("observatory.requests")


def percentile(values, p):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    pos = (len(values) - 1) * p
    lo, hi = int(pos), min(int(pos) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def summarize(records, wall_seconds):
    successes = [r for r in records if r["status"] == "ok"]
    ttft = [r.get("ttft_ms") for r in successes]
    tpot = [r.get("tpot_ms") for r in successes]
    known_output = [r["tokens"].get("output") for r in successes]
    all_known = bool(successes) and all(v is not None for v in known_output)
    return {
        "requests": len(records),
        "successes": len(successes),
        "errors": len(records) - len(successes),
        "wall_seconds": wall_seconds,
        "ttft_p50_ms": percentile(ttft, 0.5),
        "ttft_p95_ms": percentile(ttft, 0.95),
        "ttft_p99_ms": percentile(ttft, 0.99),
        "tpot_p95_ms": percentile(tpot, 0.95),
        "e2e_p95_ms": percentile([r["duration_ms"] for r in records], 0.95),
        "requests_per_second": len(successes) / max(wall_seconds, 1e-9),
        "output_tokens_per_second": sum(known_output) / max(wall_seconds, 1e-9)
        if all_known
        else None,
        "goodput_per_second": sum(r.get("slo_met") is True for r in records)
        / max(wall_seconds, 1e-9),
        "slo_evaluable": sum(r.get("slo_met") is not None for r in successes),
    }


class Service:
    def __init__(self, store, client=None):
        self.store, self.sim = store, Simulator()
        self.client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=5), limits=httpx.Limits(max_connections=32)
        )
        self.inflight = 0
        self.benchmark_busy = False

    async def remote_sim(self, req, record):
        headers = {"X-Worker-Token": os.getenv("WORKER_TOKEN", "local-development-only")}
        with t.phase(record, "prefill.rpc"):
            inject(headers)
            response = await self.client.post(
                os.environ["PREFILL_URL"] + "/prefill", json=req.model_dump(), headers=headers
            )
            response.raise_for_status()
            payload = response.json()
        record["kv"] = payload["kv"]
        # Worker-local offsets belong in their own spans; no cross-host clock subtraction.
        record["worker_phases"] = {"prefill": payload["phases"]}
        await self.sim.transfer(req, record, payload["kv"]["kv_bytes"])
        record["kv_transfer_bytes"] = payload["kv"]["kv_bytes"]
        with t.phase(record, "decode.rpc"):
            inject(headers)
            async with self.client.stream(
                "POST", os.environ["DECODE_URL"] + "/decode", json=req.model_dump(), headers=headers
            ) as response:
                response.raise_for_status()
                finished = False
                async for event in sse_json(response):
                    if event.get("error"):
                        raise RuntimeError("Remote decode failed")
                    if event.get("content"):
                        yield event["content"]
                    if "phases" in event:
                        record["worker_phases"]["decode"] = event["phases"]
                        finished = True
                if not finished:
                    raise RuntimeError("Remote worker stream ended early")

    async def run(self, req, context=None, messages=None, temperature=0):
        mode = req.mode
        source = "upstream" if mode == "upstream" else "simulated"
        record = {
            "id": uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": mode,
            "source": source,
            "model": os.getenv("UPSTREAM_MODEL", "") if source == "upstream" else "synthetic-v1",
            "token_provenance": "unavailable" if source == "upstream" else "synthetic",
            "phases": [],
            "tokens": {},
            "kv_transfer_bytes": 0,
            "status": "running",
            "ttft_ms": None,
            "tpot_ms": None,
            "itl_ms": [],
            "chunk_gaps_ms": [],
            "finish_reason": None,
            "_start": perf_counter(),
        }
        first = last = None
        visible_chunks = 0
        self.inflight += 1
        t.ACTIVE.inc()
        with t.TRACER.start_as_current_span(
            "llm.request",
            context=context,
            attributes={"lab.mode": mode, "lab.source": source, "gen_ai.operation.name": "chat"},
        ) as span:
            record["trace_id"] = format(span.get_span_context().trace_id, "032x")
            try:
                yield {
                    "type": "start",
                    "id": record["id"],
                    "trace_id": record["trace_id"],
                    "source": source,
                }
                async with asyncio.timeout(60):
                    if source == "upstream":
                        iterator = stream_upstream(req, record, self.client, messages, temperature)
                    elif (
                        mode == "disaggregated"
                        and os.getenv("PREFILL_URL")
                        and os.getenv("DECODE_URL")
                    ):
                        iterator = self.remote_sim(req, record)
                    else:
                        iterator = self.sim.stream(req, record)
                    async with aclosing(iterator):
                        async for content in iterator:
                            now = perf_counter()
                            if first is None:
                                first = now
                                record["ttft_ms"] = (now - record["_start"]) * 1000
                                span.add_event("first_visible_content")
                            if last is not None:
                                gap = (now - last) * 1000
                                metric = t.ITL if source == "simulated" else t.CHUNK_GAP
                                metric.labels(mode, source).observe(gap / 1000)
                                key = "itl_ms" if source == "simulated" else "chunk_gaps_ms"
                                record[key].append(gap)
                            last = now
                            visible_chunks += 1
                            yield {
                                "type": "token",
                                "content": content,
                                "index": visible_chunks,
                                "ttft_ms": record["ttft_ms"],
                                "offset_ms": (now - record["_start"]) * 1000,
                            }
                if first is None:
                    raise RuntimeError("No visible content returned")
                record["status"] = "ok"
                if source == "simulated":
                    record["tokens"] = {
                        "input": req.input_tokens,
                        "output": req.output_tokens,
                        "cached_input": record.get("kv", {}).get("cached_input", 0),
                        "reasoning": req.reasoning_tokens,
                        "visible_output": req.output_tokens - req.reasoning_tokens,
                        "total": req.input_tokens + req.output_tokens,
                    }
                    record["tokens"]["uncached_input"] = (
                        req.input_tokens - record["tokens"]["cached_input"]
                    )
                    record["finish_reason"] = "length"
                visible = record["tokens"].get("visible_output")
                if visible is not None and visible > 1:
                    record["tpot_ms"] = (last - first) * 1000 / (visible - 1)
                record["slo_met"] = (
                    (record["ttft_ms"] <= req.ttft_slo_ms and record["tpot_ms"] <= req.tpot_slo_ms)
                    if record["tpot_ms"] is not None
                    else None
                )
            except (asyncio.CancelledError, GeneratorExit):
                record["status"] = "cancelled"
                raise
            except Exception as exc:
                record["status"] = "error"
                record["error_type"] = type(exc).__name__
                # Class only: arbitrary provider error text could contain user content.
                span.set_status(trace.Status(trace.StatusCode.ERROR, record["error_type"]))
            finally:
                record["duration_ms"] = (perf_counter() - record["_start"]) * 1000
                transfer_ms = sum(
                    p["duration_ms"] for p in record["phases"] if p["name"] == "kv.transfer"
                )
                record["kv_effective_mb_s"] = (
                    record["kv_transfer_bytes"] / (transfer_ms * 1000)
                    if record["kv_transfer_bytes"] and transfer_ms
                    else None
                )
                record["handoff_ttft_ratio"] = (
                    transfer_ms / record["ttft_ms"] if transfer_ms and record["ttft_ms"] else None
                )
                record["visible_chunks"] = visible_chunks
                record["slo_targets"] = {"ttft_ms": req.ttft_slo_ms, "tpot_ms": req.tpot_slo_ms}
                if source == "upstream":
                    record["measurement_note"] = (
                        "Gateway first visible content and chunk gaps. Engine phases/KV bytes unavailable via generic API."
                    )
                else:
                    record["measurement_note"] = (
                        "Measured wall times of synthetic work. KV bytes are modeled; no model weights or tensors."
                    )
                for key, attr in (
                    ("input", "gen_ai.usage.input_tokens"),
                    ("output", "gen_ai.usage.output_tokens"),
                    ("reasoning", "gen_ai.usage.reasoning.output_tokens"),
                    ("cached_input", "gen_ai.usage.cache_read.input_tokens"),
                ):
                    if record["tokens"].get(key) is not None:
                        span.set_attribute(attr, record["tokens"][key])
                self.inflight -= 1
                t.ACTIVE.dec()
                t.observe_record(record)
                self.store.save("request", record)
                logger.info(
                    json.dumps(
                        {
                            "event": "request_finished",
                            "request_id": record["id"],
                            "trace_id": record["trace_id"],
                            "status": record["status"],
                            "mode": mode,
                            "duration_ms": record["duration_ms"],
                        }
                    )
                )
            yield {
                "type": "result",
                "record": {k: v for k, v in record.items() if not k.startswith("_")},
            }

    async def collect(self, req):
        record = None
        async with aclosing(self.run(req)) as events:
            async for event in events:
                if event["type"] == "result":
                    record = event["record"]
        return record

    async def benchmark(self, config):
        experiment = {
            "id": uuid.uuid4().hex,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "config": config.model_dump(),
            "results": [],
            "status": "running",
            "environment": {
                "python": platform.python_version(),
                "architecture": platform.machine(),
            },
            "method": "closed-loop; warmups excluded; linear interpolated percentiles; mode order fixed",
            "resource_note": "Combined: 1 slot. Disaggregated: 1 prefill + 1 decode slot. Not equal-cost resources.",
        }
        # Do not retain prompt text in an experiment, either.
        experiment["config"]["request"].pop("prompt", None)
        experiment["config"]["request"].pop("prefix_key", None)
        modes = (
            ["combined", "disaggregated"]
            if config.compare and config.request.mode != "upstream"
            else [config.request.mode]
        )
        try:
            for mode in modes:
                # Unique namespace prevents previous experiments from warming this run.
                req = config.request.model_copy(
                    update={"mode": mode, "prefix_key": experiment["id"]}
                )
                for _ in range(config.warmup):
                    await self.collect(req)
                queue = asyncio.Queue()
                next_index = 0

                async def worker():
                    nonlocal next_index
                    while next_index < config.requests:
                        index = next_index
                        next_index += 1
                        record = await self.collect(req)
                        await queue.put((index, record))

                begin = perf_counter()
                records = []
                async with asyncio.TaskGroup() as group:
                    for _ in range(min(config.concurrency, config.requests)):
                        group.create_task(worker())
                    for completed in range(config.requests):
                        _, record = await queue.get()
                        records.append(record)
                        yield {
                            "type": "progress",
                            "mode": mode,
                            "completed": completed + 1,
                            "total": config.requests,
                        }
                wall = perf_counter() - begin
                result = {"mode": mode, "summary": summarize(records, wall), "records": records}
                experiment["results"].append(result)
                yield {"type": "comparison", **result}
            experiment["status"] = "ok"
        except (asyncio.CancelledError, GeneratorExit):
            experiment["status"] = "cancelled"
            raise
        except Exception as exc:
            experiment["status"] = "error"
            experiment["error_type"] = type(exc).__name__
        finally:
            self.benchmark_busy = False
            self.store.save("benchmark", experiment)
        yield {"type": "benchmark", "experiment": experiment}

    def config(self):
        return {
            "upstream_available": bool(os.getenv("UPSTREAM_URL") and os.getenv("UPSTREAM_MODEL")),
            "upstream_kind": os.getenv("UPSTREAM_KIND", "llama.cpp"),
            "upstream_model": os.getenv("UPSTREAM_MODEL", ""),
            "distributed_workers": bool(os.getenv("PREFILL_URL") and os.getenv("DECODE_URL")),
            "kv_bytes_per_token": KV_BYTES_PER_TOKEN,
            "max_inflight": 16,
            "auth_required": bool(os.getenv("LAB_API_KEY")),
        }
