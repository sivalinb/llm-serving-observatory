# Serving Academy: end-to-end learning and capstone

[Open the public academy](https://llm-serving-observatory.siva-babu.chatgpt.site/learn/).

The initial portfolio emphasized the request path, memory planning and telemetry. The academy fills the surrounding lifecycle: define the workload, ship the right model, schedule and scale execution, operate securely, evaluate quality and justify cost. These are learning modules and exercises, not claims that every described engine feature is implemented in this repository.

## Ordered curriculum

Each module contains three concept explanations, what to observe, a common failure/trap, a practical task, a three-choice self-check with explanation, a prerequisite link and primary reading. The structured source of truth is `sites/curriculum.json`; `scripts/render_academy.py` validates and compiles it to escaped HTML. Readings were reviewed on 2026-09-08; runtime features and telemetry conventions must be checked against the deployed version.

| Order | Module | Evidence / practice focus |
|---|---|---|
| 01 | Workload and service contract | Online/offline needs, context/output mix, quality and latency objectives |
| 02 | Model artifacts and lifecycle | Weights/tokenizer/template/config pinning, license, load/warm-up/readiness |
| 03 | Tokens, context and sampling | Model-specific tokenization, stop reasons, cached/reasoning subsets |
| 04 | Prefill, decode and streaming | Client/server TTFT, TPOT/ITL, proxy buffering and clock boundaries |
| 05 | CPU/GPU memory | DRAM/HBM/GDDR, weights/KV/workspace, MHA/GQA/MQA and architecture caveats |
| 06 | Admission and batching | Bounded queues, fairness, continuous batching and chunked prefill |
| 07 | Cache management | Paged KV, prefix reuse, response caching, eviction and offload |
| 08 | Execution optimization | Kernels, graph capture, quantization, FlashAttention and speculation |
| 09 | Parallelism and topology | Data/tensor/pipeline/expert/context parallelism, NUMA, collectives and links |
| 10 | Disaggregated serving | Separate pools, compatible KV handoff, transfer failures and equal-budget comparison |
| 11 | Infrastructure | Compute/storage, drivers, containers, VCN/subnets, TLS/IAM and optional Kubernetes |
| 12 | Routing and autoscaling | Cache locality/fairness, probes, ready capacity, cold starts and draining |
| 13 | Observability | Metrics/traces/logs/profiles, cardinality, redaction and evidence provenance |
| 14 | Benchmarks and SLOs | Open/closed-loop load, percentiles, goodput, error budgets and burn-rate alerts |
| 15 | Reliability | Deadlines/cancellation, retry policy, overload, OOM, backups and recovery |
| 16 | Security and privacy | Tenant authorization, prompt injection, secrets, tool boundaries and retention |
| 17 | RAG and tools | Authorized retrieval, reranking, structured outputs, bounded agent workflows |
| 18 | Specialized models | Multimodal encoders, LoRA/adapters, MoE execution versus memory residency |
| 19 | Evaluation and release | Held-out quality, versioned release tuple, canary/control and rollback |
| 20 | Economics and capstone | Cost per useful completion, idle capacity, retries and a complete evidence package |

The original homepage remains an animated first-request introduction. The academy's three-row map connects **control → request execution → operational feedback**. A separate signal map starts with a symptom and identifies the next measurement at visitor, gateway, model, hardware, quality, reliability and cost layers.

## What you can run publicly

| Exercise | Calculation | Important limitation |
|---|---|---|
| Memory | Weight bytes + dense/GQA KV bytes + user-specified reserve | Single-device analytical capacity, not actual allocation; excludes fragmentation and format metadata |
| Latency | Queue + uncached prompt/rate + optional KV setup/transfer + first-output step | Fixed rates and serial work; real systems may overlap/contend and full prefix hits still have overhead |
| Tokens | Input + output; cached and reasoning remain subsets | Remaining output assumes no other output categories; unknown subsets stay unknown |
| Traffic/SLO/cost | Deterministic bounded FIFO with 24 arrivals and independent slots | Not continuous batching, real engine throughput, answer quality or an OCI price quote |

Memory uses **GiB = 2³⁰ bytes**. KV bytes are `2 × layers × KV heads × head dimension × tokens per sequence × concurrent sequences × KV bytes per element`. MHA/GQA/MQA change the KV-head count; MLA, sliding-window and hybrid/state-space models need different formulas. Weight and KV precision are independent.

The latency exercise's payload is independently specified in MiB, and effective link rate in GiB/s. Transfer milliseconds are `setup + MiB / 1024 / GiB_per_second × 1000`. Prefix reuse changes the assumed prefill work, not automatically the state needed by a different receiver. Combined mode omits handoff. The illustrative first-output processing term is deliberately separate from prompt work; this is not a statement that every engine performs an additional full decode step for its first token.

The traffic exercise uses 200 ms prefill and 32 output tokens at 20 ms per generation step. Each accepted request occupies a slot for 840 ms; its TTFT is queue wait + 220 ms. Arrivals beyond the queue bound are counted as rejections. Goodput counts accepted requests meeting both TTFT and TPOT targets, divided by the full run duration. Nearest-rank p95 is descriptive for the accepted sample; rejected requests remain explicitly reported. Total cost covers the full run at a user-supplied hourly rate. Cost per SLO completion is undefined when none qualify, even when the cost slider is zero.

All calculations happen in page memory. No network/model calls, analytics tracker, user profile, certificate or saved learning-progress service is added. Search and self-checks also stay local and reset on reload. Lessons and answer explanations render without JavaScript; interactive controls require it. The existing private `/lab` is still a separate, more detailed experiment environment.

## Practice ladder

1. **Public/browser:** read the 20 modules, answer self-checks, change one assumption in each exercise and explain the resulting signal. Opening a solution is learning support, not a certified assessment.
2. **Local CPU:** run the existing simulator and assistant profile, inspect actual token/timing receipts, contrast simulation with real inference and use the hardware report. A small model can be wrong; inspect source support separately.
3. **OCI Phoenix CPU:** review eligibility/costs, apply the existing one-VM deployment only with authorization, secure public HTTPS, keep model/operations ports private and gather deployment evidence.
4. **Optional accelerator/cluster:** separately provision appropriate hardware only with approval. Measure batching, real tensor handoff, topology, distributed failure and autoscaling on supported engines. Kubernetes, GPU allocation, RDMA/NIXL, real cache offload, speculative decoding and HA are taught here but not installed by this change.

## Capstone acceptance checklist

- [ ] Define audience, authorized corpus/tools, workload distribution, context/output limits and quality requirements.
- [ ] Pin and record the model checksum, license, tokenizer, template, engine image, configuration and corpus revision.
- [ ] Diagram trust boundaries, compute/storage/network paths, public ports and private operator access.
- [ ] Record an infrastructure plan and cost assumptions; verify Phoenix home-region eligibility, available capacity and existing allocations before applying.
- [ ] Exercise authentication, tenant isolation, quotas, bounded admission, cancellation and secret rotation.
- [ ] Capture real input/output usage, client/server TTFT, end-to-end latency, stream-gap and CPU/RAM evidence, with unknown fields labeled.
- [ ] Run repeated cold/warm and short/long workload cases. Report offered/accepted/failed load, sample counts, percentiles and SLO goodput.
- [ ] Evaluate held-out grounded answers and failure cases. Report factual support separately from citation-ID validity or HTTP success.
- [ ] Inject an authorized model/dependency failure; record user-visible behavior, quota reconciliation and recovery.
- [ ] Restore an actual backup in an isolated test; compare against stated RPO/RTO.
- [ ] Demonstrate a limited rollout and rollback to a pinned release; document single-node and capacity limitations.
- [ ] Explain cost per useful completion, idle overhead and alert-versus-spending-cap limitations.

These are future acceptance tasks unless backed by the [validation record](../reports/validation.md). Nothing in the academy claims a completed OCI/GPU deployment, quality certification or production-scale capacity result.

## Maintain and validate

```bash
ruff check .
pytest -q
node --check sites/academy.js
node --test tests/home-tour.test.cjs tests/academy.test.cjs
python scripts/build_portfolio.py
```

Python tests cover path ordering, source/quiz structure, HTML escaping, link/anchor/controller wiring and export allowlisting. Pure Node tests cover memory arithmetic, KV units, token subset/unknown behavior, bounded deterministic queues, goodput/cost denominators, input validation and search matching. These are not browser-interaction or GPU performance tests. Follow [Sites publishing](sites-publishing.md) to push the exact validated source and deploy a new saved version.
