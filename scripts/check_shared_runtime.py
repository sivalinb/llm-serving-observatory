"""Read-only checks of the running shared stack; no benchmark or model request."""

import json
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    compose = ["docker", "compose", "-f", "compose.shared.yaml", "--profile", "metrics"]
    expected = {
        "gateway": (250000000, 256),
        "model": (500000000, 2560),
        "prometheus": (250000000, 256),
    }
    for name, (nano_cpus, mib) in expected.items():
        identifier = subprocess.check_output(compose + ["ps", "-q", name], text=True).strip()
        assert identifier, f"Missing {name}"
        container = json.loads(subprocess.check_output(["docker", "inspect", identifier]))[0]
        config, state = container["HostConfig"], container["State"]
        assert config["NanoCpus"] == nano_cpus, name
        assert config["Memory"] == config["MemorySwap"] == mib * 1024**2, name
        assert config["ReadonlyRootfs"] and config["PidsLimit"] == 64, name
        assert state["Running"] and not state["OOMKilled"], name
        assert state["Health"]["Status"] == "healthy", name
        assert container["RestartCount"] == 0, f"{name} restarted; inspect before accepting traffic"
        for bindings in container["NetworkSettings"]["Ports"].values():
            assert not bindings or all(b["HostIp"] == "127.0.0.1" for b in bindings), name
        if name == "model":
            assert not any(container["NetworkSettings"]["Ports"].values())
        networks = container["NetworkSettings"]["Networks"]
        assert set(networks) == (
            {"observatory-shared_backend"}
            if name == "model"
            else {"observatory-shared_backend", "observatory-shared_access"}
        ), name
    backend = json.loads(
        subprocess.check_output(["docker", "network", "inspect", "observatory-shared_backend"])
    )[0]
    assert backend["Internal"], "Model backend must remain internal"
    with urlopen("http://127.0.0.1:18000/healthz", timeout=10) as response:
        assert json.load(response)["profile"] == "assistant-only"
    with urlopen("http://127.0.0.1:18000/api/service/status", timeout=10) as response:
        status = json.load(response)
        assert status["max_output_tokens"] == 64 and status["max_concurrent_answers"] == 1
    for path, method, expected_status in [
        ("/lab", "GET", 404),
        ("/api/config", "GET", 404),
        ("/api/benchmark", "POST", 404),
        ("/v1/chat/completions", "POST", 404),
        ("/api/service/answer", "POST", 401),
        ("/api/observability/session", "GET", 401),
        ("/api/observability/overview", "GET", 401),
        ("/api/observability/events?scope=all", "GET", 401),
    ]:
        try:
            urlopen(Request("http://127.0.0.1:18000" + path, method=method), timeout=10)
        except HTTPError as exc:
            assert exc.code == expected_status, (path, exc.code)
        else:
            raise AssertionError(f"Unexpectedly accessible: {path}")
    # A healthy Prometheus may not have performed its first 30-second scrape yet.
    deadline = time.monotonic() + 45
    while True:
        with urlopen("http://127.0.0.1:19090/api/v1/targets", timeout=5) as response:
            targets = json.load(response)["data"]["activeTargets"]
        jobs = {t["labels"]["job"] for t in targets}
        if jobs == {"shared-assistant", "shared-model"} and all(
            t["health"] == "up" for t in targets
        ):
            break
        assert time.monotonic() < deadline, targets
        time.sleep(1)
    with urlopen("http://127.0.0.1:19090/api/v1/rules", timeout=10) as response:
        groups = json.load(response)["data"]["groups"]
        assert len(groups) == 1 and len(groups[0]["rules"]) == 3
    print(
        "Shared runtime checks passed: enforced limits, health, private ports, disabled lab, authenticated dashboard, private metrics."
    )


if __name__ == "__main__":
    main()
