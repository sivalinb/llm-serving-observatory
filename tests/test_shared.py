import json
import runpy
from pathlib import Path

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from observatory.app import create_app
from observatory.assistant import Assistant, Settings
from observatory.assistant_store import AssistantStore

ROOT = Path(__file__).resolve().parents[1]


def test_assistant_only_does_not_construct_or_expose_lab(tmp_path, monkeypatch):
    def forbidden(*args):
        pytest.fail("Assistant-only mode must not instantiate the lab")

    monkeypatch.setattr("observatory.app.Service", forbidden)
    monkeypatch.setenv("OBSERVATORY_ASSISTANT_ONLY", "true")
    app = create_app(db_path=tmp_path / "lab.sqlite")
    with TestClient(app) as client:
        assert app.state.service is None
        assert client.get("/healthz").json()["profile"] == "assistant-only"
        assert client.get("/").status_code == client.get("/assistant").status_code == 200
        assert client.get("/static/home.js").status_code == 200
        assert client.get("/metrics").status_code == 200
        for method, path in [
            ("GET", "/lab"),
            ("GET", "/api/config"),
            ("POST", "/api/run"),
            ("POST", "/api/benchmark"),
            ("GET", "/api/records"),
            ("GET", "/api/records/a"),
            ("GET", "/api/benchmarks"),
            ("GET", "/api/hardware/resources"),
            ("POST", "/api/hardware/estimate"),
            ("POST", "/v1/chat/completions"),
        ]:
            assert client.request(method, path).status_code == 404, path
            assert path not in client.get("/openapi.json").json()["paths"]
        assert client.get("/api/service/me").status_code == 401
        assert client.post("/api/service/answer").status_code == 401
    assert not (tmp_path / "lab.sqlite").exists()


def test_default_full_lab_preserved(tmp_path, monkeypatch):
    monkeypatch.delenv("OBSERVATORY_ASSISTANT_ONLY", raising=False)
    with TestClient(create_app(db_path=tmp_path / "lab.sqlite")) as client:
        assert client.get("/lab").status_code == client.get("/api/config").status_code == 200
        assert client.get("/healthz").json()["profile"] == "full-lab"


def test_profile_limits_from_environment(monkeypatch):
    monkeypatch.setenv("ASSISTANT_MAX_OUTPUT_TOKENS", "64")
    monkeypatch.setenv("ASSISTANT_CONTEXT_TOKENS", "2048")
    monkeypatch.setenv("ASSISTANT_MONTHLY_TOKENS", "100000")
    settings = Settings.from_env()
    assert (settings.max_output_tokens, settings.context, settings.monthly_tokens) == (
        64,
        2048,
        100000,
    )


@pytest.mark.parametrize("limit", [0, 15, 257])
def test_invalid_profile_output_limit(limit):
    with pytest.raises(ValueError):
        Settings(max_output_tokens=limit)


def test_server_output_limit_default_and_explicit_admission(tmp_path):
    upstream_bodies = []

    def handler(request):
        upstream_bodies.append(json.loads(request.content))
        body = 'data: {"choices":[{"delta":{"content":"Answer [S1]."}}]}\n\n'
        body += 'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\n'
        body += 'data: {"choices":[],"usage":{"prompt_tokens":90,"completion_tokens":12}}\n\n'
        return httpx.Response(200, text=body + "data: [DONE]\n\n")

    store = AssistantStore(tmp_path / "assistant.sqlite")
    credentials = store.redeem(store.invite(), "Test")
    user = store.authenticate(credentials["api_key"])
    assistant = Assistant(
        store,
        Settings(enabled=True, max_output_tokens=64),
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    headers = {"Authorization": "Bearer " + credentials["api_key"]}
    with TestClient(create_app(assistant_service=assistant, assistant_only=True)) as client:
        status = client.get("/api/service/status").json()
        assert status["default_output_tokens"] == status["max_output_tokens"] == 64
        response = client.post(
            "/api/service/answer",
            headers={**headers, "Idempotency-Key": "rejected_123456789"},
            json={"question": "CPU RAM", "max_tokens": 65},
        )
        assert response.status_code == 422 and "at most 64" in response.json()["detail"]
        assert not upstream_bodies and store.usage(user["id"])["requests_today"] == 0
        for index, requested in enumerate([None, 16]):
            body = {"question": "How is CPU RAM used?"}
            if requested is not None:
                body["max_tokens"] = requested
            response = client.post(
                "/api/service/answer",
                headers={**headers, "Idempotency-Key": f"accepted_12345678{index}"},
                json=body,
            )
            assert response.status_code == 200 and '"status": "ok"' in response.text
            assert upstream_bodies[-1]["max_tokens"] == (requested or 64)
            assert f'"max_output_tokens": {requested or 64}' in response.text
        assistant.settings = Settings(enabled=False, max_output_tokens=64)
        assert client.post(
            "/api/service/search", headers=headers, json={"question": "CPU RAM"}
        ).json()["sources"]
        assert (
            client.post(
                "/api/service/answer",
                headers={**headers, "Idempotency-Key": "disabled_123456789"},
                json={"question": "CPU RAM"},
            ).status_code
            == 503
        )
        assert len(upstream_bodies) == 2


def test_shared_compose_is_standalone_and_bounded():
    config = yaml.safe_load((ROOT / "compose.shared.yaml").read_text())
    assert config["name"] == "observatory-shared"
    assert config["networks"] == {"backend": {"internal": True}}
    assert set(config["volumes"]) == {"assistant-data", "metrics-data"}
    services = config["services"]
    assert set(services) == {"gateway", "model", "prometheus"}
    expected = {"gateway": (0.25, "256m"), "model": (0.5, "2560m"), "prometheus": (0.25, "256m")}
    for name, service in services.items():
        cpu, memory = expected[name]
        assert service["cpus"] == cpu
        assert service["mem_limit"] == service["memswap_limit"] == memory
        assert service["read_only"] and service["cap_drop"] == ["ALL"]
        assert service["security_opt"] == ["no-new-privileges:true"]
        assert service["pids_limit"] == 64 and service["restart"] == "on-failure:3"
        assert service["networks"] == ["backend"]
        assert len(service["tmpfs"]) == 1 and service["tmpfs"][0].startswith("/tmp:size=")
        assert "privileged" not in service and "network_mode" not in service
        assert "docker.sock" not in str(service)
    gateway = services["gateway"]
    assert gateway["ports"] == ["127.0.0.1:18000:8000"]
    assert gateway["environment"]["OBSERVATORY_ASSISTANT_ONLY"] == "true"
    assert gateway["environment"]["ASSISTANT_MAX_OUTPUT_TOKENS"] == "64"
    assert gateway["environment"]["ASSISTANT_MONTHLY_TOKENS"] == "100000"
    assert not gateway["environment"]["OTEL_EXPORTER_OTLP_ENDPOINT"]
    assert gateway["command"][gateway["command"].index("--workers") + 1] == "1"
    model = services["model"]
    assert "ports" not in model
    assert model["volumes"] == ["./models:/models:ro,Z"]
    assert (
        model["image"]
        == yaml.safe_load((ROOT / "compose.cpu.yaml").read_text())["services"]["model"]["image"]
    )
    for flag in ["--parallel", "--threads", "--threads-batch"]:
        assert model["command"][model["command"].index(flag) + 1] == "1"
    assert services["prometheus"]["profiles"] == ["metrics"]
    assert services["prometheus"]["ports"] == ["127.0.0.1:19090:9090"]


def test_shared_metrics_only_scrape_own_services():
    config = yaml.safe_load((ROOT / "observability/prometheus-shared.yaml").read_text())
    assert config["global"]["scrape_interval"] == "30s"
    assert {
        t
        for job in config["scrape_configs"]
        for entry in job["static_configs"]
        for t in entry["targets"]
    } == {"gateway:8000", "model:8080"}
    assert all(job["sample_limit"] == 2000 for job in config["scrape_configs"])


def test_shared_host_preflight_fail_closed():
    script = runpy.run_path(str(ROOT / "scripts/shared_preflight.py"))
    evaluate, gib = script["evaluate"], script["GIB"]
    healthy = {
        "memory_available_bytes": 7 * gib,
        "swap_used_bytes": 0,
        "checkout_free_bytes": 10 * gib,
        "docker_free_bytes": 10 * gib,
        "cpus": 2,
        "load_1m": 1.1,
        "occupied_ports": [],
        "existing_project_containers": False,
        "cgroup_version": "2",
        "limits_supported": True,
    }
    assert evaluate(healthy) == []
    for key, bad in [
        ("memory_available_bytes", 4 * gib),
        ("swap_used_bytes", 1),
        ("checkout_free_bytes", 7 * gib),
        ("docker_free_bytes", 7 * gib),
        ("cpus", 1),
        ("load_1m", 1.6),
        ("occupied_ports", [18000]),
        ("existing_project_containers", True),
        ("cgroup_version", "1"),
        ("limits_supported", False),
    ]:
        assert evaluate({**healthy, key: bad}), key
