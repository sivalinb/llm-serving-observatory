"""Verify the public Caddy boundary; use an explicit URL, e.g. http://localhost in CI."""

import argparse
import time
from urllib.error import HTTPError
from urllib.request import urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    args = parser.parse_args()
    for attempt in range(30):
        try:
            with urlopen(args.url.rstrip("/") + "/api/service/status", timeout=2):
                break
        except OSError:
            if attempt == 29:
                raise
            time.sleep(1)

    def status(path):
        try:
            with urlopen(args.url.rstrip("/") + path, timeout=10) as response:
                return response.status
        except HTTPError as error:
            return error.code

    for path in ["/", "/assistant", "/api/service/status", "/static/assistant.js"]:
        assert status(path) == 200, path
    assert status("/api/service/me") == 401
    for path in [
        "/metrics",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/api/config",
        "/api/records",
        "/api/hardware/resources",
        "/api/run",
        "/v1/chat/completions",
        "/static/index.html",
        "/static/app.js",
        "/healthz",
    ]:
        assert status(path) == 404, path
    print("Public assistant allowlist verified; lab and operations routes are blocked.")


if __name__ == "__main__":
    main()
