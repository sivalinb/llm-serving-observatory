# Portfolio walkthrough: explain the system, then show evidence

## The 30-second introduction

The [public Serving Academy](https://llm-serving-observatory.siva-babu.chatgpt.site/learn/) now supports an end-to-end teaching demo: search a concept, explain its metrics and failure mode, answer a self-check, then change a memory/latency/traffic/token assumption. Use the [capstone checklist](learning-path.md) to connect those hypotheses to future measured infrastructure and service evidence. Public exercise values are not benchmark results.

For a public, no-setup introduction, share [the ChatGPT Sites portfolio](https://llm-serving-observatory.siva-babu.chatgpt.site). It includes the tour and architecture diagrams, not live inference or the interactive lab. The demonstrations below require the full local/OCI application. See [publication boundaries](sites-publishing.md).

> I built an LLM-serving observatory with an animated beginner's guide, an invite-only CPU documentation assistant, and a private experiment lab. It separates real inference, simulated KV handoffs, analytical GPU-memory estimates, and measured CPU/RAM telemetry. Personal keys, quotas, streaming receipts and traceable validation make it a small but inspectable service with a Phoenix deployment path.

The private CPU assistant and native dashboard are now deployed on the existing Phoenix ARM host. Attach the [actual OCI pilot evidence](../reports/oci-private-pilot.md) and [dashboard release evidence](../reports/observability-release.md) when saying “deployed on OCI.” Do not say “benchmarked on GPUs”: no GPU deployment is claimed. The simulation report is local, the hardware report analytical, and the separate [CI CPU receipt](../reports/real-cpu-smoke.json) is from a GitHub runner. These remain distinct evidence sources, not answer-quality or production-scale claims.

## Current private OCI demo

1. Open `/assistant#system` and follow the seven-step **How it works** guide. Explain a personal key, account workspace and the authentication/authorization distinction before showing private data.
2. Connect with your own key. Select an example to fill the question box, then explicitly choose Search guides or Ask AI. The walkthrough itself submits nothing.
3. For an approved real answer, explain TTFT, token subsets, truncation and source verification. Alternatively inspect an existing receipt without creating traffic.
4. Reconnect at `/observability`. Show My requests/My events; with an explicit operator grant, show Overview & alerts, Metric explorer and All project filters.
5. Explain the measured CPU/RAM signals and missing raw logs, stored traces, GPU/HBM and model-cgroup history. The shared pilot does not have `/lab`, Grafana or Tempo. Use the separate full-lab demonstration below only where that stack is actually running.

See the [first-visit guide](using-the-service.md) for playback, keyboard/reduced-motion support, safe questions, access and troubleshooting.

Start at `/` to explain the system without an invite. The animation makes no model calls; compare modes, pause or select a stage. Continue to `/assistant` for the real service, and open `/lab` through your local connection or SSH tunnel for the demo below. Public HTTPS intentionally blocks the lab. For an assistant-focused demo covering identity, quotas, citations and recovery, use the [five-minute service walkthrough](servingops-runbook.md#portfolio-demonstration-five-minutes).

## Eight-minute full isolated lab demo (not the shared OCI pilot)

| Time | Show | Explain / verify |
|---|---|---|
| 0:00–1:00 | Animated homepage: Combined → Disaggregated → First token | Conceptual cache handoff and TTFT boundary; animation is not live traffic |
| 1:00–2:00 | Live lab: run twice with a shared prefix | Cache reuse reduces prefill work; cached tokens remain part of input |
| 2:00–3:00 | Longer prompt, then longer output | TTFT and generation duration answer different user-experience questions |
| 3:00–4:00 | Hardware: Baseline → Save baseline → Long context | Same weights, growing KV, exceeded memory budget; estimated speed disappears when infeasible |
| 4:00–5:00 | 4-bit weights; then Slower HBM path | Weight quantization does not change KV precision; bandwidth changes speed bounds, not capacity; compare with the saved baseline |
| 5:00–6:00 | Real process resources and Grafana hardware dashboard | CPU cores, RSS and container memory are actual measurements; HBM estimates and external GPU counters are different evidence |
| 6:00–7:00 | Disaggregated transfer failure | Error trace, terminal status, released worker capacity and subsequent successful request |
| 7:00–8:00 | Benchmark JSON, hardware comparison export, tests and limitations | Reproducibility, closed-loop limitations, equal-resource comparisons and what remains unvalidated |

All hardware presets reset every field to the documented defaults, then change one assumption. Save the baseline first. Editing a field is also supported; export includes all values, not just the visible comparison columns.

## Four reproducible hardware experiments

Run `python scripts/hardware_report.py` to print the exact report committed at `reports/sample-hardware.json`. No model, GPU, credentials, network or paid resource is used. The same default configurations are available in the UI.

1. **Baseline:** 8B parameters, 16-bit weights/KV, 4096 input + 512 output, four active sequences, 24 GiB device. Ask where memory goes and how many equal-length sequences fit.
2. **Context pressure:** change input to 32768 only. Ask whether more memory or reduced concurrency is required. A hypothetical capacity failure is not an induced GPU OOM.
3. **Weight quantization:** change weight precision to 4-bit only. Check that weight bytes shrink fourfold before overhead while KV bytes do not change. Treat accuracy and speed as unvalidated.
4. **Bandwidth sensitivity:** change memory bandwidth from 1000 to 500 GB/s only. Capacity stays identical. The memory term doubles; the network handoff does not change.

Extra exercise: halve the network link bandwidth instead. Explain why it changes KV-handoff time without changing the modeled decode-memory term.

## Evidence a reviewer can inspect

| Claim | Evidence | What it does not establish |
|---|---|---|
| Beginner journey is interactive and bounded | Nine animation-state tests, reduced-motion support, pause/restart and stage selection | Measured performance or completed browser visual QA |
| Real CPU inference works | Pinned model/container and CI streaming smoke receipt | Phoenix performance, citation quality or GPU behavior |
| Users have isolated access and admission limits | Invite, key rotation, per-user history and concurrent quota tests | Enterprise SSO, HA or anonymous public-service hardening |
| Request stages are instrumented | SSE output, retained trace, Prometheus histograms, Tempo | Real internal GPU spans from a generic upstream API |
| Token accounting avoids double counting | Tests for cached input and reasoning subsets | A provider's unreported token categories |
| Memory accounting is reproducible | Formula tests, UI comparison export, sample hardware report | Real allocator behavior, accuracy or GPU performance |
| CPU/RAM signals are real | psutil snapshots, per-service metrics, optional cgroup-v2 counters | Per-request CPU attribution or GPU utilization |
| Hardware telemetry is extensible | Private DCGM discovery file, field list, provisioned GPU panels | Exporter installation or live GPU validation |
| Deployment is reproducible | Docker smoke test, OCI Terraform validation, cloud runbook | Successful provisioning or free eligibility in a particular tenancy |

## Design decisions worth discussing

- **Three explicit evidence types.** Synthetic serving has real wall-clock timings; capacity planning is analytical; hardware counters are measured. They never share a fictitious “GPU utilization” metric.
- **Null is meaningful.** Missing reasoning counts, unsupported GPU fields, first CPU intervals and infeasible-plan speed estimates stay unavailable rather than zero.
- **Bounded operations.** Calculator inputs, context sweeps, benchmark concurrency, caches and retained records have limits. The calculator cannot allocate the GB of memory it displays.
- **Cost-conscious separation.** The CPU lab remains usable with paid GPU resources off. Stopping model processes does not stop OCI billing; the GPU runbook requires checking instance cleanup.
- **Observable failure.** Failed transfers are visible and tested for recovery. Availability and resource alerts evaluate locally; notification routing needs an explicitly configured destination.

## Honest résumé / README wording

"Built an OCI-ready LLM serving observatory with an animated learning experience, invite-only CPU inference, source retrieval, atomic quotas and per-user metadata isolation; implemented streaming latency/token accounting, disaggregated worker simulation, GPU-memory planning, and measured resource telemetry using FastAPI, Prometheus, Grafana and OpenTelemetry."

Do not claim a throughput improvement, production scale, customer impact or cost saving without a reproducible real workload and a fair baseline. For a real GPU study, record model/tokenizer revisions, engine commit, precision, total GPU count, topology, warmups, independent repetitions, request-length distribution, errors and actual billed time.

## Next validation milestone—not a claim of completion

The private shared CPU deployment and native-dashboard checks are complete with the evidence linked above; the full lab and GPU stack are not deployed on that host. Next validate small-model answer quality, explicitly approved capacity tests, off-host recovery and alert delivery. Capture Grafana/Tempo evidence only in a separately approved isolated full lab. Real GPU disaggregation still requires compatible hardware, cost approval and measured transfer/correctness results.
