# Native observability release — 2026-09-08

**Implemented and CI-verified; OCI upgrade held before any application change.**

Code commit: [`4cb9f9591c331f8d3c989be9f41ac15ffe64b9ad`](https://github.com/sivalinb/llm-serving-observatory/commit/4cb9f9591c331f8d3c989be9f41ac15ffe64b9ad). [Architecture, access and operating guide](../docs/observability-dashboard.md).

## Verified implementation

- Native `/observability` overview, metric catalog/charts, request timeline and sanitized events. Existing personal-key authentication; separate host-granted operator roles for global telemetry.
- 96 Python and 28 Node tests, Ruff, JavaScript syntax, static export and whitespace checks pass locally. Two pre-existing test-library deprecation warnings remain. Local shell HTTP 200 verified; browser interaction/visual QA is not claimed.
- [CI run 34283790034](https://github.com/sivalinb/llm-serving-observatory/actions/runs/34283790034) passed all four jobs: test/integration/public boundary, full real CPU, shared real CPU, and Terraform validation. No Terraform apply occurred.
- The shared dashboard smoke queried actual Prometheus: **52 catalog entries including four calculated views, two healthy targets, three healthy evaluated rules, one retained CI request and two returned chart points**. The very short scrape history is not 24-hour performance evidence; unit fixtures exercise the response bounds and missing-data paths.
- Ordinary-user denial, explicit operator grant, operator revocation and key revocation passed. The dashboard smoke made **zero model calls**; the shared job's preceding, separate inference smoke produced its real runner request. Runner results are not Phoenix/ARM benchmarks.
- No raw log backend, persisted traces, GPU/HBM measurements, model cgroup/host CPU/disk exporter, new container or public route was added. The public Sites publication remains unchanged.

## OCI deployment safety hold

At the fresh pre-upgrade check, the existing observatory gateway/model/Prometheus containers were healthy with zero restarts. The dedicated remote checkout was still `757ab4b`; the gateway image still contained the previously deployed `800842e` application code. The new dashboard was **not deployed**.

Initial host readings at **22:06:43 UTC** showed about **5.65 GiB available RAM**, **8.15 GiB free Docker-filesystem space**, no swap use and successful incumbent API probes. Those instantaneous readings do not explain prior memory peaks.

The incumbent collector's restart count had increased from **9** in the prior pilot report to **10**, with its latest restart at **21:29:51 UTC**, before this upgrade. Its failure log showed an insertion rejected with ClickHouse HTTP 500 / `MEMORY_LIMIT_EXCEEDED`: a 3.60 GiB tracked-memory limit was exceeded and the query was selected for termination. The exception propagated out of the collector and it restarted. Docker did **not** report an OOM kill for the collector or ClickHouse.

This establishes the immediate failure path, not the workload-level cause or whether the existing pilot's resource footprint contributed. Current free RAM and successful probes do not prove that the transient memory problem is resolved. The rollout was therefore held for capacity investigation instead of adding build/restart activity to the shared host.

A finite five-minute read-only follow-up (22:06:43–22:11:43 UTC, 11 samples) showed no further restart, OOM flag, swap use or failed API probe. Gateway/model/Prometheus image IDs and start times remained unchanged. This quiet observation window does not resolve the earlier memory-limit incident or prove sustained capacity; no post-upgrade or load comparison is claimed.

Only read-only SSH checks and a temporary, existing-key 30-minute Bastion session were used. **No image build, gateway recreation, model call, DB migration, backup overwrite, role grant, resource resize, firewall change or incumbent modification was performed on OCI for this release.**

Before resuming, investigate the incumbent database memory-limit event and collector failure handling with explicit scope approval, confirm a stable baseline and adequate headroom, then follow the [gateway-only upgrade procedure](../docs/oci-shared-host.md#6-upgrade-the-private-dashboard). Do not silently raise limits, disable protections, modify the incumbent or expand cloud capacity to bypass this hold.
