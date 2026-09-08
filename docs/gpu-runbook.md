# Real GPU prefill/decode experiment

For real device-memory/SM/DRAM counters, follow [Hardware telemetry](hardware-telemetry.md). The Hardware UI's capacity calculator is an independent analytical model; do not cite its numbers as results from this runbook.

This is the hardware extension of the CPU laboratory. The repository contains a real streaming adapter and a supervised launcher for official vLLM NIXL components, but no hardware results are claimed until this runbook is executed on compatible GPUs.

## Prerequisites

Use a two-GPU Linux host with compatible CUDA/NVIDIA drivers and enough memory for the same small model on each GPU. A two-A10 OCI VM is an example when available in your region and tenancy. Start with a small supported model such as Qwen/Qwen3-0.6B to focus on transport and measurement rather than fitting weights. Review its license and context requirements.

Use a matching vLLM install and source checkout. The launcher expects the `tests/v1/kv_connector/nixl_integration/toy_proxy_server.py` file from that checkout. Install the NIXL version required by the selected vLLM release and follow that release's transport prerequisites. Do not mix an old engine with an unpinned `main` proxy. The [v0.24.0 NIXL guide](https://docs.vllm.ai/en/v0.24.0/features/nixl_connector_usage/) is a concrete versioned starting point; current upstream may change roles, flags or paths.

Record the version, source SHA, image digest if containerized, NIXL/UCX versions, model revision, tokenizer revision, precision, GPU model/count and network topology in your benchmark notes. The launcher's required SHA pins the proxy checkout. You remain responsible for using the matching installed vLLM release.

## Launch

Run in the prepared vLLM/NIXL environment:

```bash
python scripts/gpu_lab.py \
  --vllm-source /path/to/pinned-vllm-checkout \
  --source-sha EXACT_40_CHARACTER_CHECKOUT_SHA \
  --model Qwen/Qwen3-0.6B \
  --duration 1800
```

The supervisor starts prefill on GPU 0 / port 8100, decode on GPU 1 / port 8200, and the official routing proxy on 8192. It gives NIXL side channels distinct ports, uses producer/consumer roles, and configures KV load failure to fail rather than silently recompute. Engine HTTP ports bind to loopback; the official toy proxy may bind more widely, so keep the host inside a restricted network. This example uses same-host communication, not cross-node RDMA benchmarking.

Wait for the engine readiness endpoints before sending traffic. If a child exits, the supervisor terminates the other child process groups. Ctrl-C and the finite duration also stop its children. Startup time counts toward that duration. **The supervisor does not stop or delete the OCI VM, and billing continues.**

Start the observatory in a separate environment/process on the GPU host:

```bash
UPSTREAM_URL=http://127.0.0.1:8192/v1 \
UPSTREAM_MODEL=Qwen/Qwen3-0.6B \
UPSTREAM_KIND=vllm-disaggregated \
uvicorn observatory.app:app --host 127.0.0.1 --port 8000
```

Run `scripts/benchmark.py --mode upstream` with actual short and long prompts. `--input-tokens` configures only simulation, so real token lengths must be confirmed from provider usage. The UI can also load a text prompt. The generic adapter requests streaming usage; if the selected proxy does not return it, counts remain unavailable instead of being inferred from chunks.

## Validate actual KV transfer

Scrape both vLLM engines with Prometheus using reachable private endpoints. Check the metrics exposed by your chosen release. Versioned NIXL docs list:

- `vllm:nixl_xfer_time_seconds` and `vllm:nixl_post_time_seconds`
- `vllm:nixl_bytes_transferred`
- `vllm:nixl_num_failed_transfers`
- `vllm:nixl_num_failed_notifications`
- `vllm:nixl_num_kv_expired_reqs`

Run the selected release's official NIXL accuracy/integration test before performance comparison. Verify nonzero transfer observations, completion correctness, and no KV load fallback. A healthy proxy alone does not prove tensors moved. Distinguish actual NIXL measurements from `lab_kv_transfer_bytes_total`, which is simulation-only. Add NVIDIA DCGM if GPU utilization/memory telemetry is required.

## Compare fairly

1. Establish a combined vLLM baseline using the same model, precision, total GPU count, context limit and workload. For a small model, two combined replicas with a simple load distributor can provide an equal-total-GPU baseline; record the routing strategy.
2. Pin concurrency and real input/output distributions. Include short prompt, long prompt, long generation and shared-prefix workloads.
3. Run warmups separately. Alternate experiment order across multiple trials to reduce drift. Report successful requests, errors and actual generated lengths.
4. Compare p50/p95/p99 TTFT, visible TPOT where meaningful, engine ITL, generated tokens/sec, SLO goodput, transfer bytes/sec and GPU memory.
5. State the limits: a small model on same-host GPUs does not establish multi-node scaling; small samples do not establish reliable p99.
6. Export results to the CPU lab/Object Storage, then shut down the paid environment and verify remaining resources in OCI.

Prefix caching, chunked prefill, PagedAttention, speculative decoding, tensor/expert parallelism and cache-aware routing are follow-on engine experiments. Add one change at a time and keep the baseline configuration in the report.
