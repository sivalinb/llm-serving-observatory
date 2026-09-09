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

Initial local test run: **124 Python tests passed**, two new flow-controller tests passed; existing test warnings are upstream FastAPI/Starlette deprecations. Ruff passed. Local Terraform provider schema validation succeeded with OCI provider 6.37.0. This is not proof of deployed OCI IAM/service behavior. Additional workflow and export checks are run before release.

Read-only OCI inventory confirmed Phoenix, an existing Free Tier trial account, one existing shared VM, one incumbent bucket, no reliability stack in resource-search results. Resource search can lag; actual service limits and headroom must be rechecked before apply. No incumbent infrastructure was changed by these checks. The initial Cloud Shell connection interrupted; recovery is being attempted through a fresh authenticated console tab.

Operator approved the new dedicated stack/IAM scope, encrypted seven-day backup retention and publication of the existing public learning site. The notification address is retained privately, not in this report. These approvals do not count as delivered email or successful deployment.

No new VM, paid-tier upgrade, public inference listener, database migration, unrelated workload restart, or live-database restore is authorized by this release.
