# First-visit walkthrough release — 2026-09-08

**Live on the private OCI website. Gateway cutover: 23:28:14 UTC, September 8, 2026.** Open `/assistant#system`, or select **How it works** from the dashboard navigation. The public Sites academy is unchanged and does not host this private assistant.

Code: [`69aa58427d745e83f7cdb961e118b3bc465f0ecc`](https://github.com/sivalinb/llm-serving-observatory/commit/69aa58427d745e83f7cdb961e118b3bc465f0ecc). [Beginner instructions](../docs/using-the-service.md).

## What a new user can learn

Seven selectable steps explain personal keys and invitations, the account-scoped workspace, authentication versus authorization, useful questions, search versus AI, request receipts and dashboard permissions. Animated diagrams show the credential check, request path, timing and overlapping token subsets. Examples fill the existing question box without submitting it.

The guide starts in manual mode. Optional playback advances every 12 seconds, stops at the end and pauses on navigation, hidden pages and leaving the viewport. Previous/Next, direct step links and keyboard controls remain available. Reduced-motion preferences disable animation/playback. All explanatory content remains readable without the guide script. No guide action handles credentials, creates an account, changes permissions or generates model traffic.

## Verification

- **99 Python tests and 34 Node tests passed locally**, plus Ruff, JavaScript syntax, static export and whitespace checks. Two pre-existing test-library deprecation warnings remain.
- [CI run 34289932816](https://github.com/sivalinb/llm-serving-observatory/actions/runs/34289932816) passed all four jobs: tests/integration, Terraform validation without apply, real CPU shared, and real CPU full. CI inference is runner evidence, not a new OCI benchmark.
- Automated checks cover the guide controller, bounded timers, reduced motion, example retrieval, markup/link wiring, HTTP assets and authentication/public-export boundaries. Browser interaction, screenshots and visual-rendering QA were not performed.
- The deployed assistant route returned **HTTP 200 through the private tunnel**. The four served assets exactly matched the committed files by SHA-256.
- The actual shared-runtime checker passed resource ceilings, health/restarts, network/port isolation, disabled lab routes and authentication boundaries.
- The dashboard smoke passed with **58 catalog entries, 93 chart points, two healthy targets, three evaluated rules and five retained request records**. Its temporary operator grant and key were revoked afterward. The deployment and dashboard checks made **zero model calls**; retained requests were not generated as demonstration telemetry.

## Exact deployment boundary

The clean OCI checkout was fast-forwarded to the tested code. An online SQLite backup was created at a new private filename on the existing data volume; this is not off-host recovery. Existing accounts, key hashes and operator grants were compared before/after cutover and were unchanged. No schema migration or database replacement occurred.

Only `assistant.html`, `observability.html`, `guide.css` and `guide.js` were overlaid on the existing gateway image. The build used the local base, `--network=none`, `--pull=false` and a 42.02 kB static context: no dependency installation, model download or full-stack build. Only gateway was recreated, with `--no-deps --no-build --wait`.

| Deployment evidence | Verified value |
|---|---|
| Running gateway image | `sha256:9c4be050e4fdece3c8993c3cc4aca7850ca4fc9c90d96a4ab96f9e2b911bb4a4` |
| Gateway start | `2026-09-08T23:28:14.588014618Z` |
| Retained rollback image | `observatory-shared-gateway:before-guide-20260908` |
| Other containers | All pre-existing non-gateway container IDs unchanged |
| Runtime configuration | Environment, mounts, network memberships and CPU/RAM/swap/security limits unchanged |
| Existing access | Account, key and operator state preserved across deployment |
| Public hosting | No Sites publication, public ingress, firewall or cloud-capacity change |

The gateway still uses 0.25 CPU / 256 MiB; the model 0.5 CPU / 2,560 MiB; Prometheus 0.25 CPU / 256 MiB. No inference backend, authentication logic or model configuration changed. Gateway process counters reset at restart; retained Prometheus history and request receipts have separate lifetimes.

Three read-only samples from **23:29:22–23:29:52 UTC** found all three containers healthy, with zero restarts, cgroup swap and memory-limit/OOM events. The incumbent health endpoint passed in each sample. Host available RAM stayed above 5.84 GiB. Existing allocated host swap remained **75,055,104 bytes (71.58 MiB)**; `pswpin`/`pswpout` counters did not change during this short window. This is a finite post-update observation, not a fresh-install zero-swap pass, load test or sustained-capacity claim. Earlier memory-incident and paging findings remain documented in the [initial dashboard release](observability-release.md).

The approved private Bastion connection is time-limited. Renew private access after expiry; the OCI service itself continues running. No credential or SSH private key is stored in this report or repository.
