"""Measured process/host resources, sampled independently of inference requests."""

import asyncio
import time
from contextlib import suppress
from pathlib import Path

import psutil
from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily


def cgroup_v2(root=Path("/sys/fs/cgroup")):
    """Read this cgroup namespace's root, not arbitrary host processes.

    Intended for the default private Docker cgroup namespace. Nested cgroups,
    ancestor limits, cpusets and v1 are not resolved; null means unavailable.
    """
    result = {
        "memory_current_bytes": None,
        "memory_limit_bytes": None,
        "cpu_quota_cores": None,
        "cpu_throttled_seconds_total": None,
    }
    if not (root / "cgroup.controllers").exists():
        return result
    for filename, key in [
        ("memory.current", "memory_current_bytes"),
        ("memory.max", "memory_limit_bytes"),
    ]:
        try:
            value = int((root / filename).read_text().strip())
            if value >= 0:
                result[key] = value
        except (OSError, ValueError):
            pass
    try:
        quota, period = (root / "cpu.max").read_text().split()
        if quota != "max" and int(period) > 0 and int(quota) > 0:
            result["cpu_quota_cores"] = int(quota) / int(period)
    except (OSError, ValueError):
        pass
    try:
        stats = dict(line.split() for line in (root / "cpu.stat").read_text().splitlines())
        result["cpu_throttled_seconds_total"] = int(stats["throttled_usec"]) / 1e6
    except (OSError, ValueError, KeyError):
        pass
    return result


class ResourceMonitor:
    def __init__(self):
        self.process = psutil.Process()
        self.previous = None
        self.latest = None
        self.task = None

    def sample(self):
        now = time.monotonic()
        with self.process.oneshot():
            cpu = self.process.cpu_times()
            cpu_seconds = cpu.user + cpu.system
            rss = self.process.memory_info().rss
            threads = self.process.num_threads()
        cores = None
        if self.previous and now > self.previous[0]:
            cores = max(0, (cpu_seconds - self.previous[1]) / (now - self.previous[0]))
        self.previous = (now, cpu_seconds)
        vm = psutil.virtual_memory()
        self.latest = {
            "source": "measured",
            "sampled_at_unix": time.time(),
            "status": "ok",
            "process": {
                "cpu_cores": cores,
                "cpu_seconds_total": cpu_seconds,
                "rss_bytes": rss,
                "threads": threads,
            },
            "host": {"memory_total_bytes": vm.total, "memory_available_bytes": vm.available},
            "cgroup_namespace_root": cgroup_v2(),
            "gpu": {"status": "external_exporter_required", "memory_used_bytes": None},
            "scope": "This service process; host-visible RAM; optional cgroup-v2 namespace root. Not per-request GPU usage.",
        }
        return self.latest

    def snapshot(self):
        if not self.latest:
            return {"source": "measured", "status": "unavailable"}
        return {
            **self.latest,
            "sample_age_seconds": max(0, time.time() - self.latest["sampled_at_unix"]),
        }

    async def start(self):
        async def sample_safely():
            try:
                await asyncio.to_thread(self.sample)
            except (psutil.Error, OSError):
                # Do not retain stale numbers as though they were fresh measurements.
                self.latest = None

        await sample_safely()

        async def loop():
            while True:
                await asyncio.sleep(2)
                await sample_safely()

        self.task = asyncio.create_task(loop())

    async def stop(self):
        if self.task:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task

    def collect(self):
        data = self.snapshot()
        yield GaugeMetricFamily(
            "lab_resource_sample_available",
            "Resource sampler is available",
            value=int(data["status"] == "ok"),
        )
        if data["status"] != "ok":
            return
        yield GaugeMetricFamily(
            "lab_resource_sample_age_seconds",
            "Age of the last resource sample",
            value=data["sample_age_seconds"],
        )
        for scope in ("process", "host", "cgroup_namespace_root"):
            for key, value in data[scope].items():
                if value is None:
                    continue
                family = CounterMetricFamily if key.endswith("_total") else GaugeMetricFamily
                yield family(f"lab_resource_{scope}_{key}", f"Measured {scope}: {key}", value=value)
