"""Validate private shared-dashboard data and roles without inference or fake telemetry.

Uses the explicitly selected Compose environment. Creates one temporary personal key,
grants/revokes an operator role through the host CLI, then revokes the key. No secrets
are printed or placed in argv. Run only against your own approved shared deployment.
"""

import argparse
import json
import subprocess
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18000")
    args = parser.parse_args()
    admin = ["docker", "compose", "exec", "-T", "gateway", "python", "-m", "observatory.admin"]
    invite = subprocess.check_output(admin + ["invite", "--requests", "1", "--hours", "1"], text=True).strip()

    def call(path, key=None, body=None, expected=200):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        request = Request(args.url.rstrip("/") + path, headers=headers,
                          data=json.dumps(body).encode() if body is not None else None)
        try:
            with urlopen(request, timeout=25) as response:
                assert response.status == expected, path
                return json.load(response)
        except HTTPError as exc:
            if exc.code == expected:
                return None
            # Do not emit provider responses, headers or credential material.
            raise AssertionError(f"{path}: HTTP {exc.code}, expected {expected}") from None

    key = call("/api/service/redeem", body={"invite": invite, "name": "Dashboard validation"})["api_key"]
    uid = None
    try:
        session = call("/api/observability/session", key)
        uid = session["user_id"]
        assert not session["is_operator"]
        call("/api/observability/overview", key, expected=403)
        call("/api/observability/requests?scope=all", key, expected=403)
        call("/api/observability/events?scope=all", key, expected=403)
        assert call("/api/observability/requests", key)["records"] == []
        assert call("/api/observability/events", key)["events"] == []
        subprocess.check_output(admin + ["operator", "grant", uid])
        assert call("/api/observability/session", key)["is_operator"]
        overview = call("/api/observability/overview", key)
        for section in ("summary", "targets", "alerts"):
            assert overview[section]["state"] == "ready", section + " unavailable"
        targets = overview["targets"]["data"]["targets"]
        assert {t["job"] for t in targets} == {"shared-assistant", "shared-model"}
        assert all(t["health"] == "up" for t in targets)
        rules = overview["alerts"]["data"]["rules"]
        assert len(rules) == 3 and all(r["healthy"] for r in rules)
        catalog = call("/api/observability/catalog", key)
        assert catalog["state"] == "ready"
        names = {m["name"] for m in catalog["data"]["metrics"]}
        assert "up" in names and "view:ttft_p95" in names
        assert any(n.startswith("llamacpp:") for n in names), "Engine catalog absent"
        assert any(n.startswith("lab_resource_") for n in names), "Gateway resources absent"
        point_count = 0
        for metric in ("up", "view:ttft_p95"):
            chart = call("/api/observability/chart?metric=" + metric + "&window=15m", key)
            assert chart["state"] == "ready"
            series = chart["data"]["series"]
            assert len(series) <= 8 and all(len(s["points"]) <= 121 for s in series)
            point_count += sum(len(s["points"]) for s in series)
            if metric == "up":
                assert series and all(s["points"] for s in series)
        records = call("/api/observability/requests?scope=all", key)["records"]
        events = call("/api/observability/events?scope=all", key)["events"]
        assert any(e["kind"] == "operator_granted" for e in events)
        subprocess.check_output(admin + ["operator", "revoke", uid])
        call("/api/observability/overview", key, expected=403)
        report = {"dashboard_smoke": "passed", "metrics_in_catalog": len(names),
                          "chart_points": point_count, "healthy_targets": len(targets),
                          "evaluated_rules": len(rules), "retained_requests": len(records),
                          "event_kinds": sorted({e["kind"] for e in events}),
                  "model_calls": 0, "role_revocation_verified": True}
    finally:
        try:
            if uid is not None:
                subprocess.check_output(admin + ["operator", "revoke", uid])
        finally:
            call("/api/service/revoke-key", key, body={})
            call("/api/observability/session", key, expected=401)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
