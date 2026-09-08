# Observability contract

## Separate the three surfaces

- **Homepage:** explanatory animation only. It emits no inference measurements or telemetry requests.
- **Assistant:** real CPU inference uses the `assistant_*` metric namespace and personal metadata history.
- **Lab:** experiments use `lab_*`; serving-series labels distinguish simulated work from configured real upstreams. Hardware planning is analytical, while process/cgroup telemetry is measured separately.

Never combine simulated and real samples to make a performance claim. Metrics do not contain request IDs, prompts, user IDs or arbitrary model names. Trace records hold request and trace IDs for drilldown.

## Real assistant signals

| Signal | Metric / record | Definition |
|---|---|---|
| First visible content | `assistant_ttft_seconds` / `ttft_ms` | Retrieval start, after authentication, to first visible model content; excludes browser/network time |
| Whole request | `assistant_request_seconds` / `duration_ms` | Same start to terminal completion, failure or cancellation, before metadata persistence |
| Stream chunk gaps | `assistant_chunk_gap_seconds` | Arrival intervals, not model-token ITL |
| Terminal outcomes | `assistant_requests_total{status}` | Admitted requests ending as ok, error, timeout or cancelled |
| Admission denials | `assistant_admission_denied_total{reason}` | Bounded quota, rate, duplicate-ID and capacity outcomes |
| Active answers | `assistant_active_requests` | Per-process in-flight count; one gateway worker is required |
| Reported usage | `assistant_tokens_total{kind}` / `tokens` | Model-reported counts and overlapping subsets; unknown fields remain absent/null |
| Citation IDs | `assistant_citations_total{result}` | Present, missing or invalid source IDs; not factual accuracy |
| Retrieval | `retrieval_ms`, `corpus_version`, `source_ids` | Gateway retrieval duration and approved-corpus provenance in personal metadata |

The **ServingOps / Real traffic beta** dashboard is separate from the five lab dashboards. `assistant.request` contains an `assistant.model_stream` span and a retrieval-duration attribute, but not engine-internal prefill/decode spans. The record contains a trace ID; prompts, answers and personal access keys are not span attributes. If the process crashes before finalization, stale admissions are later marked abandoned in the ledger; process-local counters cannot reconstruct those missing terminal events.

Use `compose.cpu-observability.yaml` after the CPU and observability overlays to scrape the private model's engine metrics. Gateway/worker RSS is not model-container RAM; use `docker stats --no-stream` for that container. GPU/HBM measurements remain unavailable on A1. The [service runbook](servingops-runbook.md#add-monitoring) documents exact measurement boundaries and provisional CPU-specific alert targets.

## Learning-lab signals and provenance

Lab serving histograms and counters carry `mode` and `source` where applicable. Modes are `combined`, `disaggregated`, or `upstream`; sources are `simulated` or `upstream`. Resource counters and capacity gauges have their own bounded labels.

| Signal | Metric / record | Definition |
|---|---|---|
| First visible content | `lab_ttft_seconds` / `ttft_ms` | Gateway dispatch to first nonempty content |
| Whole request | `lab_request_seconds` / `duration_ms` | Through final stream event, before persistence |
| Visible TPOT | `lab_tpot_seconds` / `tpot_ms` | First-to-last content / (known visible tokens − 1) |
| Synthetic token ITL | `lab_itl_seconds` / `itl_ms` | One synthetic token per emitted unit |
| Real stream chunk gaps | `lab_chunk_gap_seconds` | Explicitly not token ITL |
| Stage timing | `lab_stage_seconds{stage=...}` | Queue, prefill, handoff, decode and worker RPC spans |
| Completion status | `lab_requests_total{status=...}` | ok, error or cancelled |
| Usage | `lab_tokens_total{kind,provenance}` | Input/output and their subsets, only when known |
| Prefix cache | `lab_prefix_cache_bytes`, capacity, evictions, queries | Simulated bytes / hits / misses |
| Handoff | `lab_kv_transfer_bytes_total`, `kv_effective_mb_s` | Modeled payload divided by measured modeled duration |
| Queues | `lab_worker_waiting`, `lab_worker_running` | Current simulated waiting and running counts |
| Goodput | `lab_slo_requests_total` | Successful requests satisfying both request targets |

Worker phase records have `clock=worker`, and their offsets are relative to that worker's local start. RPC spans in the gateway include network and worker wait. They are nested measurements, so do not sum gateway RPC and worker phase durations together. Distributed tracing backends may need clock-skew correction for visual positioning; duration arithmetic never subtracts clocks from different hosts.

Goodput uses the actual benchmark wall-clock interval. Failed requests count toward attempted throughput and error ratio, not successful throughput. Null TPOT means an SLO is not fully evaluable; inspect `slo_evaluable` before interpreting goodput. One-token responses do not have a meaningful per-token average.

## Learning-lab trace shape

```text
llm.request
  prefill.rpc [gateway clock, remote mode only]
    worker.prefill [worker clock]
      prefill.queue
      prefill.compute
  kv.transfer [simulation only]
  decode.rpc [gateway clock, remote mode only]
    worker.decode [worker clock]
      decode.queue
      decode.reasoning [optional, simulated]
      decode.visible
```

Local mode emits phase spans directly below the request. The generic real upstream adapter has gateway arrival measurements but cannot see engine internals; use engine Prometheus metrics and engine tracing. No per-token spans are exported, avoiding unnecessary trace volume.

Span attributes include `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.usage.reasoning.output_tokens` and `gen_ai.usage.cache_read.input_tokens` when available. The GenAI conventions are evolving, so pin instrumentation versions and confirm your collector mappings when upgrading. `reasoning` is a count only; the gateway does not persist chain-of-thought text.

## Useful queries

```promql
# p95 TTFT, separated by provenance
histogram_quantile(0.95,
  sum by (le, mode, source) (rate(lab_ttft_seconds_bucket[5m])))

# Tokens actually counted as output; do not add reasoning again
sum by (mode, source) (rate(lab_tokens_total{kind="output"}[5m]))

# Real NIXL bytes and aggregate effective transfer bandwidth
sum(rate(vllm:nixl_bytes_transferred_sum[5m]))
sum(rate(vllm:nixl_bytes_transferred_sum[5m]))
  / sum(rate(vllm:nixl_xfer_time_seconds_sum[5m]))

# Real engine KV utilization
vllm:kv_cache_usage_perc
```

Metric availability depends on the exact engine/connector version. `observability/engine-targets.json` starts empty. Add private engine addresses and a bounded role label, then Prometheus will discover them:

```json
[
  {"targets": ["10.0.0.10:8100"], "labels": {"role": "prefill"}},
  {"targets": ["10.0.0.10:8200"], "labels": {"role": "decode"}}
]
```

Do not expose engine ports to the internet. On a same-host loopback-only GPU setup, run Prometheus on that host or use an SSH tunnel/private reverse proxy; a VM private-IP target cannot reach an engine bound only to 127.0.0.1. Monitor vLLM `num_requests_waiting`, `num_requests_running`, `request_prefill_time_seconds`, `request_decode_time_seconds`, prefix counters, NIXL transfer failures/expired leases, and NVIDIA DCGM GPU utilization/memory when those exporters are installed. These engine/GPU signals are not generated by the CPU simulator.

## Dashboards, alerts, and storage

Six Grafana dashboards are provisioned from committed JSON: five lab dashboards and one real-assistant dashboard. OTel sends traces to Tempo (24-hour retention); Prometheus uses three-day/512 MB retention. Lab JSON stdout includes request ID, trace ID, mode, status and duration. Log rotation is bounded per service in Compose; the CPU model has logging disabled. The lab reads its shared experiment store, while the assistant reads only the authenticated user's metadata from a separate database.

Lab Prometheus rules cover TTFT > 750 ms, TPOT > 50 ms, request failures > 2%, modeled cache pressure and worker availability. Separate assistant rules flag repeated real failures, p95 TTFT above the provisional 30-second CPU target, and an unavailable configured model. These are example/provisional targets, not achieved SLAs. Rules evaluate, but notification routing is not configured. Add Alertmanager or OCI alarms with an explicit destination when ready.

Actual billing/cost data is unavailable from inference timings. For a GPU experiment, record total instance cost and elapsed billed time, then compute `billed_cost / generated_tokens × 1,000,000`. If using provider prices, keep cached-input, uncached-input and output rates separate. Never add reasoning tokens to an output total that already includes them.

## OCI option

The CPU/RAM sampler and optional GPU exporter are documented in [Hardware telemetry](hardware-telemetry.md). GPU analytical estimates are never exported as measured hardware counters.

`scripts/export_oci.py` exports aggregate benchmark points to namespace `llm_observatory` using OCI Monitoring's ingestion endpoint and your configured SDK profile. This is explicit export, not continuous scraping. For OCI APM, route the collector through the supported ingestion configuration for your APM domain. Obtain the data-upload endpoint and private data key in OCI; keep the resulting collector environment outside Git. Follow [Oracle's OpenTelemetry integration](https://docs.oracle.com/en/learn/oci-apm-with-opentelemetry/index.html). The local Tempo path works without Oracle APM configuration.
