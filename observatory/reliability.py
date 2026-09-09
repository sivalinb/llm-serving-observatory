"""Host-invoked reliability worker; never imported by the web application's routes.

No personal OCI API keys, model calls, live restore, or automatic object deletion.
The SDK uses the narrowly authorized instance identity. Keep its config/state private.
"""

import argparse
import base64
import fcntl
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

MAX_SNAPSHOT = 8 * 1024**2
MAX_ENVELOPE = 12 * 1024**2
MAX_OBJECTS = 14
TABLES = ("users", "keys", "invites", "ledger", "operator_grants", "service_events")
NAMESPACE = "observatory_reliability"
METRICS = {"ServiceHealthy", "EngineScrapeHealthy", "BackupAgeSeconds", "BackupVerified",
           "HostAvailableMemoryBytes", "ReliabilityDrill"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def private_directory(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError("Private directory must not be a symlink")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.stat().st_mode & 0o077:
        raise ValueError("Private directory must be mode 0700")
    return path


def write_private(path, data, replace=False):
    path = Path(path)
    private_directory(path.parent)
    if path.is_symlink() or (path.exists() and not replace):
        raise ValueError("Refusing to overwrite the destination")
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if replace:
            os.replace(name, path)
        else:
            os.link(name, path)  # Atomic no-overwrite publish, including races.
        return path
    finally:
        if os.path.exists(name):
            os.unlink(name)


def load_config(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError("Configuration must be a private regular file")
    value = json.loads(path.read_bytes())
    required = {"region", "namespace", "bucket", "compartment_id", "backup_secret_id",
                "apm_secret_id", "database", "state_directory"}
    if set(value) != required or value["region"] != "us-phoenix-1":
        raise ValueError("Unexpected configuration fields or region")
    if not re.fullmatch(r"observatory-reliability-[a-z0-9-]{3,40}", value["bucket"]):
        raise ValueError("Not a dedicated reliability bucket")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{3,64}", value["namespace"]):
        raise ValueError("Invalid namespace")
    for field, kind in (("compartment_id", "compartment"), ("backup_secret_id", "vaultsecret"),
                        ("apm_secret_id", "vaultsecret")):
        if not re.fullmatch(r"ocid1\." + kind + r"\.[a-zA-Z0-9._-]+", value[field]):
            raise ValueError("Invalid resource identifier")
    for field in ("database", "state_directory"):
        if not Path(value[field]).is_absolute():
            raise ValueError("Use explicit absolute paths")
    return value


@contextmanager
def locked(directory):
    directory = private_directory(directory)
    lock = directory / "worker.lock"
    fd = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield directory
    finally:
        os.close(fd)


def database_counts(path):
    with sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity verification failed")
        return {table: db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                for table in TABLES}


def snapshot(source, destination, deadline=20):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file():
        raise ValueError("Source must be an existing regular database")
    start = time.monotonic()
    write_private(destination, b"")
    with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=5) as db:
        pagesize = db.execute("PRAGMA page_size").fetchone()[0]
        if pagesize * db.execute("PRAGMA page_count").fetchone()[0] > MAX_SNAPSHOT:
            raise ValueError("Snapshot exceeds the learning budget")

        def progress(status, remaining, total):
            if total * pagesize > MAX_SNAPSHOT or time.monotonic() - start > deadline:
                raise TimeoutError("Bounded snapshot did not complete")

        with sqlite3.connect(destination) as target:
            db.backup(target, pages=128, progress=progress, sleep=0.05)
    if not 0 < destination.stat().st_size <= MAX_SNAPSHOT:
        raise ValueError("Invalid snapshot size")
    return {"snapshot_at": int(time.time()), "size": destination.stat().st_size,
            "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            "counts": database_counts(destination)}


def seal(payload, key, header):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(key) != 32 or len(payload) > MAX_SNAPSHOT:
        raise ValueError("Invalid encryption key or payload size")
    nonce = os.urandom(12)
    return canonical({"header": header, "nonce": base64.b64encode(nonce).decode(),
                      "ciphertext": base64.b64encode(AESGCM(key).encrypt(
                          nonce, payload, canonical(header))).decode()})


def open_envelope(envelope, key, binding):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    if len(envelope) > MAX_ENVELOPE:
        raise ValueError("Envelope exceeds the learning budget")
    data = json.loads(envelope)
    if set(data) != {"header", "nonce", "ciphertext"}:
        raise ValueError("Unsupported envelope")
    header = data["header"]
    expected = {"format", "binding", "key_version", "snapshot_at", "size", "sha256", "counts"}
    if set(header) != expected or header["format"] != 1 or header["binding"] != binding:
        raise ValueError("Backup format or object binding mismatch")
    if type(header["key_version"]) is not int or not 1 <= header["key_version"] <= 10000:
        raise ValueError("Invalid secret version")
    if type(header["size"]) is not int or not 0 < header["size"] <= MAX_SNAPSHOT:
        raise ValueError("Invalid declared size")
    nonce = base64.b64decode(data["nonce"], validate=True)
    if len(key) != 32 or len(nonce) != 12:
        raise ValueError("Invalid key or nonce")
    payload = AESGCM(key).decrypt(nonce, base64.b64decode(data["ciphertext"], validate=True),
                                canonical(header))
    if len(payload) != header["size"] or hashlib.sha256(payload).hexdigest() != header["sha256"]:
        raise ValueError("Snapshot digest mismatch")
    return payload, header


class Cloud:
    def __init__(self, config):
        import oci

        self.oci, self.config = oci, config
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
        options = {"signer": signer, "timeout": (5, 20),
                   "retry_strategy": oci.retry.NoneRetryStrategy()}
        sdk_config = {"region": config["region"]}
        self.storage = oci.object_storage.ObjectStorageClient(sdk_config, **options)
        self.secrets = oci.secrets.SecretsClient(sdk_config, **options)
        self.monitoring = oci.monitoring.MonitoringClient(
            sdk_config, service_endpoint="https://telemetry-ingestion.us-phoenix-1.oraclecloud.com",
            **options)

    def secret(self, identifier, version=None):
        args = {"version_number": version} if version is not None else {"stage": "CURRENT"}
        bundle = self.secrets.get_secret_bundle(identifier, **args).data
        return base64.b64decode(bundle.secret_bundle_content.content, validate=True), bundle.version_number

    def capacity(self):
        response = self.storage.list_objects(self.config["namespace"], self.config["bucket"],
                                             prefix="backups/", limit=MAX_OBJECTS, fields="name,size")
        if response.data.next_start_with or len(response.data.objects) >= MAX_OBJECTS:
            raise ValueError("Backup object ceiling reached; review retention")
        if sum(obj.size for obj in response.data.objects) > MAX_OBJECTS * MAX_ENVELOPE:
            raise ValueError("Backup byte ceiling reached")

    def put(self, name, data):
        if len(data) > MAX_ENVELOPE:
            raise ValueError("Upload size exceeded")
        self.storage.put_object(self.config["namespace"], self.config["bucket"], name, data,
                                if_none_match="*", content_type="application/octet-stream")

    def get(self, name):
        response = self.storage.get_object(self.config["namespace"], self.config["bucket"], name)
        if int(response.headers.get("content-length", MAX_ENVELOPE + 1)) > MAX_ENVELOPE:
            response.data.raw.close()
            raise ValueError("Download size exceeded")
        try:
            content = response.data.raw.read(MAX_ENVELOPE + 1)
            if len(content) > MAX_ENVELOPE:
                raise ValueError("Download size exceeded")
            return content
        finally:
            response.data.raw.close()

    def publish(self, values, drill=False):
        models = self.oci.monitoring.models
        if not values or not set(values) <= METRICS:
            raise ValueError("Metric allowlist violation")
        if any(type(v) not in (float, int) or not math.isfinite(v) or v < 0 for v in values.values()):
            raise ValueError("Invalid metric value")
        metrics = [models.MetricDataDetails(
            namespace=NAMESPACE, compartment_id=self.config["compartment_id"], name=name,
            dimensions={"service": "servingops", "source": "drill" if drill else "measured"},
            datapoints=[models.Datapoint(timestamp=datetime.now(timezone.utc), value=value)],
        ) for name, value in values.items()]
        result = self.monitoring.post_metric_data(models.PostMetricDataDetails(metric_data=metrics))
        if result.data.failed_metrics_count:
            raise RuntimeError("Cloud rejected metric datapoints")


def restore(cloud, config, name, destination):
    if not re.fullmatch(r"backups/[0-9a-f]{32}\.obk", name):
        raise ValueError("Invalid backup object name")
    started = time.monotonic()
    envelope = cloud.get(name)
    if len(envelope) > MAX_ENVELOPE:
        raise ValueError("Download size exceeded")
    # Only the configured secret is queried, never an ID supplied by downloaded data.
    version = json.loads(envelope).get("header", {}).get("key_version")
    if type(version) is not int or not 1 <= version <= 10000:
        raise ValueError("Invalid key version")
    key, returned_version = cloud.secret(config["backup_secret_id"], version)
    if version != returned_version:
        raise ValueError("Secret version mismatch")
    payload, header = open_envelope(envelope, key, config["bucket"] + "/" + name)
    if Path(destination).resolve() == Path(config["database"]).resolve():
        raise ValueError("A drill must never replace the live database")
    write_private(destination, payload)
    if database_counts(destination) != header["counts"]:
        raise ValueError("Restored data verification failed")
    return {"restore_verified": True, "restore_seconds": round(time.monotonic() - started, 3),
            "snapshot_age_seconds": max(0, int(time.time()) - header["snapshot_at"]),
            "snapshot_at": header["snapshot_at"], "snapshot_bytes": header["size"],
            "snapshot_sha256": header["sha256"], "table_counts": header["counts"]}


def backup(cloud, config, directory):
    cloud.capacity()
    with tempfile.TemporaryDirectory(prefix="backup-", dir=directory) as work:
        source = Path(work) / "snapshot.sqlite"
        metadata = snapshot(config["database"], source)
        key, version = cloud.secret(config["backup_secret_id"])
        name = "backups/" + uuid.uuid4().hex + ".obk"
        header = {"format": 1, "binding": config["bucket"] + "/" + name,
                  "key_version": version, **metadata}
        body = seal(source.read_bytes(), key, header)
        cloud.put(name, body)
        result = restore(cloud, config, name, Path(work) / "restored.sqlite")
        result.update(object_name=name, verified_at=int(time.time()), key_version=version)
        write_private(Path(directory) / "latest-backup.json", canonical(result), replace=True)
        return result


def json_probe(url):
    # URLs are fixed by this program; no caller-supplied address or credential.
    with urlopen(url, timeout=5) as response:
        data = response.read(128 * 1024 + 1)
    if len(data) > 128 * 1024:
        raise ValueError("Probe response too large")
    return json.loads(data)


def measure(directory, gateway="http://gateway:8000", prometheus="http://prometheus:9090"):
    values = {"ServiceHealthy": 0, "EngineScrapeHealthy": 0, "BackupVerified": 0}
    try:
        health = json_probe(gateway + "/healthz")
        values["ServiceHealthy"] = int(health.get("status") == "ok" and health.get("profile") == "assistant-only")
    except Exception:
        pass  # Missing/unhealthy is measured failure, never invented success.
    try:
        result = json_probe(prometheus + "/api/v1/query?query=up%7Bjob%3D%22shared-model%22%7D")
        vector = result["data"]["result"]
        values["EngineScrapeHealthy"] = int(len(vector) == 1 and float(vector[0]["value"][1]) == 1)
    except Exception:
        pass
    state = Path(directory) / "latest-backup.json"
    if state.is_file() and not state.is_symlink():
        try:
            report = json.loads(state.read_bytes())
            timestamp = report["snapshot_at"]
            if report["restore_verified"] is True and type(timestamp) is int and 0 < timestamp <= time.time():
                values["BackupVerified"] = 1
                values["BackupAgeSeconds"] = int(time.time()) - timestamp
        except (KeyError, ValueError, TypeError):
            pass
    # /proc/meminfo in a container is host aggregate, not its cgroup allowance.
    memory = Path("/proc/meminfo")
    if memory.exists():
        rows = {line.split(":")[0]: line.split()[1] for line in memory.read_text().splitlines()}
        values["HostAvailableMemoryBytes"] = int(rows["MemAvailable"]) * 1024
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("backup", help="Snapshot, encrypt, upload, download and verify isolated restore")
    actions.add_parser("probe", help="Publish bounded health/freshness metrics; no model requests")
    drill = actions.add_parser("drill", help="Publish a separate synthetic alarm test signal")
    drill.add_argument("--value", type=int, choices=(0, 1), required=True)
    recovery = actions.add_parser("restore-check", help="Create a new isolated restore; never overwrite")
    recovery.add_argument("object_name")
    recovery.add_argument("destination")
    secret = actions.add_parser("prepare-trace-key", help="Copy only the APM upload key to a protected runtime file")
    secret.add_argument("destination")
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        with locked(config["state_directory"]) as directory:
            cloud = Cloud(config)
            if args.action == "backup":
                result = backup(cloud, config, directory)
            elif args.action == "probe":
                values = measure(directory)
                cloud.publish(values)
                result = {"metrics_accepted": sorted(values), "model_calls": 0}
            elif args.action == "drill":
                cloud.publish({"ReliabilityDrill": args.value}, drill=True)
                result = {"drill_signal_accepted": args.value, "model_calls": 0}
            elif args.action == "prepare-trace-key":
                key, _ = cloud.secret(config["apm_secret_id"])
                if not re.fullmatch(rb"[A-Za-z0-9_-]{16,256}", key):
                    raise ValueError("Invalid APM key")
                write_private(args.destination, key)
                result = {"trace_key_prepared": True}
            else:
                result = restore(cloud, config, args.object_name, args.destination)
        print(json.dumps(result, sort_keys=True))
    except Exception as exc:
        # SDK error bodies and URLs can contain private context; never echo them.
        print(json.dumps({"action": args.action, "status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
