"""Reproducible closed-loop runner. Prints exportable JSON to stdout."""

import argparse
import asyncio
import json
import os
import sys

import httpx


async def run(args):
    body = {
        "request": {
            "mode": args.mode,
            "input_tokens": args.input_tokens,
            "output_tokens": args.output_tokens,
            "prompt": args.prompt,
            "prefix_tokens": args.prefix_tokens,
            "cache_enabled": not args.no_cache,
            "transfer_mb_s": args.transfer_mb_s,
        },
        "requests": args.requests,
        "concurrency": args.concurrency,
        "warmup": args.warmup,
        "compare": args.mode != "upstream",
    }
    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            args.url.rstrip("/") + "/api/benchmark",
            json=body,
            headers={"Authorization": "Bearer " + os.environ["LAB_API_KEY"]}
            if os.getenv("LAB_API_KEY")
            else {},
        ) as response:
            response.raise_for_status()
            finished = False
            async for line in response.aiter_lines():
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                if event["type"] == "progress":
                    print(
                        f"{event['mode']}: {event['completed']}/{event['total']}", file=sys.stderr
                    )
                if event["type"] == "benchmark":
                    print(json.dumps(event["experiment"], indent=2))
                    finished = True
                    if event["experiment"]["status"] != "ok":
                        raise SystemExit(1)
            if not finished:
                raise RuntimeError("Benchmark stream ended without a report")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--mode", choices=["combined", "disaggregated", "upstream"], default="combined"
    )
    parser.add_argument("--input-tokens", type=int, default=512)
    parser.add_argument("--output-tokens", type=int, default=32)
    parser.add_argument("--prefix-tokens", type=int, default=256)
    parser.add_argument("--transfer-mb-s", type=float, default=1000)
    parser.add_argument("--requests", type=int, default=16)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--warmup", type=int, default=1)
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--prompt", default="Explain prefill, decode and KV caching.")
    asyncio.run(run(parser.parse_args()))
