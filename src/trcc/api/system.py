"""System metrics and diagnostic report endpoints."""
from __future__ import annotations

import dataclasses
import logging

from fastapi import APIRouter

log = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])


def _get_system_svc():
    """Get the shared SystemService instance (initialized by configure_app())."""
    from fastapi import HTTPException

    import trcc.api as api
    if api._system_svc is None:
        raise HTTPException(status_code=503, detail="System service not initialized")
    return api._system_svc


@router.get("/metrics")
def get_metrics() -> dict:
    """All system metrics as JSON (CPU, GPU, memory, disk, network, fans)."""
    svc = _get_system_svc()
    m = svc.all_metrics
    return dataclasses.asdict(m)


@router.get("/metrics/{category}")
def get_metrics_by_category(category: str) -> dict:
    """Filtered metrics by category (cpu, gpu, mem, disk, net, fan)."""
    from fastapi import HTTPException

    prefix_map = {
        "cpu": "cpu_",
        "gpu": "gpu_",
        "mem": "mem_",
        "memory": "mem_",
        "disk": "disk_",
        "net": "net_",
        "network": "net_",
        "fan": "fan_",
    }

    if not (prefix := prefix_map.get(category.lower())):
        raise HTTPException(
            status_code=400,
            detail=f"Unknown category '{category}'. Use: {', '.join(sorted(prefix_map.keys()))}",
        )

    svc = _get_system_svc()
    m = svc.all_metrics
    all_data = dataclasses.asdict(m)
    return {k: v for k, v in all_data.items() if k.startswith(prefix)}


@router.get("/report")
def get_report() -> dict:
    """Generate diagnostic report for bug reports."""
    from trcc.adapters.infra.debug_report import DebugReport

    rpt = DebugReport()
    rpt.collect()
    return {"report": str(rpt)}


@router.get("/perf")
def get_perf() -> dict:
    """Run CPU + memory performance benchmarks."""
    from trcc.services.perf import run_benchmarks

    report = run_benchmarks()
    return report.to_dict()


@router.get("/perf/device")
def get_perf_device() -> dict:
    """Benchmark connected hardware (USB handshake, frame latency, FPS)."""
    from trcc.adapters.device.detector import DeviceDetector
    from trcc.adapters.device.factory import DeviceProtocolFactory
    from trcc.adapters.device.led import probe_led_model
    from trcc.services.perf import run_device_benchmarks

    report = run_device_benchmarks(
        detect_fn=DeviceDetector.detect,
        get_protocol=DeviceProtocolFactory.get_protocol,
        get_protocol_info=DeviceProtocolFactory.get_protocol_info,
        probe_led_fn=probe_led_model,
    )
    return report.to_dict()
