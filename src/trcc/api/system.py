"""System metrics and diagnostic report endpoints."""
from __future__ import annotations

import dataclasses
import logging

from fastapi import APIRouter

log = logging.getLogger(__name__)

router = APIRouter(prefix="/system", tags=["system"])


def _get_system_svc():
    """Get or create the shared SystemService instance."""
    import trcc.api as api
    from trcc.services import SystemService

    if api._system_svc is None:
        api._system_svc = SystemService()
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

    svc = _get_system_svc()
    m = svc.all_metrics
    all_data = dataclasses.asdict(m)

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

    prefix = prefix_map.get(category.lower())
    if not prefix:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown category '{category}'. Use: {', '.join(sorted(prefix_map.keys()))}",
        )

    return {k: v for k, v in all_data.items() if k.startswith(prefix)}


@router.get("/commands")
def list_commands() -> dict:
    """List all available dispatcher commands (self-documenting API).

    Returns display and LED command names with descriptions, so API
    clients (Flutter app, scripts) can discover what's available.
    """
    from trcc.cli._display import DisplayDispatcher
    from trcc.cli._led import LEDDispatcher

    def _methods(cls: type) -> list[dict]:
        results = []
        for name in sorted(dir(cls)):
            if name.startswith('_'):
                continue
            attr = getattr(cls, name, None)
            if not callable(attr):
                continue
            doc = (attr.__doc__ or '').strip().split('\n')[0]
            results.append({"name": name, "description": doc})
        return results

    return {
        "display": _methods(DisplayDispatcher),
        "led": _methods(LEDDispatcher),
    }


@router.get("/report")
def get_report() -> dict:
    """Generate diagnostic report for bug reports."""
    from trcc.adapters.infra.debug_report import DebugReport

    rpt = DebugReport()
    rpt.collect()
    return {"report": str(rpt)}
