"""Read-only integration checks for the local Compose monitoring stack."""

import asyncio
import json
import os
from pathlib import Path

import httpx


async def check():
    async with httpx.AsyncClient(timeout=5) as client:
        for attempt in range(45):
            try:
                response = await client.get(
                    "http://127.0.0.1:9090/api/v1/query",
                    params={"query": "lab_resource_process_rss_bytes"},
                )
                values = response.json()["data"]["result"]
                if len(values) == 3 and all(float(v["value"][1]) > 0 for v in values):
                    break
            except (httpx.HTTPError, ValueError, KeyError):
                pass
            if attempt == 44:
                raise RuntimeError("Three measured service RSS series did not become available")
            await asyncio.sleep(2)
        root = Path(__file__).resolve().parents[1]
        count = 0
        for path in (root / "observability/grafana/dashboards").glob("*.json"):
            dashboard = json.loads(path.read_text())
            for panel in dashboard["panels"]:
                for target in panel.get("targets", []):
                    expr = target["expr"].replace("$source", ".*").replace("$mode", ".*")
                    response = await client.get(
                        "http://127.0.0.1:9090/api/v1/query", params={"query": expr}
                    )
                    response.raise_for_status()
                    assert response.json()["status"] == "success", panel["title"]
                    count += 1
        health = await client.get("http://127.0.0.1:3000/api/health")
        assert health.json()["database"] == "ok"
        response = await client.get(
            "http://127.0.0.1:3000/api/dashboards/uid/lab-hardware",
            auth=("admin", os.environ["GRAFANA_PASSWORD"]),
        )
        response.raise_for_status()
        assert len(response.json()["dashboard"]["panels"]) == 12
        print(
            json.dumps(
                {
                    "status": "passed",
                    "measured_service_series": len(values),
                    "promql_queries_checked": count,
                    "hardware_dashboard_panels": 12,
                }
            )
        )


if __name__ == "__main__":
    asyncio.run(check())
