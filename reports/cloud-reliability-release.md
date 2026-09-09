# Cloud Reliability Lab release evidence

Status: **OCI recovery, scheduled jobs, stored tracing and infrastructure drift checks verified; recipient confirmation of the drill emails remains pending.** Updated September 9, 2026 UTC.

| Milestone | Verified evidence | Remaining boundary |
|---|---|---|
| Private service | Gateway health and a real 24-token CPU answer passed after the update; model and Prometheus retained their original running containers | Single shared VM, invite-only, no public inference or HA |
| Recover | Actual online snapshot → versioned Vault key → encrypted private object → download → isolated restore; integrity and all six table counts matched | This is a recovery drill, not automatic failover or a live-database restore |
| Schedule | Actual systemd probe and backup both returned success / exit 0; five-minute probe and daily backup timers enabled | Requires the existing VM, Docker and instance-principal access |
| Detect | Stored ServiceHealthy=1 and BackupVerified=1 datapoints; active email subscription; harmless alarm fired and reset to OK | Inbox receipt of both notifications still awaits operator confirmation |
| Trace | Real request ID matched a stored APM trace containing all four expected spans | Sanitized sampled gateway timing, not GPU or token-by-token engine spans |
| Reproduce | Exact 17-resource approved stack applied; drift job succeeded with all 17 resources IN_SYNC | Existing VM and application are intentionally outside this Terraform stack |
| Public learning | Published /reliability/ page with connected architecture and four animated five-step journeys; HTTP verification passed | Static explanatory content, no private telemetry or cloud actions |

## Recovery receipts

The initial actual backup at **01:38:38 UTC** captured **69,632 bytes (68 KiB)**. Its isolated restore check took **0.218 seconds**; integrity and all six table counts matched. A second backup executed through the repaired systemd service at **02:14 UTC** captured **77,824 bytes (76 KiB)** and passed the same checks in **0.231 seconds**. The live SQLite database was never replaced.

The encrypted objects reside in the new private bucket under unique names, with a seven-day asynchronous lifecycle rule. Backup key version 1 was retrieved using the existing VM's instance principal. Secret values were not stored in Git, Terraform state, public pages or Compose environment variables. An integer snapshot age of zero in these receipts is timestamp precision, not a zero-RPO promise. Restore timing excludes operator detection/provisioning and is not whole-service recovery time.

Worker image: `sha256:a48438163e30b4e923ccf97560d3e148c3c32562cdb08faa6b233a39af462537`. Actual runtime inspection verified UID 10001, read-only root, dropped capabilities, **0.1 CPU / 192 MiB / no additional swap**, and no model calls for probes/drills.

## Real request and stored APM evidence

A bounded canary completed successfully with **178 input tokens**, **24 output tokens**, **1,543.87 ms TTFT** and **7,601.08 ms request duration**. The receipt reported 167 cached and 11 uncached input tokens; reasoning and visible-output subsets remained unknown, not zero. This single warm-prefix request is not a benchmark or an SLO.

OCI APM returned the matching trace and these four stored spans:

| Operation | Stored duration |
|---|---:|
| assistant.retrieval | 1 ms |
| assistant.admission | 21 ms |
| assistant.model_stream | 7,578 ms |
| assistant.request | 7,614 ms |

The root span encloses the children; do not sum them. Small differences from the receipt reflect the different start/end boundaries. The gateway exporter counter showed four successful transport attempts, zero filtered spans and zero budget drops; the separate APM query established persistence. No prompt, answer, personal key, account ID or private trace identifier is published in this report.

The gateway was recreated alone at **01:51:17 UTC** with image `sha256:335bfcd5bf80d536497b910d8230d671740a9182af3a9b2f9e404f271f428b36`, retaining **0.25 CPU / 256 MiB / no additional swap** and loopback port 18000. The previous image is retained locally for rollback. Model and Prometheus remained healthy with their original September 8 20:34 UTC start times, zero restarts and no OOM kills.

## Alert drill and scheduling incident

OCI alarm history records the safe drill's **OK → FIRING** transition at **01:47:08 UTC** (trigger time 01:44) and reset to **OK** at **02:05:08 UTC** (trigger time 02:02). The dedicated drill signal was also explicitly cleared to zero. This test did not stop the model or change real health datapoints. The email subscription is ACTIVE; cloud history does not prove inbox delivery. Operator receipt confirmation is still required.

Initial timer execution failed because systemd/SELinux could not read home-directory configuration, and host-level NoNewPrivileges prevented Docker's normal SELinux domain transition. The final root-owned environment and worker-only Compose definition live under /etc/observatory-reliability. The host Docker client uses its normal transition, while the worker retains no-new-privileges and all container limits. **SELinux remains Enforcing.** Actual systemd probe and backup succeeded at 02:14 UTC. This was a reliability-worker deployment fault, not a model outage; missing-worker alarms can legitimately reflect that interval.

## Infrastructure apply and drift

Read-only inventory confirmed PHX and the Free Tier trial. The incumbent bucket's three objects (58,267 bytes) were not modified, and no pre-existing APM domain was found in the inspected compartments.

The initial Terraform 1.5.x plan passed the exact 17-resource create-only guard: no updates, replacements or deletions. Its digest was `97873a4d2674bcca83b792b7c28a3eab43854435f193bf93bc48a3c3e54705e2`. The first apply created 16 resources but failed to create the software key because the new Vault management hostname had not yet resolved.

After DNS became available, a fresh recovery plan verified those exact 16 resource IDs as no-ops and allowed only the missing software key creation. Recovery-plan digest: `efd765aaecf5ebc793e5c6492cda5c46f8e06cc6800a775c5dd3e13eae65b01d`. Its apply succeeded, and both approved Vault secrets were then bootstrapped without publishing their values. No second stack or paid fallback was created.

Resource Manager drift detection completed **02:07:15 UTC**, with **17 IN_SYNC / zero drifted** resources. The stack contains a dedicated compartment, private bucket/lifecycle, DEFAULT Vault/software key, explicitly Always Free APM domain, topic/subscription, exact-VM dynamic group/policies and six alarms.

## Validation and limits

Latest local suite: **128 Python tests + 36 JavaScript logic tests**, Ruff, and Terraform OCI provider 6.37.0 schema validation passed. Two warnings are upstream FastAPI/Starlette deprecations. [GitHub Actions 34300192852](https://github.com/sivalinb/llm-serving-observatory/actions/runs/34300192852) passed the gateway/worker build source, including both real CPU profiles. Subsequent timer definition fixes have focused contract tests and actual host execution evidence above.

Before builds, available host memory was about 6.1 GiB and root disk free space about 8.1 GiB. Existing cold host swap allocation was 71.58 MiB with no active swap-in/out in sampled intervals. Runtime limits do not cap image-build resource use.

Post-deployment observation at **02:15:17–02:15:47 UTC** found **5.99–6.04 GiB available RAM**, healthy incumbent API, and no additional swap activity (host page counters unchanged across all three samples). Gateway/model/Prometheus cgroups each had **zero swap, zero memory-limit hits and zero OOM events**. Their observed memory was approximately 49–59 MiB, 2.13 GiB and 57 MiB respectively; these are samples, not peak guarantees. Existing cold host swap allocation was 71.33 MiB.

The [public learning page](https://llm-serving-observatory.siva-babu.chatgpt.site/reliability/) is illustrative and public; the assistant, credentials, metrics, logs, backups and APM data remain private. No new VM, paid-tier upgrade, public listener, database migration, unrelated workload restart or live-database restore was performed. Always Free eligibility is tenancy-wide, not a zero-invoice guarantee. See the [runbook](../docs/cloud-reliability.md) for boundaries, pausing and rollback.
