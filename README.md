# LLM Serving Observatory

[![Validation](https://github.com/sivalinb/llm-serving-observatory/actions/workflows/ci.yaml/badge.svg)](https://github.com/sivalinb/llm-serving-observatory/actions/workflows/ci.yaml)

A working LLM serving laboratory for learning **TTFT, prefill, decode, KV-cache transfer, CPU/RAM, GPU/HBM memory planning, disaggregation, token accounting, and observability**. Run it on a laptop or an OCI CPU VM; connect a real llama.cpp or vLLM server when available.

**Three evidence lanes:** measured serving timings · analytical GPU-memory estimates · real process/container telemetry. No GPU needed for the default lab; no GPU performance claims from simulation.

New here? Follow the [eight-minute portfolio walkthrough](docs/portfolio-walkthrough.md) or the [hardware and memory guide](docs/hardware-memory.md).

The website now opens with an **animated visual homepage**: follow a request through prefill, optional KV handoff, first visible output, decode and observability. Switch architectures, pause, restart or select any stage. The tour is explanatory, makes no model calls, and respects reduced-motion preferences. Open `/assistant` for the real service or `/lab` through your local/SSH connection for experiments.

## New: ServingOps Cloud — real traffic on Phoenix Free Tier

The repository now includes an **invite-only documentation assistant** at `/assistant`: real streamed CPU inference, retrieved references, per-user access keys and isolated history, atomic quotas, cancellation/deadlines, and a separate real-traffic Grafana dashboard. No model configured? It offers document search and explicitly disables AI answers; it never substitutes simulated answers.

![Phoenix service architecture](observatory/static/service-architecture.svg)

The default deployment uses a checksum-pinned Qwen 1.5B quantized model and a digest-pinned ARM-compatible llama.cpp container. It targets **one Always Free eligible A1 VM in `us-phoenix-1`**, with no managed inference calls, GPU or HBM. Verify current free allowance, home region and existing allocations before provisioning. This is a single-node beta, not an HA or zero-cost guarantee.

```bash
python3 scripts/download_model.py
docker compose -f compose.yaml -f compose.cpu.yaml up -d --build --wait --wait-timeout 300
docker compose exec -T gateway python -m observatory.admin invite
```

Open `http://localhost:8000/assistant` through an SSH tunnel, redeem the invite, and save the returned personal key. Follow the [complete Phoenix service runbook](docs/servingops-runbook.md) for HTTPS, monitoring, privacy, backups, rollback and the portfolio demo. The public Caddy profile exposes **the homepage and assistant**; the lab and operations console stay private.

The assistant performs real combined prefill/decode. It does **not** claim real cross-worker KV transfer or GPU disaggregation. Citations are source-ID checks, not factual validation. All real latency and token fields come from actual streams; missing usage details remain unknown.

## Learning lab

![System architecture](observatory/static/architecture.svg)

## Start in two minutes

Python 3.11+ (3.12 tested):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.lock
pip install -e '.[dev]'
uvicorn observatory.app:app --host 127.0.0.1 --port 8000
```

Open [the visual introduction](http://localhost:8000) or [the learning lab](http://localhost:8000/lab). No cloud account, API key, model download, or GPU is needed for simulation. Existing root bookmarks such as `/#hardware` continue to the matching `/lab` view when JavaScript is enabled.

1. Run a request in **Disaggregated** mode and inspect the waterfall.
2. Run it again to see prefix-cache reuse reduce prefill work.
3. Set 8 reasoning tokens within 32 output tokens: visible output becomes 24, total remains input + 32.
4. Lower transfer bandwidth or increase prompt length to expose the handoff cost.
5. Open **Benchmarks** and compare combined versus disaggregated timing.
6. Inject a transfer failure; inspect the retained error trace and metric counter.
7. Open **Hardware & memory**, save a baseline, then try **Long context**, **4-bit weights**, and **Slower HBM path**. Export the comparison and inspect the real CPU/RAM readings below it.

## What is implemented

| Capability | Implementation | Evidence boundary |
|---|---|---|
| Combined serving | One simulated worker slot holds prefill + decode | Synthetic work; measured wall time |
| Disaggregated serving | Independent prefill/decode queues; optional separate HTTP services | Modeled transfer, no KV tensors |
| Prefix cache | Capacity-bounded LRU with hits, misses and eviction counters | Synthetic exact-prefix identity |
| Real model inference | Configured OpenAI Chat Completions stream adapter | Provider-reported usage; gateway arrival timings |
| Real GPU disaggregation | Finite vLLM/NIXL launcher using an explicit official source checkout | Requires two GPUs and hardware validation |
| Hardware planning | Interactive weight/KV/workspace budget, capacity sweep, bounds, baseline comparison and export | Hypothetical single device; no model allocations or GPU benchmark claims |
| CPU/RAM telemetry | Per-service CPU cores, RSS, host RAM and optional cgroup-v2 limits/throttling | Measured process/container aggregates, not per-request attribution |
| GPU telemetry integration | Private DCGM discovery, collector field list, GPU/DRAM/SM and VRAM panels | External compatible GPU/exporter required; no fake samples |
| Observability | Prometheus, five lab dashboards plus one real-service dashboard, OTel collector, Tempo, JSON logs | Source labels keep simulated / upstream data distinct |
| Invite-only assistant | Curated lexical retrieval, real CPU stream, hashed keys, isolated metadata, quotas | Small-model answers require source verification; no private uploads |
| Experiment storage | SQLite WAL, bounded retention, JSON export | No prompts or generated text retained |
| OCI integration | A1 Terraform, private Object Storage, optional budget, export to Monitoring/ADB | Credentials and an OCI apply are required |
| Rich diagrams | Downloadable SVG architecture and lifecycle, live serving-path view | Diagrams document actual boundaries |

**Simulation does not prove GPU speedup.** Combined uses one slot; disaggregated uses one prefill slot plus one decode slot. Continuous batching, PagedAttention, speculative decoding, GPU allocation, and real tensor transport are engine features, not implemented by the simulator.

## Request flow

![Request lifecycle](observatory/static/request-flow.svg)

The main diagram is available as a [full-size SVG](observatory/static/architecture.svg), and the [request-flow SVG](observatory/static/request-flow.svg) explains the latency boundaries and token subsets. Both render in the application's Architecture view. [Architecture notes](docs/architecture.md) include editable Mermaid source and component responsibilities.

## From requests to hardware

![Hardware and memory architecture](observatory/static/hardware-flow.svg)

The hardware view separates **capacity** (what fits), **memory bandwidth** (how quickly data reaches compute), **compute throughput** (model math), and the **network link** (KV handoff). Presets change one variable at a time. If a configuration exceeds capacity, estimated throughput is withheld rather than shown as achievable.

`python scripts/hardware_report.py` reproduces [the analytical sample report](reports/sample-hardware.json). Its complete inputs, formulas and limitations are documented in the [memory contract](docs/hardware-memory.md). These estimates do not change Live lab simulation rates.

## Separate workers + observability

Docker Engine and the Compose v2 plugin are required:

```bash
cp .env.example .env
# Set GRAFANA_PASSWORD in .env. Set LAB_API_KEY before exposing the API.
docker compose up -d --build
docker compose -f compose.yaml -f compose.observability.yaml up -d --build
```

The base Compose file runs gateway, prefill, and decode services. The second command adds the observability stack and OTel export. Ports bind to loopback:

| Surface | Local URL |
|---|---|
| Visual homepage | http://localhost:8000 |
| Lab (private) | http://localhost:8000/lab |
| API schema | http://localhost:8000/docs |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 — `admin` / your configured password |

In Grafana, open the **LLM Serving** folder for User experience, Token ledger, KV cache and handoff, Capacity and SLO, and **Hardware and memory**. The hardware dashboard includes measured CPU/RAM plus optional external GPU panels; GPU panels correctly show no data until configured. For a request trace, copy its full trace ID from exported JSON and search it in **Explore → Tempo**.

Prometheus evaluates alert rules locally. Notification delivery requires adding Alertmanager and your chosen receiver, or configuring OCI Monitoring alarms; the repository does not send notifications automatically.

## Real inference

Run a llama.cpp server with a compatible small, licensed GGUF model:

```bash
llama-server --model /path/to/model.gguf --host 127.0.0.1 --port 8080 --ctx-size 4096 --metrics
```

In a second terminal with the Python environment active:

```bash
UPSTREAM_URL=http://127.0.0.1:8080/v1 \
UPSTREAM_MODEL=your-model-alias \
UPSTREAM_KIND=llama.cpp \
uvicorn observatory.app:app --host 127.0.0.1 --port 8000
```

Use the exact model name returned by the engine's `/v1/models` endpoint, or configure its model alias. Choose **Real inference** in the UI. For a gateway inside Docker, localhost refers to the gateway container: use a reachable engine service name/private address instead.

The adapter also accepts a vLLM endpoint or the official vLLM disaggregated proxy. [GPU runbook](docs/gpu-runbook.md) documents the two-GPU launcher, baseline comparison, engine metrics, and cleanup. The default UI remains usable when GPU resources are shut down.

## Benchmark and export

```bash
python scripts/benchmark.py --requests 16 --concurrency 4 --input-tokens 2048 --prefix-tokens 1024
python scripts/smoke.py --url http://localhost:8000
```

The benchmark CLI prints a JSON report to stdout, with progress on stderr. The UI has an **Export experiment** button. For reproducible trials, record output from several independent runs and use different load patterns. Prefix keys are namespaced per experiment so prior experiments do not silently warm a run. `--warmup 0 --no-cache` is a useful uncached trial.

Each report contains configuration, environment, request records, p50/p95/p99 TTFT, p95 TPOT, successful requests/sec, generated tokens/sec, and goodput. This is **closed-loop load**: each worker submits its next request after completion. It does not establish open-loop saturation or avoid coordinated omission. Small sample p99 values are descriptive, not statistically reliable.

Use `--mode upstream --prompt '...'` for real inference. Synthetic input-length and prefix settings do not alter real engine tokenization. Use actual prompt text of the desired length for real benchmarks.

## Deploy on OCI

Follow [the OCI deployment guide](docs/oci-deployment.md). Terraform creates an A1 VM, VCN, restricted SSH ingress, and private report bucket. It does **not** provision GPUs, Autonomous Database, or a paid monitoring service implicitly.

Always Free eligibility and capacity must be checked in your tenancy's home region. The supplied A1 shape requests 2 OCPUs and 12 GB memory; those amounts are not a guarantee of free eligibility in every account. The optional budget is advisory, not a spending cap.

Once an experiment is exported:

```bash
pip install -e '.[oci]'
python scripts/export_oci.py experiment.json --bucket YOUR_PRIVATE_BUCKET --compartment YOUR_COMPARTMENT_OCID
```

`--adb` additionally stores aggregate results in an existing Autonomous Database using environment-provided connection details. No credentials are committed. See the deployment guide for configuration.

## Measurement rules

- **Gateway TTFT:** first nonempty visible content arrival minus gateway processing start. It excludes earlier HTTP middleware, client/network time before the gateway, and browser rendering.
- **E2E:** gateway processing start to final stream completion, before telemetry persistence.
- **Visible TPOT:** `(last visible arrival − first visible arrival) / (visible tokens − 1)`. Null for fewer than two visible tokens or unknown visible token count.
- **ITL:** intervals between individual synthetic tokens. Real upstream chunk intervals have a separate name; a chunk is not necessarily a token.
- **Reasoning/extended tokens:** a subset of output, not added twice. Missing provider details remain null, not zero. The app does not reconstruct or log hidden reasoning.
- **KV transfer:** simulated byte volume uses a documented dense-attention formula. Effective modeled throughput includes configured setup delay; it is not a network benchmark.
- **Cache capacity:** the serving simulator retains prefix metadata up to a modeled byte budget. The separate hardware calculator estimates end-context active KV; neither implements real allocator fragmentation or GPU OOM.
- **Hardware:** GPU budget and speed bounds are analytical estimates, not utilization measurements. Measured process CPU/RSS, host RAM and optional cgroup-v2 counters use separate names. DCGM DRAM activity is not GB/s.

The [observability guide](docs/observability.md) explains metric names, trace structure, queries, cardinality, and limitations.

## Test and repository layout

```bash
ruff check .
pytest -q
node --check observatory/static/app.js
node --check observatory/static/hardware.js
terraform -chdir=infra/oci init -backend=false
terraform -chdir=infra/oci validate
```

```text
observatory/              FastAPI gateway, simulator, workers, upstream adapter
  static/                Dashboard, architecture SVG, request-flow SVG
observability/           Collector, Tempo, Prometheus, alerts, Grafana dashboards
infra/oci/               Terraform and Ubuntu cloud-init
scripts/                 Benchmark, smoke check, deployment, OCI export, GPU launcher
tests/                   Accounting, failure, cancellation, API, trace and config checks
docs/                    Architecture, measurement contract, OCI and GPU runbooks
.github/workflows/       Python checks, Docker smoke test, Terraform validation
```

This is a learning system with one gateway replica. SQLite, local counters and simulator state are process-local; do not run multiple Uvicorn workers. Add a shared state store, tenant-aware cache isolation, request rate limits, and a real inference scheduler before treating it as a multi-user production service.

## Sources

- [vLLM disaggregated prefill](https://docs.vllm.ai/en/latest/features/disagg_prefill/)
- [vLLM NIXL guide and metrics](https://docs.vllm.ai/en/v0.24.0/features/nixl_connector_usage/)
- [vLLM production metrics](https://docs.vllm.ai/en/latest/usage/metrics/)
- [llama.cpp server](https://github.com/ggml-org/llama.cpp/tree/master/tools/server)
- [OpenTelemetry GenAI conventions](https://opentelemetry.io/docs/specs/semconv/registry/attributes/gen-ai/)
- [OCI Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm)
- [OCI OpenTelemetry monitoring tutorial](https://docs.oracle.com/en/learn/oci-apm-with-opentelemetry/index.html)

Documentation checked 2026-09-07. Engine APIs evolve; pin and record the exact versions used for hardware experiments.
