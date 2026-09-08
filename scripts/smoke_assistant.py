"""Exercise real CPU inference through the user-facing API. Run after Compose is healthy."""

import argparse
import json
import subprocess
import uuid
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    # The invitation and personal key remain in memory and are never printed or put in argv.
    invite = subprocess.check_output(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "gateway",
            "python",
            "-m",
            "observatory.admin",
            "invite",
            "--requests",
            "2",
            "--hours",
            "1",
        ],
        text=True,
    ).strip()

    def call(path, body, key=None, idem=None):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = "Bearer " + key
        if idem:
            headers["Idempotency-Key"] = idem
        req = Request(
            args.url + "/api/service/" + path,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )
        return urlopen(req, timeout=120)

    with call("redeem", {"invite": invite, "name": "CI smoke"}) as response:
        key = json.load(response)["api_key"]
    try:
        with call(
            "answer",
            {"question": "What is TTFT? Explain with a source citation.", "max_tokens": 64},
            key,
            str(uuid.uuid4()),
        ) as response:
            events = [
                json.loads(line[6:])
                for line in response.read().decode().splitlines()
                if line.startswith("data: ")
            ]
        record = next(e["record"] for e in events if e["type"] == "result")
        assert record["status"] == "ok", record
        assert record["tokens"]["input"] > 0 and record["tokens"]["output"] > 0, record
        assert record["ttft_ms"] > 0
        assert any(e["type"] == "delta" and e["content"] for e in events)
        # Machine-readable evidence without storing the question or generated answer.
        print(json.dumps({"real_cpu_smoke": "passed", "record": record}, indent=2))
    finally:
        with call("revoke-key", {}, key):
            pass


if __name__ == "__main__":
    main()
