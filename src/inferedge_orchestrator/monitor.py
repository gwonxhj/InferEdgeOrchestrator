from __future__ import annotations

import os
import platform
import re
import resource
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ResourceSnapshot:
    stage: str
    platform: str
    process_rss_mb: float | None
    cpu_percent: float | None = None
    memory_percent: float | None = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class ResourceMonitor:
    def capture(self, *, stage: str) -> ResourceSnapshot:
        psutil_snapshot = _capture_with_psutil(stage)
        if psutil_snapshot is not None:
            return psutil_snapshot
        return ResourceSnapshot(
            stage=stage,
            platform=platform.platform(),
            process_rss_mb=_rss_mb_from_resource(),
        )


def parse_tegrastats_line(line: str) -> dict[str, object]:
    parsed: dict[str, object] = {"raw": line.strip()}
    ram_match = re.search(r"RAM\s+(\d+)/(\d+)MB", line)
    if ram_match:
        used, total = ram_match.groups()
        parsed["ram_used_mb"] = int(used)
        parsed["ram_total_mb"] = int(total)

    swap_match = re.search(r"SWAP\s+(\d+)/(\d+)MB", line)
    if swap_match:
        used, total = swap_match.groups()
        parsed["swap_used_mb"] = int(used)
        parsed["swap_total_mb"] = int(total)

    cpu_match = re.search(r"CPU\s+\[([^\]]+)\]", line)
    if cpu_match:
        parsed["cpu"] = cpu_match.group(1)

    gr3d_match = re.search(r"GR3D_FREQ\s+(\d+)%", line)
    if gr3d_match:
        parsed["gpu_percent"] = int(gr3d_match.group(1))

    temp_matches = re.findall(r"([A-Za-z0-9_]+)@([0-9.]+)C", line)
    if temp_matches:
        parsed["temperatures_c"] = {
            name: float(value) for name, value in temp_matches
        }

    return parsed


def _capture_with_psutil(stage: str) -> ResourceSnapshot | None:
    try:
        import psutil
    except ModuleNotFoundError:
        return None

    process = psutil.Process(os.getpid())
    memory = process.memory_info()
    return ResourceSnapshot(
        stage=stage,
        platform=platform.platform(),
        process_rss_mb=round(memory.rss / (1024 * 1024), 3),
        cpu_percent=process.cpu_percent(interval=None),
        memory_percent=round(process.memory_percent(), 3),
    )


def _rss_mb_from_resource() -> float | None:
    try:
        usage = resource.getrusage(resource.RUSAGE_SELF)
    except (OSError, ValueError):
        return None
    # macOS reports ru_maxrss in bytes; Linux reports kilobytes.
    divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
    return round(usage.ru_maxrss / divisor, 3)
