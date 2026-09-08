import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from prometheus_client import CollectorRegistry, generate_latest
from pydantic import ValidationError

from observatory.app import create_app
from observatory.hardware import GIB, HardwareRequest, estimate, estimate_with_sweep
from observatory.resources import ResourceMonitor, cgroup_v2


def test_committed_portfolio_report_is_reproducible():
    root = Path(__file__).resolve().parents[1]
    report = subprocess.check_output(
        [sys.executable, str(root / "scripts/hardware_report.py")], text=True
    )
    assert json.loads((root / "reports/sample-hardware.json").read_text()) == json.loads(report)


def test_exact_memory_accounting_and_units():
    r = estimate(HardwareRequest())
    m = r["memory"]
    assert m["weights_bytes"] == 16e9
    assert m["kv_bytes_per_token"] == 131072
    assert m["kv_bytes"] == (4096 + 512) * 4 * 131072
    assert m["capacity_bytes"] == 24 * GIB
    assert m["required_bytes"] == sum(
        m[k]
        for k in [
            "weights_bytes",
            "weight_overhead_bytes",
            "kv_bytes",
            "workspace_bytes",
            "reserve_bytes",
        ]
    )
    assert m["fits"]
    assert r["source"] == "analytical_estimate"


def test_context_concurrency_and_kv_precision_scale_independently():
    base = estimate(HardwareRequest())["memory"]
    double_batch = estimate(HardwareRequest(concurrency=8))["memory"]
    half_kv = estimate(HardwareRequest(kv_bits=8))["memory"]
    quarter_weights = estimate(HardwareRequest(weight_bits=4))["memory"]
    assert double_batch["kv_bytes"] == base["kv_bytes"] * 2
    assert double_batch["weights_bytes"] == base["weights_bytes"]
    assert half_kv["kv_bytes"] == base["kv_bytes"] / 2
    assert quarter_weights["weights_bytes"] == base["weights_bytes"] / 4
    assert quarter_weights["kv_bytes"] == base["kv_bytes"]


def test_capacity_failure_withholds_throughput_not_fake_oom():
    r = estimate(HardwareRequest(input_tokens=32768))
    assert not r["memory"]["fits"]
    assert r["memory"]["headroom_bytes"] < 0
    assert r["performance"]["decode_limiting_term"] == "capacity"
    assert r["performance"]["decode_step_floor_ms"] is None
    assert r["performance"]["aggregate_output_ceiling_tps"] is None
    assert estimate(HardwareRequest(memory_gib=1))["memory"]["max_concurrency"] == 0


def test_capacity_boundary_matches_maximum_concurrency():
    req = HardwareRequest()
    maximum = estimate(req)["memory"]["max_concurrency"]
    assert estimate(req.model_copy(update={"concurrency": maximum}))["memory"]["fits"]
    assert not estimate(req.model_copy(update={"concurrency": maximum + 1}))["memory"]["fits"]


def test_hbm_bandwidth_and_network_are_separate():
    base = estimate(HardwareRequest())
    slow_memory = estimate(HardwareRequest(memory_gb_s=500))
    slow_link = estimate(HardwareRequest(link_gb_s=12.5))
    assert base["memory"] == slow_memory["memory"] == slow_link["memory"]
    assert (
        slow_memory["performance"]["decode_memory_floor_ms"]
        == base["performance"]["decode_memory_floor_ms"] * 2
    )
    assert (
        slow_link["performance"]["decode_step_floor_ms"]
        == base["performance"]["decode_step_floor_ms"]
    )
    assert (
        slow_memory["performance"]["prompt_kv_transfer_floor_ms_per_request"]
        == base["performance"]["prompt_kv_transfer_floor_ms_per_request"]
    )
    assert slow_link["performance"]["prompt_kv_transfer_floor_ms_per_request"] - 3 == pytest.approx(
        (base["performance"]["prompt_kv_transfer_floor_ms_per_request"] - 3) * 2
    )


def test_output_kv_grows_without_changing_prompt_handoff():
    a = estimate(HardwareRequest(output_tokens=1))
    b = estimate(HardwareRequest(output_tokens=8192))
    assert b["memory"]["kv_bytes"] > a["memory"]["kv_bytes"]
    assert (
        a["performance"]["prompt_kv_transfer_bytes_per_request"]
        == b["performance"]["prompt_kv_transfer_bytes_per_request"]
    )


@pytest.mark.parametrize(
    "invalid",
    [
        {"memory_efficiency": 0},
        {"parameters_b": float("nan")},
        {"memory_gb_s": float("inf")},
        {"concurrency": 0},
        {"weight_bits": 3},
        {"input_tokens": 2**30},
        {"unknown": 1},
    ],
)
def test_hardware_input_boundaries(invalid):
    with pytest.raises(ValidationError):
        HardwareRequest(**invalid)


def test_sweep_is_bounded_sorted_and_deterministic():
    req = HardwareRequest(input_tokens=1234)
    a = estimate_with_sweep(req)
    assert a == estimate_with_sweep(req)
    assert len(a["context_sweep"]) == 6
    assert [x["required_gib"] for x in a["context_sweep"]] == sorted(
        x["required_gib"] for x in a["context_sweep"]
    )
    json.dumps(a, allow_nan=False)


def test_cgroup_nulls_and_exact_unit_conversion(tmp_path):
    assert all(v is None for v in cgroup_v2(tmp_path).values())
    (tmp_path / "cgroup.controllers").write_text("cpu memory")
    (tmp_path / "memory.current").write_text("1234")
    (tmp_path / "memory.max").write_text("max")
    (tmp_path / "cpu.max").write_text("150000 100000")
    (tmp_path / "cpu.stat").write_text("usage_usec 42\nthrottled_usec 2500000\n")
    c = cgroup_v2(tmp_path)
    assert c == {
        "memory_current_bytes": 1234,
        "memory_limit_bytes": None,
        "cpu_quota_cores": 1.5,
        "cpu_throttled_seconds_total": 2.5,
    }
    (tmp_path / "cpu.max").write_text("max 100000")
    (tmp_path / "memory.max").write_text("4096")
    assert cgroup_v2(tmp_path)["cpu_quota_cores"] is None
    assert cgroup_v2(tmp_path)["memory_limit_bytes"] == 4096


def test_real_sampler_never_invents_gpu_values():
    monitor = ResourceMonitor()
    assert monitor.snapshot()["status"] == "unavailable"
    first = monitor.sample()
    assert first["process"]["cpu_cores"] is None
    second = monitor.sample()
    assert second["process"]["cpu_cores"] >= 0
    assert second["process"]["rss_bytes"] > 0
    assert second["gpu"]["memory_used_bytes"] is None
    registry = CollectorRegistry()
    registry.register(monitor)
    metrics = generate_latest(registry).decode()
    assert "lab_resource_process_rss_bytes" in metrics
    assert "lab_resource_process_cpu_seconds_total" in metrics
    assert "gpu_memory" not in metrics
    monitor.latest = None
    assert "lab_resource_process_rss_bytes" not in generate_latest(registry).decode()


async def test_monitor_lifecycle():
    monitor = ResourceMonitor()
    await monitor.start()
    assert monitor.snapshot()["status"] == "ok"
    await monitor.stop()
    assert monitor.task.done()


def test_hardware_api_auth_and_provenance(monkeypatch):
    monkeypatch.setenv("LAB_API_KEY", "test-key")
    with TestClient(create_app(db_path=":memory:")) as client:
        assert client.post("/api/hardware/estimate", json={}).status_code == 401
        assert client.get("/api/hardware/resources").status_code == 401
        headers = {"Authorization": "Bearer test-key"}
        result = client.post("/api/hardware/estimate", json={}, headers=headers)
        assert result.status_code == 200
        assert result.json()["source"] == "analytical_estimate"
        assert (
            client.post(
                "/api/hardware/estimate", json={"concurrency": -1}, headers=headers
            ).status_code
            == 422
        )
        resources = client.get("/api/hardware/resources", headers=headers).json()
        assert resources["source"] == "measured"
        assert resources["process"]["rss_bytes"] > 0
        assert "lab_resource_process_rss_bytes" in client.get("/metrics").text
        assert client.get("/api/records", headers=headers).json()["records"] == []
