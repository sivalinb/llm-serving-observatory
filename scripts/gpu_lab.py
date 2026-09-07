"""Supervise a finite same-host vLLM NIXL experiment using an explicit source checkout.

Run inside a compatible CUDA/vLLM/NIXL environment on a two-GPU host. Uses the
official version-matched toy proxy, not a locally invented KV handoff protocol.
This stops only its child processes; it DOES NOT stop OCI instance billing.
"""

import argparse
import os
import signal
import subprocess
import time
from pathlib import Path


def run(args):
    source = Path(args.vllm_source).resolve()
    proxy = source / "tests/v1/kv_connector/nixl_integration/toy_proxy_server.py"
    if not proxy.is_file():
        raise SystemExit("The selected vLLM checkout does not contain the documented NIXL proxy")
    commit = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True
    ).strip()
    if commit != args.source_sha:
        raise SystemExit("Source SHA does not match the explicit --source-sha")
    import nixl  # noqa: F401 -- fail before allocating GPUs when transport is missing
    import vllm

    print(f"vLLM={vllm.__version__} proxy_source={commit} model={args.model}", flush=True)
    print(
        "Hardware recipe: validate this vLLM/NIXL combination before interpreting results.",
        flush=True,
    )
    children = []
    try:
        for gpu, port, side, role in [
            ("0", "8100", "5600", "kv_producer"),
            ("1", "8200", "5601", "kv_consumer"),
        ]:
            env = {
                **os.environ,
                "CUDA_VISIBLE_DEVICES": gpu,
                "VLLM_NIXL_SIDE_CHANNEL_PORT": side,
                "VLLM_NIXL_SIDE_CHANNEL_HOST": "127.0.0.1",
                "UCX_NET_DEVICES": "all",
            }
            command = [
                "vllm",
                "serve",
                args.model,
                "--host",
                "127.0.0.1",
                "--port",
                port,
                "--enforce-eager",
                "--max-model-len",
                "8192",
                "--kv-transfer-config",
                '{"kv_connector":"NixlConnector","kv_role":"'
                + role
                + '","kv_load_failure_policy":"fail"}',
            ]
            children.append(subprocess.Popen(command, env=env, start_new_session=True))
        import sys

        children.append(
            subprocess.Popen(
                [
                    sys.executable,
                    str(proxy),
                    "--port",
                    "8192",
                    "--prefiller-hosts",
                    "localhost",
                    "--prefiller-ports",
                    "8100",
                    "--decoder-hosts",
                    "localhost",
                    "--decoder-ports",
                    "8200",
                ],
                start_new_session=True,
            )
        )
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            if any(child.poll() is not None for child in children):
                raise RuntimeError("An inference child exited; inspect its startup output")
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for child in children:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
        for child in children:
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--vllm-source", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--model", default="Qwen/Qwen3-0.6B")
    parser.add_argument("--duration", type=int, default=1800)
    args = parser.parse_args()
    if not 60 <= args.duration <= 7200:
        parser.error("Duration must be between 60 and 7200 seconds")
    run(args)
