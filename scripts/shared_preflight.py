"""Read-only Linux host gates BEFORE first shared-profile start; never deploy or repair."""

import json
import os
import platform
import subprocess
from pathlib import Path

GIB = 1024**3
ROOT = Path(__file__).resolve().parents[1]


def command(*args):
    return subprocess.check_output(args, text=True, timeout=20).strip()


def free_bytes(path):
    fs = os.statvfs(path)
    return fs.f_bavail * fs.f_frsize


def evaluate(snapshot):
    """Conservative installation gates, not a scheduling or Free Tier guarantee."""
    problems = []
    if snapshot["memory_available_bytes"] < 5 * GIB:
        problems.append("Need at least 5 GiB MemAvailable before installation")
    if min(snapshot["checkout_free_bytes"], snapshot["docker_free_bytes"]) < 8 * GIB:
        problems.append("Need at least 8 GiB free on BOTH checkout and Docker filesystems")
    if snapshot["swap_used_bytes"] > 0:
        problems.append("Swap is already in use; investigate baseline memory pressure first")
    if snapshot["cpus"] < 2 or snapshot["load_1m"] > snapshot["cpus"] * 0.75:
        problems.append("Need at least 2 CPUs and one-minute load <= 75% of logical CPU count")
    if snapshot["occupied_ports"]:
        problems.append("Required loopback ports are occupied: " + str(snapshot["occupied_ports"]))
    if snapshot["existing_project_containers"]:
        problems.append("observatory-shared already exists; inspect it instead of overwriting")
    if snapshot["cgroup_version"] != "2" or not snapshot["limits_supported"]:
        problems.append("Require cgroup v2 and Docker CPU, memory and swap-limit support")
    return problems


def snapshot():
    if platform.system() != "Linux":
        raise RuntimeError("Run on the intended Linux host, not the laptop")
    info = json.loads(command("docker", "info", "--format", "{{json .}}"))
    command("docker", "compose", "version")
    # Confirm the exact standalone Compose file resolves before checking the host.
    command("docker", "compose", "-f", str(ROOT / "compose.shared.yaml"), "config", "--quiet")
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        name, value = line.split(":", 1)
        memory[name] = int(value.strip().split()[0]) * 1024
    listening = command("ss", "-H", "-ltn")
    occupied = sorted(
        {
            int(row.split()[3].rsplit(":", 1)[-1])
            for row in listening.splitlines()
            if row.split()[3].rsplit(":", 1)[-1] in {"18000", "19090"}
        }
    )
    return {
        "architecture": platform.machine(),
        "cpus": os.cpu_count() or 0,
        "load_1m": os.getloadavg()[0],
        "memory_available_bytes": memory["MemAvailable"],
        "swap_used_bytes": memory["SwapTotal"] - memory["SwapFree"],
        "checkout_free_bytes": free_bytes(ROOT),
        "docker_free_bytes": free_bytes(info["DockerRootDir"]),
        "occupied_ports": occupied,
        "existing_project_containers": bool(
            command(
                "docker",
                "ps",
                "-aq",
                "--filter",
                "label=com.docker.compose.project=observatory-shared",
            )
        ),
        "cgroup_version": info.get("CgroupVersion"),
        "limits_supported": all(
            info.get(key) for key in ("MemoryLimit", "SwapLimit", "CPUCfsQuota")
        ),
    }


def main():
    try:
        observed = snapshot()
        problems = evaluate(observed)
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(json.dumps({"ready_for_review": False, "error": str(exc)}))
        return 1
    print(
        json.dumps(
            {"ready_for_review": not problems, "snapshot": observed, "blockers": problems}, indent=2
        )
    )
    return bool(problems)


if __name__ == "__main__":
    raise SystemExit(main())
