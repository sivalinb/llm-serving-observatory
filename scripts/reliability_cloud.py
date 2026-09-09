"""OCI Cloud Shell operator workflow. Explicit actions; never auto-apply a plan.

Uses the existing OCI CLI login. Secrets only travel via stdin and remain in Vault.
Run from a reviewed checkout in a task directory; private state stays outside Git.
"""

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from observatory.reliability import canonical, private_directory, write_private  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ADDRESSES = {
    "oci_identity_compartment.lab", "oci_objectstorage_bucket.backups",
    "oci_objectstorage_object_lifecycle_policy.backups", "oci_identity_policy.expiry",
    "oci_kms_vault.lab", "oci_kms_key.secrets", "oci_apm_apm_domain.lab",
    "oci_ons_notification_topic.operator", "oci_ons_subscription.operator",
    "oci_identity_dynamic_group.runner", "oci_identity_policy.runner",
} | {f'oci_monitoring_alarm.lab["{name}"]' for name in (
    "service_unhealthy", "engine_scrape", "backup_missing", "backup_stale", "worker_missing", "safe_drill")}


def cli(*args, payload=None):
    command = ["oci", "--region", "us-phoenix-1", "--no-retry", *args]
    if payload is not None:
        command += ["--from-json", "file:///dev/stdin"]
    result = subprocess.run(command, input=canonical(payload) if payload is not None else None,
                            capture_output=True, timeout=90, check=False)
    if result.returncode:
        raise RuntimeError("OCI command failed; inspect the corresponding operation in the private console")
    return json.loads(result.stdout) if result.stdout.strip() else {"data": []}


def validate_plan(plan, existing=None):
    managed = [item for item in plan.get("resource_changes", []) if item.get("mode") == "managed"]
    if {item["address"] for item in managed} != ADDRESSES:
        raise ValueError("Plan differs from the dedicated resource allowlist")
    for item in managed:
        address, change = item["address"], item["change"]
        if existing is not None and address in existing:
            if (change["actions"] != ["no-op"] or change["before"].get("id") != existing[address]
                    or change["after"].get("id") != existing[address]):
                raise ValueError("Recovery must preserve every already-created resource unchanged")
        elif change["actions"] != ["create"]:
            raise ValueError("Only missing resources may be created; no changes or deletions")
    values = {item["address"]: item["change"]["after"] for item in managed}
    if values["oci_apm_apm_domain.lab"].get("is_free_tier") is not True:
        raise ValueError("APM must explicitly use Always Free")
    if values["oci_kms_vault.lab"].get("vault_type") != "DEFAULT":
        raise ValueError("A paid private vault is forbidden")
    if values["oci_kms_key.secrets"].get("protection_mode") != "SOFTWARE":
        raise ValueError("Only a software key was approved")
    bucket = values["oci_objectstorage_bucket.backups"]
    if bucket.get("access_type") != "NoPublicAccess" or bucket.get("storage_tier") != "Standard":
        raise ValueError("Backup bucket must be private Standard storage")
    return [{"address": item["address"], "actions": item["change"]["actions"]} for item in managed]


def state_ids(tf):
    result = {}
    for resource in tf.get("resources", []):
        if resource.get("mode") != "managed":
            continue
        for instance in resource.get("instances", []):
            address = resource["type"] + "." + resource["name"]
            if "index_key" in instance:
                address += "[" + json.dumps(instance["index_key"]) + "]"
            if address not in ADDRESSES or instance.get("status") == "tainted":
                raise ValueError("Unexpected or tainted resource requires manual investigation")
            result[address] = instance["attributes"]["id"]
    return result


def read_private(path):
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("State must be a private regular file")
    return json.loads(path.read_bytes())


def bootstrap(support, directory):
    compartment = support["compartment_id"]
    existing = cli("vault", "secret", "list", "--compartment-id", compartment, "--all")["data"]
    by_name = {item["secret-name"]: item for item in existing}
    ids = {}
    for name in ("observatory-backup-key", "observatory-apm-upload-key"):
        if name in by_name:
            item = by_name[name]
            if item["vault-id"] != support["vault_id"] or item["lifecycle-state"] != "ACTIVE":
                raise ValueError("Existing secret is not the expected active dedicated resource")
            ids[name] = item["id"]
            continue
        if name == "observatory-backup-key":
            content = secrets.token_bytes(32)
        else:
            keys = cli("apm-control-plane", "data-key", "list", "--apm-domain-id",
                       support["apm_domain_id"], "--data-key-type", "PRIVATE", "--all")["data"]
            if not keys:
                raise ValueError("No private APM upload key exists")
            content = keys[0]["value"].encode("ascii")
        value = cli("vault", "secret", "create-base64", payload={
            "compartmentId": compartment, "vaultId": support["vault_id"],
            "keyId": support["vault_key_id"], "secretName": name,
            "secretContentContent": base64.b64encode(content).decode(),
        })["data"]
        ids[name] = value["id"]
    config = {key: support[key] for key in ("region", "namespace", "bucket", "compartment_id")}
    config.update(backup_secret_id=ids["observatory-backup-key"], apm_secret_id=ids["observatory-apm-upload-key"],
                  database="/source/assistant.sqlite", state_directory="/private/state")
    write_private(directory / "config.json", canonical(config))
    return {"secret_ids": ids, "configuration_written": True, "secret_values_written": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("action", choices=("create-stack", "plan", "review", "review-resume", "apply-reviewed", "job", "outputs", "bootstrap", "drift"))
    parser.add_argument("--instance")
    parser.add_argument("--suffix")
    parser.add_argument("--email")
    args = parser.parse_args()
    directory = private_directory(args.state.resolve())
    state_path = directory / "operator.json"
    state = read_private(state_path) if state_path.exists() else {}
    if args.action == "create-stack":
        if state or not args.email or not args.instance or not args.suffix:
            raise ValueError("Use a new state directory and explicit approved instance, suffix and email")
        if not re.fullmatch(r"[a-z0-9-]{3,24}", args.suffix):
            raise ValueError("Invalid suffix")
        archive = directory / "support.zip"
        with zipfile.ZipFile(archive, "x", zipfile.ZIP_DEFLATED) as bundle:
            for name in ("main.tf", ".terraform.lock.hcl"):
                bundle.write(ROOT / "infra/reliability" / name, name)
        created = cli("resource-manager", "stack", "create", payload={
            "compartmentId": os.environ["OCI_TENANCY"], "configSource": str(archive),
            "displayName": "observatory-reliability", "terraformVersion": "1.5.x",
            "variables": {"tenancy_id": os.environ["OCI_TENANCY"], "existing_instance_id": args.instance,
                          "bucket_suffix": args.suffix, "notification_email": args.email},
        })["data"]
        state = {"stack_id": created["id"]}
        result = state
    elif args.action == "plan":
        if state.get("job_id"):
            prior = cli("resource-manager", "job", "get", "--job-id", state["job_id"])["data"]
            if prior["lifecycle-state"] in {"ACCEPTED", "IN_PROGRESS", "CANCELING"}:
                raise ValueError("Wait for the existing job before creating another plan")
            if prior["operation"] == "APPLY" and prior["lifecycle-state"] == "FAILED":
                state["recovery_apply_id"] = prior["id"]
        state.pop("reviewed_sha256", None)
        state.pop("reviewed_existing", None)
        job = cli("resource-manager", "job", "create-plan-job", "--stack-id", state["stack_id"])["data"]
        state["plan_id"] = state["job_id"] = job["id"]
        result = {"job_id": job["id"], "state": job["lifecycle-state"]}
    elif args.action in {"review", "review-resume", "apply-reviewed"}:
        plan = cli("resource-manager", "job", "get-job-tf-plan", "--job-id", state["plan_id"],
                   "--tf-plan-format", "JSON", "--file", "-")
        existing = state.get("reviewed_existing") if args.action == "apply-reviewed" else None
        if args.action == "review-resume":
            failed = cli("resource-manager", "job", "get", "--job-id", state["recovery_apply_id"])["data"]
            if failed["operation"] != "APPLY" or failed["lifecycle-state"] != "FAILED" or failed["stack-id"] != state["stack_id"]:
                raise ValueError("Recovery must refer to this stack's failed apply")
            tf = cli("resource-manager", "job", "get-job-tf-state", "--job-id", failed["id"], "--file", "-")
            existing = state_ids(tf)
            if not existing:
                raise ValueError("No partial resources to reconcile; use the initial review")
        changes = validate_plan(plan, existing)
        digest = hashlib.sha256(canonical(plan)).hexdigest()
        if args.action in {"review", "review-resume"}:
            state["reviewed_sha256"] = digest
            state["reviewed_existing"] = existing
            result = {"changes": changes, "plan_sha256": digest, "apply_requires_separate_action": True}
        else:
            if state.get("reviewed_sha256") != digest:
                raise ValueError("Plan must match the independently reviewed result")
            job = cli("resource-manager", "job", "create-apply-job", "--stack-id", state["stack_id"],
                      "--execution-plan-strategy", "FROM_PLAN_JOB_ID", "--execution-plan-job-id", state["plan_id"])["data"]
            state["job_id"] = job["id"]
            result = {"job_id": job["id"], "state": job["lifecycle-state"]}
    elif args.action == "job":
        job = cli("resource-manager", "job", "get", "--job-id", state["job_id"])["data"]
        result = {"job_id": job["id"], "state": job["lifecycle-state"]}
    elif args.action == "outputs":
        job = cli("resource-manager", "job", "get", "--job-id", state["job_id"])["data"]
        if job["lifecycle-state"] != "SUCCEEDED" or job["operation"] != "APPLY":
            raise ValueError("Require a successful apply before extracting outputs")
        tf = cli("resource-manager", "job", "get-job-tf-state", "--job-id", state["job_id"], "--file", "-")
        state["support"] = tf["outputs"]["support"]["value"]
        result = state["support"]  # IDs/endpoints only. No Terraform state or email printed.
    elif args.action == "bootstrap":
        result = bootstrap(state["support"], directory)
    else:
        result = cli("resource-manager", "stack", "detect-drift", "--stack-id", state["stack_id"])
        result = {"drift_detection_requested": True, "verify_in_resource_manager": True}
    write_private(state_path, canonical(state), replace=True)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
