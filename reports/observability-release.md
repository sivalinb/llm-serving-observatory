# Native observability release — 2026-09-08

**Live on the private Phoenix OCI website. Gateway cutover: 22:49:02 UTC, September 8, 2026.**

Code commit: [`4cb9f9591c331f8d3c989be9f41ac15ffe64b9ad`](https://github.com/sivalinb/llm-serving-observatory/commit/4cb9f9591c331f8d3c989be9f41ac15ffe64b9ad). [Architecture, access and operating guide](../docs/observability-dashboard.md).

## Verified implementation

- Native `/observability` overview, metric catalog/charts, request timeline and sanitized events. Existing personal-key authentication; separate host-granted operator roles for global telemetry.
- 96 Python and 28 Node tests, Ruff, JavaScript syntax, static export and whitespace checks pass locally. Two pre-existing test-library deprecation warnings remain. Local shell HTTP 200 verified; browser interaction/visual QA is not claimed.
- [CI run 34283790034](https://github.com/sivalinb/llm-serving-observatory/actions/runs/34283790034) passed all four jobs: test/integration/public boundary, full real CPU, shared real CPU, and Terraform validation. No Terraform apply occurred.
- The shared dashboard smoke queried actual Prometheus: **52 catalog entries including four calculated views, two healthy targets, three healthy evaluated rules, one retained CI request and two returned chart points**. The very short scrape history is not 24-hour performance evidence; unit fixtures exercise the response bounds and missing-data paths.
- Ordinary-user denial, explicit operator grant, operator revocation and key revocation passed. The dashboard smoke made **zero model calls**; the shared job's preceding, separate inference smoke produced its real runner request. Runner results are not Phoenix/ARM benchmarks.
- No raw log backend, persisted traces, GPU/HBM measurements, model cgroup/host CPU/disk exporter, new container or public route was added. The public Sites publication remains unchanged.

## Actual OCI deployment and access

The owner explicitly approved fixing the deployment blocker. The database investigation found repeated wide `system.metric_log` background merges consuming about 2.3 GiB, competing with the 4 GiB ClickHouse container's 3.60 GiB tracked-memory ceiling. The rejected collector insert itself used under 9 MiB. Only three internal-log merge settings were reduced/tuned online; no rows, retention periods or memory protections were removed. The collector was hardened to back off on transient store failures and resume fresh polling without blindly replaying potentially partially delivered batches.

See the [RackLens incident report and rollback](https://github.com/sivalinb/racklens-ai/blob/main/infra/oci/MEMORY-INCIDENT.md) and [repair code](https://github.com/sivalinb/racklens-ai/commit/a73c1909908fb975fc28ba7d07cc32a001083e1d). Only the collector was recreated for that separately approved repair at 22:29:49 UTC. Its API, database, Grafana and OTel containers were not restarted. The collector's 28 Python tests and 40-case evaluation passed; its overall CI still has a separate pre-existing frontend lockfile installation failure. Do not conflate that workflow with this project's four green jobs.

The observatory checkout was fast-forwarded cleanly to `80e3e8feb63aae5c261f3b4a6bce63ed83f792b3` (documentation following tested application code `4cb9f95`). An online integrity-checked SQLite backup was made to a new private filename before migration; it remains on the same volume, not an off-host recovery copy. The old gateway image is retained as `observatory-shared-gateway:before-dashboard-20260908`. Only gateway was built and then recreated using `--no-deps --no-build --wait`. Database additions are backward-compatible tables; no DB restore or replacement was performed.

| Evidence | Measured result |
|---|---|
| Gateway image | `sha256:eb3f3d34c1f2d50de017c5018ecb85f1d596dab499f1c291c729b63535209c64`, ARM64 |
| Gateway start | `2026-09-08T22:49:02.170424791Z` |
| Model / Prometheus | Original image IDs and 20:34:37 UTC start times retained; no recreation |
| Runtime checker | Passed actual CPU/RAM/swap ceilings, read-only roots, PID limits, health, private networks/ports, lab-disabled and dashboard-auth boundaries |
| Actual Prometheus smoke | 58 catalog entries, 93 chart points, two healthy targets, three healthy evaluated rules |
| Retained request metadata | Three earlier OCI inference receipts; no invented dashboard traffic |
| Authorization | Learner denied global data; temporary operator grant/revoke and key revoke passed; separate owner account verified through authenticated HTTP |
| Inference during dashboard validation | Zero model calls; engine totals remained 276 processed prompt / 192 generated tokens from the earlier pilot |
| Private website | `/observability` returned HTTP 200 through the approved localhost tunnel; no browser interaction or visual QA claimed |

At 22:50:55 UTC, actual cgroup memory was about **49.6 MiB gateway / 1,550.9 MiB model / 58.2 MiB Prometheus**. Each had zero cgroup swap, memory-limit events and OOM events; all were healthy with zero process restarts. CPU ceilings remain 0.25 / 0.5 / 0.25, RAM ceilings 256 / 2,560 / 256 MiB. Gateway throttling is expected under its fractional CPU ceiling and is visible, not hidden. These are point-in-time readings, not peak-load or per-request attribution.

### Host stability and measurement limits

The completed **22:43:07–22:48:07 UTC** quiet post-build observation covered 11 samples over five minutes. Available host RAM stayed at least 5.73 GiB and Docker-filesystem space at least 8.05 GiB. Incumbent health/telemetry probes passed throughout; no service restart or OOM flag appeared. Measured host CPU intervals ranged about 8.4–16.3%, not load-average percentages.

The build had left approximately 73 MiB of host swap allocated; this later quiet window held **75,681,792 bytes (72.2 MiB)** allocated with **zero additional `pswpin`/`pswpout` pages and no allocation growth**. This is explicitly an existing-swap post-maintenance observation, **not** a pass of the unchanged fresh-install zero-swap gate. No swap clearing, cache dropping, memory-limit increase or extra capacity was used. Short quiet observations do not prove sustained production capacity or rule out future memory spikes.

The separate post-cutover quiet observer **did not complete its planned five minutes**: it stopped at **22:51:52 UTC**, after two minutes/five samples, on nine swapped pages read (**36 KiB**, verified 4 KiB host pages). Swap allocation stayed unchanged, with zero new swap-out pages; all service probes and restart/OOM checks still passed. This is recorded as a failed strict no-new-I/O observation, not silently reset to a passing run. A subsequent five one-second `vmstat` intervals showed no swap-in/out, and ClickHouse still had no new memory-limit error at 22:53 UTC (counter **66,204**, last **22:21:33**). The dashboard remains available as a private pilot: a small read of previously swapped pages without growth, swap writes, failed probes or OOM is not evidence by itself of sustained memory pressure. No load/capacity promotion is claimed; recurrent paging, worsening latency or memory failures require renewed review.

### How to open it

With an active approved private connection, visit `http://127.0.0.1:18000/observability`, paste your personal key and select **Connect**. The owner's separate read-only operator grant is enabled; the credential was delivered in a private local file outside Git, not in this report. Use **Overview & alerts**, **Metric explorer**, **Requests** and **Events**. Select **All project requests** and apply the filter to inspect the three existing receipts; a newly created owner's personal history starts empty.

The gateway restart resets its process counters. Unknown/empty rates immediately afterwards are legitimate; the preserved Prometheus history and SQLite receipts have different lifetimes. Events begin with this release and do not import historical stdout. Raw container-log search, persisted distributed traces, GPU/HBM and remote KV transfer remain explicitly absent.

The current connection is time-limited. When Bastion expires or the laptop sleeps, localhost access stops; the OCI containers continue running. Renew an approved Bastion session and tunnel to reconnect. Do not open public SSH or publish Prometheus. The public Sites academy and its hosting manifest/publication remain unchanged. No new VM/disk, paid inference, firewall rule, external network or cloud capacity was added.

## Historical OCI deployment safety hold (superseded by the approved repair above)

At the fresh pre-upgrade check, the existing observatory gateway/model/Prometheus containers were healthy with zero restarts. The dedicated remote checkout was still `757ab4b`; the gateway image still contained the previously deployed `800842e` application code. The new dashboard was **not deployed**.

Initial host readings at **22:06:43 UTC** showed about **5.65 GiB available RAM**, **8.15 GiB free Docker-filesystem space**, no swap use and successful incumbent API probes. Those instantaneous readings do not explain prior memory peaks.

The incumbent collector's restart count had increased from **9** in the prior pilot report to **10**, with its latest restart at **21:29:51 UTC**, before this upgrade. Its failure log showed an insertion rejected with ClickHouse HTTP 500 / `MEMORY_LIMIT_EXCEEDED`: a 3.60 GiB tracked-memory limit was exceeded and the query was selected for termination. The exception propagated out of the collector and it restarted. Docker did **not** report an OOM kill for the collector or ClickHouse.

This establishes the immediate failure path, not the workload-level cause or whether the existing pilot's resource footprint contributed. Current free RAM and successful probes do not prove that the transient memory problem is resolved. The rollout was therefore held for capacity investigation instead of adding build/restart activity to the shared host.

A finite five-minute read-only follow-up (22:06:43–22:11:43 UTC, 11 samples) showed no further restart, OOM flag, swap use or failed API probe. Gateway/model/Prometheus image IDs and start times remained unchanged. This quiet observation window does not resolve the earlier memory-limit incident or prove sustained capacity; no post-upgrade or load comparison is claimed.

During that **initial held attempt**, only read-only SSH checks and a temporary, existing-key 30-minute Bastion session were used. No image build, gateway recreation, model call, DB migration, backup overwrite, role grant, resource resize, firewall change or incumbent modification was performed during the held attempt. The subsequent approved repair and deployment are recorded above.

The hold required explicit approval to investigate/fix the incumbent database and collector, followed by a stable baseline and the [gateway-only upgrade procedure](../docs/oci-shared-host.md#6-upgrade-the-private-dashboard). That approval and targeted work occurred as recorded above. The restriction against silently raising limits, disabling protections or expanding cloud capacity remains.
