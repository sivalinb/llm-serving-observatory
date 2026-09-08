# Validation record

## Native private observability (2026-09-08, local and CI validation; OCI held)

The `/observability` implementation passes **96 Python tests, 28 Node tests and Ruff** locally. New coverage includes operator default-deny/fresh revocation, cross-user request/event isolation, enum-only event sanitization and bounded retention, backup recovery, Prometheus catalog and query budgets, stale/unavailable responses, invalid expressions, null-versus-zero math and public-export exclusion. Two existing dependency deprecation warnings remain. The local shell responds HTTP 200; no browser interaction, screenshot or responsive-rendering QA is claimed.

All four jobs in [CI run 34283790034](https://github.com/sivalinb/llm-serving-observatory/actions/runs/34283790034) passed for code `4cb9f95`, including a no-inference dashboard smoke against actual Prometheus and the public-edge route/asset boundary. The dashboard smoke verified 52 catalog entries, two healthy targets, three evaluated rules and temporary operator/key revocation. **OCI was not upgraded:** a pre-upgrade check found an incumbent database memory-limit failure and increased collector restart count. [Exact release evidence and deployment hold](observability-release.md). No new backend/container, public publication, GPU data, raw log storage or persisted trace backend is introduced.

## Private Phoenix deployment (2026-09-08)

The shared assistant is now deployed on the existing A1 ARM64 host. The [OCI pilot report](oci-private-pilot.md) records actual runtime controls, three sequential real-inference receipts, before/during host observations, backup verification and remaining release gates. It explicitly separates transport success from answer quality: every answer reached the 64-token cap and two lacked citations. It is a private beta, not a public endpoint or a throughput/HA result.

Deployed code `800842e05e409259ed5733ecdff34851daa6edde` passed [all four CI jobs](https://github.com/sivalinb/llm-serving-observatory/actions/runs/34273067398). Local validation includes 85 Python tests and Ruff. The host-specific fixes retain fail-closed gates: bounded SHA-256 reads support Oracle Linux's Python 3.9, and Docker capability detection uses the actual JSON `CpuCfsQuota` key. No admission threshold was relaxed.

The academy remains a separate, unchanged public static publication; this deployment does not enable its live chat link. No public firewall/NSG change, new VM/disk, paid inference, GPU/HBM measurement, alert delivery or persisted trace backend is claimed.

The sections below are **historical point-in-time validation records**. Their “not deployed” statements describe those earlier releases, not the current private pilot. They remain to preserve the distinction between local, CI, simulated and OCI evidence.

## Shared-host profile before deployment (2026-09-08)

- Adds a standalone assistant-only deployment: half-CPU / 2.5 GiB model, 256 MiB gateway, optional 256 MiB Prometheus, private networking, separate loopback ports and volumes, no lab workers or trace stack. The [runbook](../docs/oci-shared-host.md) includes an architecture map, capacity gates, real-metric boundaries, canary checks, search-only fallback and rollback.
- Local validation passes: **83 Python tests**, **25 Node tests**, Ruff, assistant JavaScript syntax, static portfolio export and whitespace checks. New regressions cover absent lab routes/schema/database, full-lab compatibility, output-cap enforcement before admission, deployment defaults, search-only behavior, standalone limits/isolation and fail-closed host gates. Two upstream test-library deprecation warnings remain.
- CI now checks the shared Prometheus configuration and runs the real CPU smoke in both full and shared profiles. The shared job also inspects actual Docker CPU/RAM/swap limits, health/restarts, private bindings, disabled lab/auth boundaries and Prometheus targets/rules. Consult the workflow result for the committed revision; configuring a job is not evidence that it passed.
- The initial Linux integration run caught a real connectivity defect: containers were healthy on an internal-only network, but loopback publishing was unreachable. The corrected topology gives gateway/Prometheus a separate project-owned access bridge and keeps the model exclusively on the internal backend. Runtime checks explicitly verify those network memberships; the host-facing smoke must pass before calling this usable.
- **Verified CI:** [run 34270910559](https://github.com/sivalinb/llm-serving-observatory/actions/runs/34270910559), code revision `3b114bad9ed063fdac1cdb6f520def132a5aa70e`, passed test, Terraform validation, full CPU and shared CPU jobs. The shared runtime checker passed with actual CPU/RAM/swap limits, health/no restarts, private network memberships, API boundaries and both Prometheus targets/rules. Its [raw receipt](shared-cpu-smoke.json) measured 274 input and 64 output tokens, **17,601.68 ms TTFT / 26,112.92 ms total**. One x86 runner sample, not an OCI result; output ended at the configured length limit.
- Docker Engine is unavailable on this laptop. No local container execution, OCI deployment, ARM model performance, incumbent-workload impact, public API exposure, alert delivery or persisted distributed traces are claimed. Runtime CPU limits do not limit Docker builds or downloads.
- At this pre-deployment release, the public Sites export was unchanged and real inference was not yet deployed on OCI. The later private deployment is recorded above.

## End-to-end Serving Academy (2026-09-08)

- Adds 20 ordered modules and self-checks, five tracks, primary readings, per-module signals/traps/practice, two cross-layer maps and four browser-only exercises.
- Regression checks cover curriculum structure/order, HTML escaping, export links/assets/controller IDs, memory and transfer units, invalid inputs, token subsets/unknowns, deterministic bounded queues, goodput/cost denominators and search matching.
- Local validation passes: 73 Python tests, 25 Node tests (9 animation + 16 academy), Ruff, JavaScript syntax, static export and whitespace checks. The local `/learn/` route returns HTTP 200. GitHub CI and Sites record their separate final publication results.
- The public academy generates no real inference, GPU utilization, telemetry, user-data persistence or OCI resources. Exercise measurements are explicitly analytical or simulated. At this academy release, live assistant deployment was still pending OCI.
- Browser interaction/visual QA, real GPU/kernel optimization, cluster autoscaling, HA, held-out model quality and new OCI benchmarks are not claimed. Sources and exercise contracts are recorded in [the learning path](../docs/learning-path.md).

## Public portfolio export (2026-09-07)

The Sites export is separately built from allowlisted public assets. New regression checks cover deployment-boundary copy, link/anchor/controller wiring, all four diagrams, deterministic output, unchanged full-service entry points, stale-file/symlink rejection and source-contract failures. The export adds no model requests, live telemetry, user-data store or backend. Its local HTTP preview returns 200; browser visual/interaction QA is not claimed. Publication status and the exact source SHA are recorded by Sites, separately from GitHub CI. See [the publishing guide](../docs/sites-publishing.md).

## Animated introduction (2026-09-07 local)

- The root route serves a visual beginner homepage; the private lab moved to `/lab`. The public-edge check verifies the root does not redirect and continues to block lab/operations routes.
- 65 Python tests and 9 Node animation-state tests pass locally. Coverage includes combined versus disaggregated sequences, first-output timing in the illustration, pause/restart, manual stepping, reduced motion, timer cleanup, static asset/anchor/controller wiring and valid SVG geometry.
- [Homepage release CI](https://github.com/sivalinb/llm-serving-observatory/actions/runs/34179964956), commit `77fe465`, passed all three jobs: Python/Node plus public-edge/observability checks, real CPU inference, and Terraform validation. This is automated validation, not a live OCI deployment.
- The tour performs no network requests or real inference and labels all motion as explanatory. Motion stops when the page is hidden or the tour leaves view; reduced-motion users start paused.
- The local root returned HTTP 200 and was handed off for preview. No browser-interaction, screenshot, responsive-viewport or visual-rendering QA is claimed for this update.
- In this earlier homepage release, the OCI hosting architecture was unchanged and no hosting service was created. The later public Sites export is documented above; it does not deploy OCI.

## Real-traffic CPU service (v0.3, 2026-09-07 local / 2026-09-08 UTC)

- 62 local pytest tests pass, including single-use/expired invites, key rotation/revocation, separate-user history, atomic admission across SQLite connections, daily/monthly limits, duplicate request IDs, cancellation, deadlines, malformed/oversized streams, conservative unknown usage, and online backup recovery.
- The [core implementation CI run](https://github.com/sivalinb/llm-serving-observatory/actions/runs/34176647822) passed all three jobs: full tests/observability/public-edge validation, Terraform validation, and **real CPU inference**. The later fixture-regression assertion increases the local test count from that run's 61 to 62.
- The real CPU job downloaded the checksum-pinned official Qwen model, started the digest-pinned llama.cpp container and streamed an answer through the authenticated assistant endpoint. [Raw timing/token receipt](real-cpu-smoke.json): 274 input tokens, 64 output tokens, 1,953.49 ms TTFT, 6,500.02 ms total. These are **one GitHub x86 runner request, not a Phoenix benchmark or a throughput result**.
- That response reached its 64-token cap and had missing citation IDs. This is a recorded limitation, not a passed answer-quality evaluation. The UI prominently warns about both truncation and missing/invalid citations; source links alone do not prove support.
- The transparent 15-query retrieval teaching fixture has recall@3 of 1.0. It is authored against this tiny corpus and is not held-out retrieval or model-quality evidence.
- Browser verification exercised invite redemption, personal quota display, CPU/HBM document search, disabled AI behavior without a configured model, and architecture rendering. The user-facing source excerpts and statuses were verified; no responsive breakpoint or live browser/model streaming test is claimed.
- No OCI credentials or resources were accessed, and no OCI deployment or GPU test occurred. Public TLS issuance still requires a real domain. CI checks the Caddy route boundary using local HTTP, not an issued public certificate.

## Hardware extension (v0.2, 2026-09-07)

- 39 pytest tests passed on Python 3.12.14/macOS ARM64, including deterministic memory accounting, unit conversions, capacity boundaries, independent weight/KV precision, memory-versus-network bandwidth, bounded inputs, cgroup parsing, CPU sampler lifecycle, missing-data behavior and API authentication.
- The committed `sample-hardware.json` is regenerated by the CLI and compared exactly in a test. It contains analytical scenarios, not GPU measurements.
- Ruff, both JavaScript syntax checks and Git whitespace checks passed.
- The updated HTTP smoke test passed against the local gateway: analytical capacity success/failure and real process RSS were verified alongside serving/transfer-failure behavior.
- Browser checks exercised Hardware navigation, saved-baseline comparison, long-context capacity failure, 4-bit weight memory accounting, and live CPU/RAM readings. The new layout and diagram were inspected. A navigation initialization issue found during verification was corrected.
- GitHub Actions now validates Prometheus configuration and starts the full Compose observability stack. Its integration check requires measured RSS from three services, valid dashboard PromQL and the provisioned twelve-panel hardware dashboard. Consult the workflow run for its result; local Docker is unavailable.
- No real GPU or OCI deployment was performed. Cgroup behavior was unit-tested locally; Linux container sampling is covered by the Docker integration path. No responsive-breakpoint or GPU hardware test is claimed.

## Initial serving implementation (v0.1)

Validation performed locally on 2026-09-07 with Python 3.12.14 on macOS ARM64.

- 20 pytest tests passed, covering token accounting, prefix eviction, cancellation, failure recovery, W3C context propagation, upstream stream parsing, usage unknowns, API authentication, config and SVG parsing.
- Ruff checks, JavaScript syntax, and shell syntax passed.
- Terraform 1.9.8 validated against oracle/oci 6.37.0; no cloud resources were created.
- Real HTTP smoke test passed with the gateway and two separate simulated worker processes.
- Browser: live streaming, ledger, waterfall, architecture, and comparison workflows checked. Benchmark page reported zero browser console errors.
- Docker Engine is not installed on the local host. Docker build/Compose execution is configured in GitHub Actions and is not included in the local test claim.
- No real GPU, real model weights, OCI credentials, ADB wallet, or OCI APM domain was supplied. The GPU recipe and cloud export paths require environment validation.

Two upstream test-library deprecation warnings were observed (Starlette/httpx and an AnyIO alias); tests passed.

## Recorded sample

The adjacent JSON is the actual local closed-loop simulation run: 8 requests per mode, concurrency 2, 1 warmup per mode. Warmups are excluded from reported samples. Input/output lengths: 128/32 synthetic units. This is not an OCI or GPU benchmark.

| Mode | p95 TTFT (ms) | p95 TPOT (ms) | Output tokens/s | Errors |
|---|---:|---:|---:|---:|
| combined | 432.64 | 11.82 | 84.47 | 0 |
| disaggregated | 408.14 | 11.86 | 85.58 | 0 |

Combined owns one slot; disaggregated owns separate prefill/decode slots. The small differences in this sample are descriptive only. More repetitions, controlled hardware and equal resource budgets are required for a performance conclusion.
