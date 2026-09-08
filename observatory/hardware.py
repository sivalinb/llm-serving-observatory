"""Deterministic, single-device dense/GQA planning model. Never GPU telemetry."""

import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GIB = 1024**3


class HardwareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    parameters_b: float = Field(8, ge=0.1, le=1000)
    layers: int = Field(32, ge=1, le=256)
    kv_heads: int = Field(8, ge=1, le=256)
    head_dim: int = Field(128, ge=16, le=512)
    weight_bits: Literal[4, 8, 16, 32] = 16
    kv_bits: Literal[8, 16, 32] = 16
    input_tokens: int = Field(4096, ge=1, le=1048576)
    output_tokens: int = Field(512, ge=1, le=131072)
    concurrency: int = Field(4, ge=1, le=1024)
    memory_gib: float = Field(24, ge=1, le=2048)
    memory_gb_s: float = Field(1000, ge=1, le=20000)
    compute_tflops: float = Field(100, ge=0.1, le=20000)
    memory_efficiency: float = Field(0.6, ge=0.01, le=1)
    compute_efficiency: float = Field(0.4, ge=0.01, le=1)
    weight_overhead_pct: float = Field(10, ge=0, le=100)
    workspace_gib: float = Field(2, ge=0, le=256)
    reserve_pct: float = Field(10, ge=0, le=50)
    link_gb_s: float = Field(25, ge=0.001, le=1000)
    link_latency_ms: float = Field(3, ge=0, le=1000)


def estimate(req: HardwareRequest):
    params = req.parameters_b * 1e9
    weights = params * req.weight_bits / 8
    overhead = weights * req.weight_overhead_pct / 100
    kv_per_token = 2 * req.layers * req.kv_heads * req.head_dim * req.kv_bits / 8
    context = req.input_tokens + req.output_tokens
    kv_per_request = context * kv_per_token
    kv = kv_per_request * req.concurrency
    capacity = req.memory_gib * GIB
    workspace = req.workspace_gib * GIB
    reserve = capacity * req.reserve_pct / 100
    fixed = weights + overhead + workspace + reserve
    required = fixed + kv
    fits = required <= capacity
    max_concurrency = max(0, math.floor((capacity - fixed) / kv_per_request))
    bandwidth = req.memory_gb_s * 1e9 * req.memory_efficiency
    compute = req.compute_tflops * 1e12 * req.compute_efficiency
    # One dense weight read per batch step, full end-context KV read, ideal reuse.
    # Attention FLOPs, dequantization, kernels, scheduling and communication omitted.
    decode_memory_ms = (weights + overhead + kv) / bandwidth * 1000
    decode_compute_ms = 2 * params * req.concurrency / compute * 1000
    decode_floor = max(decode_memory_ms, decode_compute_ms)
    prefill_compute_ms = 2 * params * req.input_tokens * req.concurrency / compute * 1000
    prompt_kv = req.input_tokens * kv_per_token
    transfer_ms = req.link_latency_ms + prompt_kv / (req.link_gb_s * 1e9) * 1000
    memory = {
        "weights_bytes": weights,
        "weight_overhead_bytes": overhead,
        "kv_bytes": kv,
        "workspace_bytes": workspace,
        "reserve_bytes": reserve,
        "capacity_bytes": capacity,
        "required_bytes": required,
        "headroom_bytes": capacity - required,
        "kv_bytes_per_token": kv_per_token,
        "kv_bytes_per_request": kv_per_request,
        "max_concurrency": max_concurrency,
        "fits": fits,
    }
    return {
        "schema_version": "1.0",
        "source": "analytical_estimate",
        "model": "single-device-dense-gqa-v1",
        "inputs": req.model_dump(),
        "memory": memory,
        "performance": {
            "decode_memory_floor_ms": decode_memory_ms if fits else None,
            "decode_compute_floor_ms": decode_compute_ms if fits else None,
            "decode_step_floor_ms": decode_floor if fits else None,
            "aggregate_output_ceiling_tps": req.concurrency * 1000 / decode_floor if fits else None,
            "prefill_dense_compute_floor_ms": prefill_compute_ms if fits else None,
            "decode_limiting_term": (
                "capacity"
                if not fits
                else "memory_bandwidth"
                if decode_memory_ms >= decode_compute_ms
                else "compute"
            ),
            "prompt_kv_transfer_bytes_per_request": prompt_kv,
            "prompt_kv_transfer_floor_ms_per_request": transfer_ms,
            "effective_memory_gb_s": bandwidth / 1e9,
        },
        "assumptions": [
            "One complete dense model on one device; not tensor parallel or MoE.",
            "All requests have equal prompt/output lengths and decode in one ideal batch.",
            "End-context KV includes input plus ALL output, including reasoning; no prefix sharing.",
            "Workspace, weight overhead and reserve are user assumptions, not measured allocations.",
            "Performance is an optimistic analytical bound under selected efficiencies, not TTFT/TPOT evidence.",
            "No attention FLOPs, dequantization cost, cache hierarchy, paging, offload, or scheduling modeled.",
            "KV transfer is one prompt per request over an independent link; no contention/overlap/compression.",
            "Changing precision does not guarantee kernel support, accuracy or speed on real hardware.",
            "GiB = 2^30 bytes; bandwidth GB/s = 10^9 bytes/s. Profiles are hypothetical, not GPU specifications.",
        ],
    }


def estimate_with_sweep(req: HardwareRequest):
    result = estimate(req)
    # Fixed bounded work; no model execution, allocations or exporter side effects.
    contexts = sorted({512, 2048, 8192, 32768, 131072, req.input_tokens})
    result["context_sweep"] = [
        {
            "input_tokens": tokens,
            "required_gib": estimate(req.model_copy(update={"input_tokens": tokens}))["memory"][
                "required_bytes"
            ]
            / GIB,
        }
        for tokens in contexts
    ]
    return result
