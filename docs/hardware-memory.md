# Hardware & memory: from tokens to physical resources

The **Hardware & memory** view is a single-device planning calculator alongside a real CPU/RAM monitor. It does not execute a model or change the Live lab simulator. This separation is deliberate: a plausible memory estimate must never be presented as a GPU measurement.

![CPU, RAM, GPU and HBM flow](../observatory/static/hardware-flow.svg)

## Learn in this order

1. **CPU and system RAM.** In GPU serving, the CPU handles networking, tokenization, queues and scheduling. Host RAM holds application state, buffers and potentially offloaded weights/KV. In CPU-only inference, CPU cores also execute the model. High CPU pressure can delay work before the GPU begins.
2. **GPU compute and device memory.** Compute units perform model math. Device memory holds weights, KV and temporary data. HBM is one kind of GPU memory; GDDR is another. GPU L2 cache and on-chip SRAM are smaller, faster levels; the calculator does not model their reuse.
3. **Capacity versus bandwidth.** Capacity is how much fits. Bandwidth is how quickly bytes can move. Having sufficient memory does not imply fast decoding; high memory activity does not imply the memory is full.
4. **Weights versus KV.** Weights are shared across requests on a model replica. Each active sequence adds KV state. For the modeled dense/GQA geometry, KV grows with context and active sequence count.
5. **Prefill versus decode.** Prefill processes a prompt in parallel and is often compute-heavy. Decode repeatedly reads weights and cached attention state and is often memory-bandwidth-limited at small batches. Batch size, model architecture, kernels and hardware can change the bottleneck.
6. **Quantization and batching.** Lower weight precision reduces weight storage, not automatically KV storage. Lower KV precision changes a different pool. Both require compatible kernels and accuracy validation. Larger batches can amortize weight reads but need more KV memory and affect latency.
7. **Disaggregation and offload.** Prefill/decode separation adds a KV handoff over an interconnect or network. Host-memory offload crosses another link; it is not free extra HBM. The calculator does not simulate offload, tensor parallelism, continuous batching, or paging.
8. **Correlate measurements.** Inspect request latency, CPU cores, process RSS, container limits, engine KV-pool use, and GPU memory/activity together. No single utilization gauge diagnoses a bottleneck.

## Memory accounting contract

Defaults are a **hypothetical** 8-billion-parameter dense/GQA model and a hypothetical 24 GiB device, not a named model or a purchasable GPU specification. Change geometry to match a verified model config. Weight precision does not select a compatible compute precision automatically; adjust the compute assumption independently.

Let `P` be parameters, `L` layers, `Hkv` KV heads, `D` head dimension, `B` active sequences, `I` input tokens and `O` all output tokens.

```text
weights_bytes = P × weight_bits / 8
weight_overhead_bytes = weights_bytes × overhead_fraction
kv_bytes_per_token = 2 × L × Hkv × D × kv_bits / 8
kv_bytes = B × (I + O) × kv_bytes_per_token
required = weights + weight_overhead + KV + workspace + safety_reserve
headroom = capacity − required
max_sequences = max(0, floor((capacity − fixed_budget) / KV_per_sequence))
```

The factor 2 is keys plus values. Use **KV heads**, not query heads, for GQA. `O` includes reasoning if present; do not add reasoning again. This is an end-context budget, conservatively counting all configured output tokens. No prefix sharing or eviction is assumed. Weights are allocated once per replica, not multiplied by `B`.

Weight overhead represents user-selected metadata/alignment allowance, including possible quantization overhead. Workspace is a fixed placeholder for activations and runtime buffers, not a calibrated activation model. Safety reserve is deliberately unused space, not a reported allocation. Engine preallocation, allocator fragmentation and transient peaks can still cause real OOM even when this plan says “fits.”

`GiB = 2^30 bytes`; bandwidth `GB/s = 10^9 bytes/s`; parameter billions use `10^9`. Precision is storage precision; 4-bit means a nominal half-byte per weight before overhead.

## Performance model: bounds, not predictions

The calculator compares two simplified costs for an ideal synchronous decode batch at the configured end context:

```text
effective_memory_Bps = memory_GBps × 10^9 × assumed_memory_efficiency
effective_FLOPs = compute_TFLOPs × 10^12 × assumed_compute_efficiency
decode_memory_seconds = (weights + weight_overhead + end_context_KV) / effective_memory_Bps
decode_dense_compute_seconds = 2 × P × B / effective_FLOPs
decode_step_seconds = max(decode_memory_seconds, decode_dense_compute_seconds)
aggregate_output_ceiling = B / decode_step_seconds
prefill_dense_compute_seconds = 2 × P × B × I / effective_FLOPs
```

One decode step produces one token for **each** sequence, not one token for the whole batch. Its duration is an optimistic analytical floor **within these assumptions**, and the aggregate rate is a model ceiling, not a hardware guarantee. Attention FLOPs, kernel launches, dequantization, scheduling, real cache hierarchy and synchronization are omitted. Weight reuse assumes an ideal batched read; hardware can reuse or reread data differently. Do not label these numbers measured TPOT or TTFT. Latency/rate results are null when capacity is exceeded; this does not trigger a real OOM.

The separate network calculation is:

```text
prompt_KV_bytes_per_request = I × kv_bytes_per_token
handoff_seconds_per_request = setup_seconds + prompt_KV_bytes_per_request / link_Bps
```

It excludes generated output KV, assumes one request without link contention, and does not model transfer/compute overlap. It is **not** HBM bandwidth or aggregate batch transfer time. The Live lab's “Transfer MB/s” control is also a modeled handoff, in MB/s rather than this calculator's GB/s.

## Real CPU/RAM monitoring

The gateway and both worker processes sample independently every two seconds using psutil. Sampling runs off the asyncio event loop. The UI reads the gateway snapshot; Prometheus scrapes all services. CPU cores consumed = change in process user+system CPU seconds / elapsed monotonic wall seconds. A value of `1.0` means one fully busy logical core, not 1%. The first interval is null. Host available RAM is reported separately from process RSS and optional container memory.

Linux cgroup-v2 data is read only at `/sys/fs/cgroup`, the namespace root. This matches the default private Docker cgroup namespace. Native nested cgroups, v1, parent limits and cpuset constraints are not resolved. An unlimited `memory.max` or `cpu.max` yields null for the limit. Do not claim these fields identify the effective limit in every deployment. RSS is not full container consumption: page cache and other processes can account for the difference.

Missing GPU data stays unavailable. Real GPU measurements are collected externally into Prometheus, not invented from the analytical model. Process metrics include sampling overhead and all work in that service; they are not a request-level cost breakdown. A short request may start and end between resource samples. The simulator mostly waits, so low measured CPU and high modeled GPU demand are consistent.

The authenticated endpoints are `POST /api/hardware/estimate` and `GET /api/hardware/resources`. The calculator has bounded inputs and a fixed-size context sweep; it allocates no model tensors and writes no request records or estimate metrics. Comparison JSON contains complete assumptions and both saved/current configurations. It does not contain host identifiers or prompt text.

## References

- [NVIDIA: inference phases, weights, KV and batching](https://developer.nvidia.com/blog/mastering-llm-techniques-inference-optimization/)
- [NVIDIA: CPU–GPU memory sharing and offload](https://developer.nvidia.com/blog/accelerate-large-scale-llm-inference-and-kv-cache-offload-with-cpu-gpu-memory-sharing/)
- [NVIDIA DCGM: profiling metric semantics and limitations](https://docs.nvidia.com/datacenter/dcgm/latest/learn/modules/profiling.html)
- [psutil: CPU and memory measurement definitions](https://psutil.readthedocs.io/stable/)

Reviewed 2026-09-07. Use the [portfolio walkthrough](portfolio-walkthrough.md) to turn these concepts into reproducible experiments, not unsupported performance claims.
