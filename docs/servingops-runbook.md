# ServingOps Cloud: Phoenix Free Tier beta

An invite-only documentation assistant that exercises a real inference path. It is a **single-node portfolio beta**, not an HA platform or a promise of free capacity. The simulator remains an independent operator lab.

![Service architecture](../observatory/static/service-architecture.svg)

## What a visitor can do

1. Redeem an expiring, single-use invitation and save the personal key returned once.
2. Ask about TTFT, prefill/decode, KV transfer, tokens, CPU/RAM or GPU/HBM.
3. Search approved project documentation, without invoking a model.
4. If the CPU backend is enabled, receive real streamed model output with retrieved source references.
5. Inspect their own timing/token receipt and recent request metadata. Rotate their key or delete metadata.

The 1.5B model is intentionally small. Its answers may be incomplete or wrong. The citation check detects missing or unknown `[S#]` IDs; it **does not verify factual support**. Do not use this assistant for high-stakes decisions. There are no private document uploads, tool calls or arbitrary URL fetching.

## Architecture decisions

| Decision | Reason and tradeoff |
|---|---|
| Phoenix A1 CPU VM | Matches the user's Free Tier constraint; much slower than GPU inference |
| Qwen2.5-1.5B-Instruct Q4_K_M + llama.cpp | Small real model, Apache-2.0 weights, ARM64 support; limited answer quality |
| Combined serving | Real CPU prefill/decode in one engine; disaggregation is still simulated in the lab |
| Curated lexical retrieval | No vector DB, embedding service or paid API; weaker recall for paraphrases |
| SQLite WAL + one gateway worker | Atomic admission with minimal infrastructure; no horizontal scaling or HA |
| One answer at a time, immediate 429 when busy | Protects a 2-OCPU host; no hidden unbounded queue |
| Caddy allowlist + private operations | Public users never reach shared lab history, metrics, docs or model endpoints |
| No content persistence | Reduced data exposure; no conversation replay or resumable response storage |

## Zero-paid-service deployment gate

Oracle currently documents A1 Always Free allowances of **1,500 OCPU-hours and 9,000 GB-hours/month**, equivalent to 2 OCPUs / 12 GB for an Always Free tenancy. Compute must be in the home region, available capacity is not guaranteed, and idle instances may be reclaimed. Verify the **Always Free eligible** labels and aggregate resources in your own tenancy before applying Terraform. [Oracle Always Free documentation](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

The example targets `us-phoenix-1`. PHX must also be your home region. The Terraform uses a 50-GB boot volume; include existing volumes, backups and Object Storage use when checking free limits. Do not upgrade the account, resize outside the allowance, switch to a paid shape, or provision GPU/OKE/managed inference as a capacity workaround. Budgets are alerts, **not hard spending stops**. [Oracle budget documentation](https://docs.oracle.com/en-us/iaas/Content/Billing/Concepts/budgetsoverview.htm).

This release does not enable OCI Generative AI. The older lab's upstream adapter remains available for separately authorized experiments. Model downloads and GitHub Actions are not OCI inference calls, but network and hosting usage still have service-specific allowances. Review those as well.

### Before provisioning

- Configure OCI authentication locally using Oracle's supported setup; do not paste private keys or credentials into chat or Git.
- Confirm home region, compartment, available A1 capacity and *existing aggregate* compute/storage allocations in the Console.
- Choose an official Always Free eligible Ubuntu ARM image and availability domain. Copy their actual identifiers into your ignored `terraform.tfvars`.
- Keep `create_budget=false`. An optional advisory budget does not enforce a zero-dollar ceiling.
- Keep `public_https=false` for the first SSH-only validation. Follow [OCI deployment](oci-deployment.md) for Terraform plan review and VM creation.

No live OCI tenancy was accessed during implementation. These checks require the account owner's authenticated environment.

## Start the real CPU service

Run from the repository root on the Ubuntu ARM VM after Docker Engine and Compose are installed. The existing `scripts/deploy.sh` copies the code and starts the lab; execute the CPU commands below on that VM to add the real service. Local Python-only previews default to search-only mode.

```bash
python3 scripts/download_model.py
docker compose -f compose.yaml -f compose.cpu.yaml up -d --build --wait --wait-timeout 300
docker compose exec -T gateway python -m observatory.admin invite --requests 20 --tokens 100000 --hours 24
```

The downloader pins the official Hugging Face repository revision, filename, 1,117,320,736-byte size and SHA-256. Existing nonmatching files are not overwritten. The Compose image is pinned by its multi-platform digest. The model file is ignored by Git. [Official model and license](https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF), [llama.cpp Docker documentation](https://github.com/ggml-org/llama.cpp/blob/master/docs/docker.md).

From your laptop, open the existing SSH tunnel to port 8000, then visit `http://localhost:8000/assistant`. Redeem the printed invitation; save the new key securely. Do not publish invitation output or reuse a CI invitation. Use a fresh CLI invite for each visitor.

Default runtime bounds:

| Resource | Bound |
|---|---|
| CPU model container | 1.5 CPU cores, 4 GiB memory cap; 2 inference threads |
| Context / output | 4,096 context tokens in engine; 256 maximum requested output tokens |
| Questions | 800 characters; conservative byte-plus-framing input admission estimate |
| In-flight answers | 1 globally, exactly one gateway worker |
| User limits | 20 admitted requests / 100,000 quota tokens per UTC day by default |
| Service limit | 1,000,000 quota tokens per UTC calendar month by default |
| Request rate | At most 6 admitted requests per user per minute |
| Model deadline | 90 seconds by default; set `ASSISTANT_DEADLINE_SECONDS` before starting |
| Gateway / workers | 512 MiB / 256 MiB each |
| Optional telemetry stack | Approximately 1.7 GiB aggregate configured memory caps |

Memory caps are limits, not benchmarked peak requirements. Inspect `docker stats --no-stream` under real load and leave RAM for the OS/page cache. The 4-GiB model cap includes weights, KV cache and runtime allocations; CPU inference uses normal host RAM, **not HBM**. This deployment does not simulate GPU utilization or label CPU RAM as GPU memory.

## Add monitoring

Set a strong `GRAFANA_PASSWORD` in `.env`, then:

```bash
docker compose -f compose.yaml -f compose.cpu.yaml -f compose.observability.yaml -f compose.cpu-observability.yaml up -d --build
```

Tunnel localhost ports 3000 and 9090 over SSH. The **ServingOps / Real traffic beta** dashboard is separate from the five lab dashboards. It shows request outcomes, admission denials, TTFT, E2E, tokens, citation ID checks, active requests and measured gateway/lab CPU/RSS. The model's own `/metrics` endpoint is scraped through private service discovery; inspect its engine metrics in Prometheus.

| Observation | Exact meaning / limit |
|---|---|
| `assistant_ttft_seconds` | Gateway question processing (retrieval start, after authentication) to first visible content; excludes browser network time |
| `assistant_request_seconds` | Same start to terminal completion/cancellation |
| `assistant_chunk_gap_seconds` | Gap between visible chunks; **not** token-level ITL or decode TPOT |
| Input / output | Model server-reported usage; input includes instructions and reference excerpts |
| Cached / reasoning | Provider-reported subsets; missing values stay null, never inferred from chunks |
| Reserved quota tokens | UTF-8 bytes + framing allowance + output allowance; not actual tokenizer usage |
| Prefill / decode internals | Engine metrics, where available; gateway cannot infer exact internal phase durations |
| KV transfer | None in the real combined CPU service; modeled separately in the lab |
| CPU / RSS / cgroup | Existing per-process sampler for gateway and lab workers, not the model container |
| Model container memory | Measure with `docker stats`; not attributed to individual requests or mislabeled as gateway RSS |
| GPU / HBM | Unavailable on A1; hardware lab estimates remain explicitly analytical |

The request record includes retrieval duration, a trace ID and the corpus version. Tempo receives request/model spans without prompt, answer, user name or key attributes. The public status endpoint reports *configuration*, not successful model readiness or fabricated uptime. Local `/healthz` is application liveness, not end-to-end inference health.

Provisional beta targets: p95 TTFT under 30 seconds and completed-request error rate under 5%, measured over meaningful real traffic. These are targets to validate, not achieved SLAs. Prometheus rules flag repeated failures, slow first content and an unavailable configured model. Alert delivery still requires a receiver; the repository does not automatically notify anyone.

## Public HTTPS

After private validation, point an existing DNS name at the VM. Set `DOMAIN`, `ACME_EMAIL`, `LAB_API_KEY`, `WORKER_TOKEN` and `GRAFANA_PASSWORD` in the VM's ignored `.env`. Use independently generated strong secrets. Enable Terraform's `public_https` only after reviewing the change. No domain purchase is performed by this project.

```bash
docker compose -f compose.yaml -f compose.cpu.yaml -f compose.observability.yaml -f compose.cpu-observability.yaml -f compose.public.yaml up -d --build
python3 scripts/check_public.py --url https://YOUR_DOMAIN
```

Caddy redirects `/` to `/assistant`, permits the assistant API/assets, and denies everything else. Ports 8000, 3000 and 9090 remain loopback-bound. The model has **no host port**. Do not change the gateway bind address or expose Docker sockets. This is an invite-only beta, not a hardened anonymous high-volume endpoint; volumetric DDoS protection, an edge WAF, organization SSO and multi-region failover are outside this release.

## Admission, cancellation and privacy contract

SQLite `BEGIN IMMEDIATE` protects reservation checks across connections. A unique `(user, Idempotency-Key)` prevents duplicate inference; a reused key returns 409 even with different content. It does not replay answers because answers are not stored. Unknown, failed, cancelled or abandoned work retains its full token reservation. Successful complete usage replaces the estimate with server-reported total tokens. An estimate is not a universal tokenizer bound: if reported usage exceeds it, the ledger charges actual usage and later requests are blocked by quotas. This is a **capacity control**, not a hard dollar billing guarantee.

Disconnect closes the upstream stream and releases the active admission. Work already done is not refunded. Reservations older than twice the configured deadline are marked abandoned on subsequent admission. Run only one gateway worker and do not share the SQLite file across replicated hosts. Revocation blocks new requests; an already admitted request may finish.

Only identity, hashed secrets and request metadata are persisted. High-entropy random keys/invites use SHA-256; these are not human passwords. Metadata contains status, counts, latencies, source IDs and trace IDs, not question/answer content. The browser holds the key and content in memory, not localStorage or cookies. Page reload signs out. Model logging is disabled in the CPU profile; do not enable verbose request/body logging on the edge, gateway or engine.

History APIs return only the caller's last seven days. Deletion clears request metadata but retains the minimal quota/idempotency ledger. Old metadata/ledger rows are physically pruned on the next admitted-request cleanup (7/90 days respectively); an idle database and existing backups may retain older bytes until an operator cleans/replaces them. SQLite deletion is not secure erasure. Display names and hashed keys persist until operator-managed account removal. This is not a compliance certification or a tenant-private document system.

## Operator runbook

**Invite or revoke:** Use the private CLI above. To revoke every key for a known user ID:

```bash
docker compose exec -T gateway python -m observatory.admin revoke USER_ID
```

**Capacity/latency incident:** Inspect `docker stats --no-stream`, model health and the real-service dashboard. Stop accepting AI requests by restarting the gateway with the base configuration (omit `compose.cpu.yaml`), leaving search available. Stop the model container if necessary. Do not automatically retry failed inference; it may already have consumed compute. Avoid running lab benchmarks concurrently on the small VM.

**Backup:** SQLite's online backup captures a consistent snapshot including WAL. The command refuses to overwrite an existing destination:

```bash
docker compose exec -T gateway python -m observatory.admin backup /app/data/assistant-backup-2026-09-07.sqlite
```

Choose a new filename each time. Copy the file off the VM over SSH to protected storage; an on-VM backup does not protect against VM loss. It contains identity and credential hashes and needs access controls. Verify free storage/backup allowances before adding cloud copies. Keep a documented retention policy and rehearse restore with an isolated copy. Restoring an old identity database can restore old keys/revocations and old quota balances: revoke/reissue keys and review quotas before reopening traffic.

**Restore:** Stop gateway writes; preserve the current database and its WAL/SHM files together as a recoverable set. Verify the backup's `PRAGMA integrity_check` returns `ok`. Restore to a **new** path, preserve owner UID 10001, point `ASSISTANT_DB` at it, and validate privately before reopening. Never overwrite a live WAL database or copy only its main file as a backup.

**Release / rollback:** Record the tested Git commit and current image IDs, take an online backup, build/test the new revision in a separate checkout, and restart gracefully. Keep the previous images/checkouts. To roll back, run the prior tested Compose/image revision against a schema-compatible database or an explicitly rehearsed restore. Do not use `git reset --hard` on a working checkout or delete persistent volumes. Pin updates should repeat the real-model CI smoke.

**Validation:** `pytest -q` covers auth, isolation, quotas, atomic admission, stream limits, cancellation, deadlines and backups. CI separately runs the pinned real model and a real answer through the public API, plus public-edge boundary checks and the full existing observability smoke. Its CPU results are GitHub-runner evidence, **not Phoenix benchmarks**. `scripts/evaluate_retrieval.py` measures retrieval recall on a tiny transparent teaching fixture; it is not model answer quality or generalization evidence.

## Portfolio demonstration (five minutes)

1. Explain why Free Tier changed the architecture: no paid model API, no GPU, one CPU request at a time.
2. Redeem an invite and ask about CPU RAM versus HBM. Inspect retrieved excerpts and compare the model's claims with the source links.
3. Show the real TTFT/token receipt; contrast unknown reasoning details with the lab's explicitly simulated counts.
4. Start overlapping requests from two users: show a bounded 429 and isolated history, then cancellation recovery.
5. Correlate latency with CPU pressure in Grafana, explain why gateway RSS is not model RAM, and open the request trace in Tempo.
6. Show CI evidence, checksum/image pins, an online backup, and the explicit limitations. Future milestones are measured A1 load tests, human answer evaluation, an authenticated model-container exporter, and only then shared storage/replicas if demand justifies cost.
