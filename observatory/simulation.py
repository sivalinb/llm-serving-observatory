"""A timing/queue model, not a transformer or GPU benchmark.

Combined owns one service slot for the entire request. Disaggregated owns one
prefill slot, then a separate decode slot. These are DIFFERENT resource budgets.
The model intentionally does not claim continuous batching or GPU contention.
"""

import asyncio
import hashlib
import os
from collections import OrderedDict
from contextlib import asynccontextmanager
from time import perf_counter

from . import telemetry as t

KV_BYTES_PER_TOKEN = 2 * 16 * 8 * 128 * 2  # Dense attention / FP16 / no TP sharding.


class PrefixCache:
    def __init__(self, pool, capacity=128 * 1024 * 1024):
        self.pool, self.capacity = pool, capacity
        self.entries = OrderedDict()
        self.bytes = 0
        t.CACHE_CAPACITY.labels(pool).set(capacity)

    def lookup(self, req):
        if not req.cache_enabled or not req.prefix_tokens:
            return 0
        # The prefix_key identifies a synthetic prefix, never a user prompt.
        key = hashlib.sha256(f"sim-v1:{req.prefix_key}:{req.prefix_tokens}".encode()).hexdigest()
        if key in self.entries:
            self.entries.move_to_end(key)
            t.HITS.labels(self.pool, "hit").inc()
            return req.prefix_tokens
        t.HITS.labels(self.pool, "miss").inc()
        return 0

    def insert(self, req):
        if not req.cache_enabled or not req.prefix_tokens:
            return
        size = req.prefix_tokens * KV_BYTES_PER_TOKEN
        if size > self.capacity:
            return
        key = hashlib.sha256(f"sim-v1:{req.prefix_key}:{req.prefix_tokens}".encode()).hexdigest()
        if key in self.entries:
            self.entries.move_to_end(key)
            return
        while self.bytes + size > self.capacity:
            _, removed = self.entries.popitem(last=False)
            self.bytes -= removed
            t.EVICTIONS.labels(self.pool).inc()
        self.entries[key] = size
        self.bytes += size
        t.CACHE.labels(self.pool).set(self.bytes)


class Simulator:
    def __init__(self):
        self.locks = {pool: asyncio.Semaphore(1) for pool in ("combined", "prefill", "decode")}
        capacity = int(os.getenv("SIM_CACHE_BYTES", str(128 * 1024 * 1024)))
        self.caches = {pool: PrefixCache(pool, capacity) for pool in ("combined", "prefill")}

    @asynccontextmanager
    async def slot(self, pool, record):
        t.WAITING.labels(pool).inc()
        acquired = False
        try:
            with t.phase(record, pool + ".queue"):
                await self.locks[pool].acquire()
                acquired = True
        finally:
            t.WAITING.labels(pool).dec()
        try:
            t.RUNNING.labels(pool).inc()
            yield
        finally:
            if acquired:
                self.locks[pool].release()
                t.RUNNING.labels(pool).dec()

    async def prefill(self, req, record, pool="prefill"):
        cached = self.caches[pool].lookup(req)
        with t.phase(record, "prefill.compute"):
            await asyncio.sleep((req.input_tokens - cached) / req.prefill_tps + 0.002)
        self.caches[pool].insert(req)
        return {
            "cached_input": cached,
            "kv_bytes": req.input_tokens * KV_BYTES_PER_TOKEN,
            "kv_bytes_per_token": KV_BYTES_PER_TOKEN,
            "source": "simulated",
        }

    async def transfer(self, req, record, kv_bytes):
        with t.phase(record, "kv.transfer"):
            await asyncio.sleep(
                req.transfer_latency_ms / 1000 + kv_bytes / (req.transfer_mb_s * 1_000_000)
            )
            if req.fault == "transfer_failure":
                raise RuntimeError("Injected KV transfer failure")

    async def decode(self, req, record):
        # Each visible word below is ONE synthetic token, not a model tokenizer token.
        words = "Prefill builds the key value cache and decode reuses it to generate each next token while telemetry reveals latency throughput and transfer overhead across the serving pipeline".split()
        if req.reasoning_tokens:
            with t.phase(record, "decode.reasoning"):
                await asyncio.sleep(req.reasoning_tokens / req.decode_tps)
        with t.phase(record, "decode.visible"):
            for index in range(req.output_tokens - req.reasoning_tokens):
                await asyncio.sleep(1 / req.decode_tps)
                yield words[index % len(words)] + " "

    async def stream(self, req, record):
        if req.mode == "combined":
            async with self.slot("combined", record):
                record["kv"] = await self.prefill(req, record, "combined")
                async for word in self.decode(req, record):
                    yield word
        else:
            async with self.slot("prefill", record):
                record["kv"] = await self.prefill(req, record)
            await self.transfer(req, record, record["kv"]["kv_bytes"])
            record["kv_transfer_bytes"] = record["kv"]["kv_bytes"]
            async with self.slot("decode", record):
                async for word in self.decode(req, record):
                    yield word


def worker_record():
    return {
        "source": "simulated",
        "mode": "disaggregated",
        "phases": [],
        "clock": "worker",
        "_start": perf_counter(),
    }
