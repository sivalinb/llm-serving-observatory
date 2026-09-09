# Cloud Reliability Lab release evidence

Status: **implementation and local validation complete for the initial recovery/tracing components; cloud execution not yet verified**. Updated September 9, 2026 UTC. This report will be amended with actual deployment receipts, not inferred success.

| Milestone | Evidence available | Remaining gate |
|---|---|---|
| Existing private assistant/dashboard | Dated [private-pilot](oci-private-pilot.md), [dashboard](observability-release.md), [guide](usage-guide-release.md) reports | Current live recheck after renewal of Bastion access |
| Recover | Unit-tested encrypted roundtrip, historical key version, WAL, integrity/count verification, no overwrite and tamper rejection | Actual Vault → Object Storage → isolated restore on OCI |
| Detect | Bounded probe/metric worker and six Terraform alarm definitions | Applied alarms, confirmed subscription, delivered fire/recovery notifications |
| Trace | Privacy allowlist, timing spans, bounded exporter tests; no payload export | Gateway deployment, real canary and matching stored APM trace |
| Reproduce | Terraform provider validation; protected state workflow and create-only plan guard | Actual Resource Manager plan/apply/drift receipts |
| Public learning page | Responsive SVG, four five-step animated journeys, reduced-motion/manual controls; static export | Publication and public HTTP verification |

Latest local validation: **127 Python tests and 36 browser-logic tests passed**; existing warnings are upstream FastAPI/Starlette deprecations. Ruff passed. Local Terraform provider schema validation succeeded with OCI provider 6.37.0. [GitHub Actions run 34297662749](https://github.com/sivalinb/llm-serving-observatory/actions/runs/34297662749) passed all four jobs, including both real CPU profiles and a bounded worker-image smoke test, for the initial reliability source. This is not proof of deployed OCI IAM/service behavior.

Read-only OCI inventory confirmed Phoenix and a Free Tier trial account. The existing bucket contained three objects totaling 58,267 bytes; it was not modified. Actual APM service listings in the root and existing child compartment returned zero domains. The interrupted Cloud Shell connection was recovered in a fresh authenticated console tab.

Resource Manager accepted the dedicated stack from source `bbeeac5998c764c583b5778cc224b054c72fc22b`. Its Terraform 1.5.x plan **succeeded** and passed the exact 17-resource create-only guard: no updates, replacements or deletions. The reviewed plan digest was `97873a4d2674bcca83b792b7c28a3eab43854435f193bf93bc48a3c3e54705e2`. The separate approved apply was submitted and remains in progress at this checkpoint. Runtime activation is still gated on its actual result and shared-host verification.

Operator approved the new dedicated stack/IAM scope, encrypted seven-day backup retention and publication of the existing public learning site. The notification address is retained privately, not in this report. These approvals do not count as delivered email or successful deployment.

No new VM, paid-tier upgrade, public inference listener, database migration, unrelated workload restart, or live-database restore is authorized by this release.
