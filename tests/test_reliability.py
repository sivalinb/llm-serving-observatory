import json
import os
import sqlite3
from pathlib import Path

import pytest

from observatory import reliability as r


@pytest.fixture
def database(tmp_path):
    db = tmp_path / "live.sqlite"
    with sqlite3.connect(db) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        for table in r.TABLES:
            connection.execute(f"CREATE TABLE {table} (id TEXT PRIMARY KEY, value TEXT)")
            connection.execute(f"INSERT INTO {table} VALUES (?,?)", ("owner", "private-value"))
    return db


class Cloud:
    def __init__(self):
        self.keys = {1: os.urandom(32), 2: os.urandom(32)}
        self.version = 1
        self.objects = {}
        self.secret_requests = []

    def capacity(self):
        if len(self.objects) >= r.MAX_OBJECTS:
            raise ValueError("full")

    def secret(self, identifier, version=None):
        version = version or self.version
        self.secret_requests.append((identifier, version))
        return self.keys[version], version

    def put(self, name, body):
        assert name not in self.objects
        self.objects[name] = body

    def get(self, name):
        return self.objects[name]


@pytest.fixture
def config(tmp_path, database):
    state = tmp_path / "private"
    state.mkdir(mode=0o700)
    return {"region": "us-phoenix-1", "namespace": "testnamespace",
            "bucket": "observatory-reliability-test", "compartment_id": "ocid1.compartment.oc1..test",
            "backup_secret_id": "ocid1.vaultsecret.oc1.phx.backup",
            "apm_secret_id": "ocid1.vaultsecret.oc1.phx.apm",
            "database": str(database), "state_directory": str(state)}


def test_roundtrip_is_encrypted_verified_and_preserves_live_database(config):
    cloud = Cloud()
    before = Path(config["database"]).read_bytes()
    result = r.backup(cloud, config, config["state_directory"])
    assert result["restore_verified"] is True
    assert result["table_counts"] == dict.fromkeys(r.TABLES, 1)
    assert before == Path(config["database"]).read_bytes()
    envelope = cloud.objects[result["object_name"]]
    assert b"private-value" not in envelope and b"SQLite format" not in envelope
    assert result["snapshot_age_seconds"] >= 0 and result["restore_seconds"] >= 0
    state = Path(config["state_directory"]) / "latest-backup.json"
    assert state.stat().st_mode & 0o777 == 0o600
    assert not list(Path(config["state_directory"]).glob("backup-*"))


def test_restore_uses_historical_key_version_and_never_overwrites(config):
    cloud = Cloud()
    result = r.backup(cloud, config, config["state_directory"])
    cloud.version = 2
    destination = Path(config["state_directory"]) / "restored.sqlite"
    r.restore(cloud, config, result["object_name"], destination)
    assert cloud.secret_requests[-1] == (config["backup_secret_id"], 1)
    with pytest.raises(ValueError, match="overwrite"):
        r.restore(cloud, config, result["object_name"], destination)
    with pytest.raises(ValueError, match="live database"):
        r.restore(cloud, config, result["object_name"], config["database"])


@pytest.mark.parametrize("part", ["ciphertext", "binding", "counts", "size", "sha256"])
def test_tampering_is_rejected_before_creating_restore(config, part):
    from cryptography.exceptions import InvalidTag

    cloud = Cloud()
    result = r.backup(cloud, config, config["state_directory"])
    value = json.loads(cloud.objects[result["object_name"]])
    if part == "ciphertext":
        value[part] = "AAAA" + value[part][4:]
    elif part == "binding":
        value["header"][part] = "another-bucket/object"
    elif part == "counts":
        value["header"][part] = {}
    elif part == "size":
        value["header"][part] += 1
    else:
        value["header"][part] = "0" * 64
    cloud.objects[result["object_name"]] = r.canonical(value)
    destination = Path(config["state_directory"]) / "rejected.sqlite"
    with pytest.raises((InvalidTag, ValueError)):
        r.restore(cloud, config, result["object_name"], destination)
    assert not destination.exists()


def test_failed_cloud_restore_does_not_mark_backup_success(config):
    cloud = Cloud()
    cloud.get = lambda _: b"broken response"
    with pytest.raises(ValueError):
        r.backup(cloud, config, config["state_directory"])
    assert not (Path(config["state_directory"]) / "latest-backup.json").exists()


def test_oversized_database_and_expired_snapshot_deadline_fail_closed(config, monkeypatch):
    monkeypatch.setattr(r, "MAX_SNAPSHOT", 1)
    with pytest.raises(ValueError, match="budget"):
        r.backup(Cloud(), config, config["state_directory"])
    monkeypatch.setattr(r, "MAX_SNAPSHOT", 8 * 1024**2)
    with pytest.raises(TimeoutError):
        r.snapshot(config["database"], Path(config["state_directory"]) / "timeout.sqlite", deadline=-1)


def test_private_paths_and_atomic_no_overwrite(tmp_path):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    target = directory / "secret"
    r.write_private(target, b"first")
    with pytest.raises(ValueError):
        r.write_private(target, b"second")
    assert target.read_bytes() == b"first"
    link = directory / "link"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        r.write_private(link, b"other", replace=True)
    directory.chmod(0o755)
    with pytest.raises(ValueError, match="0700"):
        r.write_private(directory / "new", b"value")


def test_config_exact_fields_region_and_permissions(config):
    path = Path(config["state_directory"]) / "config.json"
    r.write_private(path, r.canonical(config))
    assert r.load_config(path) == config
    for field, value in [("region", "us-ashburn-1"), ("bucket", "someone-elses-bucket"),
                         ("namespace", "invalid/name"), ("database", "relative.sqlite"),
                         ("backup_secret_id", "http://example.com/secret")]:
        r.write_private(path, r.canonical({**config, field: value}), replace=True)
        with pytest.raises(ValueError):
            r.load_config(path)
    path.chmod(0o644)
    with pytest.raises(ValueError):
        r.load_config(path)


def test_wal_snapshot_includes_committed_changes(config):
    with sqlite3.connect(config["database"]) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("INSERT INTO ledger VALUES ('second','sensitive')")
        writer.commit()
        result = r.backup(Cloud(), config, config["state_directory"])
        assert result["table_counts"]["ledger"] == 2


def test_probe_missing_state_never_fabricates_a_success_or_age(config, monkeypatch):
    monkeypatch.setattr(r, "json_probe", lambda _: (_ for _ in ()).throw(OSError()))
    result = r.measure(config["state_directory"])
    assert result["ServiceHealthy"] == result["EngineScrapeHealthy"] == result["BackupVerified"] == 0
    assert "BackupAgeSeconds" not in result


def test_probe_success_and_freshness_are_measured(config, monkeypatch):
    r.backup(Cloud(), config, config["state_directory"])
    monkeypatch.setattr(r, "json_probe", lambda url:
                        {"status": "ok", "profile": "assistant-only"} if url.endswith("healthz")
                        else {"data": {"result": [{"value": [123, "1"]}]}})
    result = r.measure(config["state_directory"])
    assert result["ServiceHealthy"] == result["EngineScrapeHealthy"] == result["BackupVerified"] == 1
    assert result["BackupAgeSeconds"] >= 0


def test_key_version_rejection_precedes_secret_lookup(config):
    cloud = Cloud()
    name = "backups/" + "a" * 32 + ".obk"
    for value in [None, 0, -1, "1", True, 10001]:
        cloud.objects[name] = r.canonical({"header": {"key_version": value}})
        with pytest.raises(ValueError):
            r.restore(cloud, config, name, Path(config["state_directory"]) / "bad.sqlite")
    assert not cloud.secret_requests


def test_private_lock_prevents_overlapping_workers(config):
    with r.locked(config["state_directory"]):
        with pytest.raises(BlockingIOError):
            with r.locked(config["state_directory"]):
                pytest.fail("overlapping worker acquired lock")
