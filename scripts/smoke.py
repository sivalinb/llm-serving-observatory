"""Exercise a deployed lab (including its worker HTTP path when configured)."""

import argparse
import asyncio
import json
import os

import httpx


async def smoke(url):
    headers = (
        {"Authorization": "Bearer " + os.environ["LAB_API_KEY"]} if os.getenv("LAB_API_KEY") else {}
    )
    async with httpx.AsyncClient(base_url=url, headers=headers, timeout=60) as client:
        assert (await client.get("/healthz")).json()["status"] == "ok"
        assert (await client.get("/")).status_code == 200
        estimate = (await client.post("/api/hardware/estimate", json={})).json()
        assert estimate["source"] == "analytical_estimate"
        assert estimate["memory"]["fits"]
        over = (await client.post("/api/hardware/estimate", json={"input_tokens": 32768})).json()
        assert not over["memory"]["fits"]
        assert over["performance"]["decode_step_floor_ms"] is None
        resources = (await client.get("/api/hardware/resources")).json()
        assert resources["source"] == "measured"
        assert resources["process"]["rss_bytes"] > 0
        request = {
            "mode": "disaggregated",
            "input_tokens": 64,
            "output_tokens": 8,
            "reasoning_tokens": 2,
        }
        r = await client.post("/api/run", json=request)
        r.raise_for_status()
        events = [
            json.loads(block[6:]) for block in r.text.split("\n\n") if block.startswith("data: ")
        ]
        record = events[-1]["record"]
        assert record["status"] == "ok", record
        assert record["tokens"]["visible_output"] == 6
        assert record["tokens"]["total"] == 72
        configured = (await client.get("/api/config")).json()
        if configured["distributed_workers"]:
            assert "worker_phases" in record
        failure = await client.post("/api/run", json={**request, "fault": "transfer_failure"})
        assert '"status": "error"' in failure.text
        metrics = (await client.get("/metrics")).text
        assert "lab_ttft_seconds" in metrics
        assert "lab_tokens_total" in metrics
        assert "lab_resource_process_rss_bytes" in metrics
        print(
            json.dumps(
                {
                    "status": "passed",
                    "distributed_workers": configured["distributed_workers"],
                    "ttft_ms": record["ttft_ms"],
                    "trace_id": record["trace_id"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    asyncio.run(smoke(args.url))
