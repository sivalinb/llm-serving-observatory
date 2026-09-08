# OCI deployment

**Existing shared Oracle Linux A1 host:** use the [shared-host pilot runbook](oci-shared-host.md). Do not apply this guide's Ubuntu bootstrap, Terraform or full-stack deploy script to a VM running another application. The slim profile was deployed privately on Phoenix ARM64 on September 8; see [actual pilot evidence](../reports/oci-private-pilot.md). This does not validate the separate new-VM/full-stack procedure below.

For the current **Phoenix Free Tier assistant**, follow the [ServingOps service runbook](servingops-runbook.md). This guide covers shared infrastructure, the private learning lab and optional aggregate exports. The public routes are `/` (animated introduction) and `/assistant`; `/lab` and operations endpoints remain private.

## CPU lab

The long-lived deployment is an Ubuntu ARM VM, three lightweight application containers, and optionally the local observability stack. The lab serves its own HTML/CSS/JavaScript; no separate web hosting service is needed. Resource estimates are not guarantees: inspect the Always Free label and your **aggregate** current usage in the OCI console before applying the configuration.

Prerequisites: an active OCI tenancy, home-region A1 capacity, an existing compartment, an SSH public key, your current public IPv4 address, a region-specific official Ubuntu 24.04 ARM image OCID, Terraform 1.6+, and a configured OCI API profile. Do not place the OCI private key or profile in this repository. Terraform's OCI provider can use your normal OCI CLI configuration or supported environment variables.

```bash
cp infra/oci/terraform.tfvars.example infra/oci/terraform.tfvars
# Fill the region, compartment, availability domain, image, public key, and admin /32 CIDR.
terraform -chdir=infra/oci init
terraform -chdir=infra/oci plan -out=reviewed.tfplan
terraform -chdir=infra/oci apply reviewed.tfplan
terraform -chdir=infra/oci output
```

The plan includes the VM, 50 GB boot volume, VCN/subnet, internet gateway, restricted SSH access, and a private Object Storage bucket. The optional budget requires `create_budget=true`, the tenancy OCID, and notification email. Review the plan against your tenancy limits. A budget sends advisory alerts and **does not stop spending**.

After provisioning:

```bash
export OCI_HOST=YOUR_VM_IP
bash scripts/deploy.sh
ssh -L 8000:127.0.0.1:8000 -L 3000:127.0.0.1:3000 ubuntu@YOUR_VM_IP
```

The deployment script waits for cloud-init, copies source using rsync, and builds/starts the CPU services. It excludes `.env`, credentials, state files, local model files and runtime data. Configure the remote `.env` yourself through SSH before adding the observability or public profile. It does not delete files or data already on the host.

On the VM, inside `~/llm-serving-observatory`:

```bash
cp .env.example .env
# Edit .env: GRAFANA_PASSWORD, and unique LAB_API_KEY / WORKER_TOKEN if needed.
docker compose -f compose.yaml -f compose.observability.yaml up -d --build
docker compose ps
```

Open `http://localhost:8000` for the homepage, `http://localhost:8000/lab` for experiments and `http://localhost:3000` for Grafana on the machine with the SSH tunnel. Re-run `bash scripts/deploy.sh` after source changes; then reapply all overlays you use. The script starts the base lab configuration, not the complete real-assistant deployment.

## Public HTTPS portfolio

Use a domain you control, with its DNS A record pointing to the VM. Set `public_https=true` in Terraform and review/apply the ingress change. Set `DOMAIN`, `ACME_EMAIL`, and a strong `LAB_API_KEY` in the VM's `.env`, then:

```bash
docker compose -f compose.yaml -f compose.observability.yaml -f compose.public.yaml up -d --build
```

Caddy terminates TLS, supports streaming without proxy buffering, and permits only the homepage, assistant API and explicitly listed public assets. It blocks `/lab`, lab experiment/history APIs, `/metrics` and API schema pages. The lab key protects experiments reached through the local/SSH connection; it does not grant public access through Caddy. Keep engine and worker ports private. If the OS firewall blocks ports 80/443, add only those ports using the image's supported firewall tooling; do not flush firewall rules.

The command above exposes the explanatory homepage and search-only assistant. Invited assistant users have personal hashed keys, isolated metadata history, quotas and bounded admission; these are separate from the lab's shared key and experiment store. To enable real CPU answers, first download the pinned model and add the CPU overlays:

```bash
python3 scripts/download_model.py
docker compose -f compose.yaml -f compose.cpu.yaml -f compose.observability.yaml -f compose.cpu-observability.yaml -f compose.public.yaml up -d --build --wait --wait-timeout 300
docker compose exec -T gateway python -m observatory.admin invite
python3 scripts/check_public.py --url https://YOUR_DOMAIN
```

The CPU profile does not call a paid managed inference API. Follow the [service runbook](servingops-runbook.md) for key management, capacity settings, privacy, backups and rollback. This remains a single-node invite-only beta, not an anonymous production service or a guarantee of free tenancy eligibility.

## Object Storage, Monitoring and Autonomous Database

Install optional dependencies with `pip install -e '.[oci]'`. `scripts/export_oci.py` uses the ordinary OCI SDK profile outside the checkout. It sends aggregate benchmark fields only, excluding prompts, responses and per-request trace records.

```bash
python scripts/export_oci.py experiment.json --bucket YOUR_BUCKET --compartment YOUR_COMPARTMENT
```

For an **existing** Autonomous Database, configure `ADB_USER`, `ADB_PASSWORD`, and `ADB_DSN` as environment variables. With an mTLS wallet, also set `ADB_WALLET_DIR` and `ADB_WALLET_PASSWORD`; store the wallet outside Git. Use `--adb` to create/update the `lab_experiments` table. Provisioning or upgrading a database is not part of the default Terraform plan.

OCI Monitoring metrics use namespace `llm_observatory` and bounded `mode`/`source` dimensions. They are aggregate experiment snapshots, not continuous engine telemetry. Optional OCI APM ingestion must be configured using your domain's upload endpoint and data key according to Oracle's current documentation.

## Cost and cleanup

- Keep the CPU lab within the Always Free resources shown in your tenancy; eligibility and idle-instance reclamation policies can vary over time.
- GPU access requires quota, regional capacity, compatible drivers and billing eligibility. Trial credits do not guarantee GPU provisioning.
- Stop or terminate paid GPU instances after experiments using the OCI console/CLI, checking the shape's billing behavior. Killing an inference process is not sufficient.
- Object storage, boot volumes, retained disks and other resources may remain billable after compute stops. Check Cost Analysis.
- Export important benchmark reports before cleanup. `docker compose down` preserves named data volumes; adding `--volumes` would delete them.
- To retire the cloud lab, inspect `terraform plan -destroy` and use Terraform's normal confirmation flow. This may remove the VM and boot disk. The private report bucket must be handled explicitly if nonempty; `force_destroy` is not enabled.

No OCI resources were provisioned during local implementation. Terraform validation checks configuration/schema, not your credentials, quota, regional image availability or cloud-init completion.
