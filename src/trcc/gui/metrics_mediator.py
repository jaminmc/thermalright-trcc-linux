"""Centralized metrics coordinator (Mediator + Observer pattern).

Conky-inspired design: single timer, period-multiplied callbacks,
guard functions to skip inactive subscribers.  Replaces scattered
QTimers and manual dedup flags with one clean dispatch loop.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer

from ..core.models import HardwareMetrics

log = logging.getLogger(__name__)


@dataclass
class _Subscription:
    """A registered metrics consumer."""

    callback: Callable[[HardwareMetrics], None]
    period: int  # fire every N ticks (1 = every tick, 3 = every 3rd)
    guard: Callable[[], bool] | None  # skip when returns False


class MetricsMediator(QObject):
    """Single-timer metrics coordinator (Mediator + Observer).

    One poll loop per tick dispatches pre-polled ``HardwareMetrics``
    to all active subscribers.  Period multipliers let slow consumers
    (info module at 3s) coexist with fast ones (overlay at 1s) on the
    same timer without redundant ``get_all_metrics()`` calls.

    Usage::

        mediator = MetricsMediator(parent)
        mediator.subscribe(overlay_cb, period=1, guard=lambda: overlay_on)
        mediator.subscribe(info_cb,    period=3, guard=lambda: info_visible)
        mediator.ensure_running()
    """

    def __init__(self, parent: QObject,
                 metrics_fn: Callable[[], HardwareMetrics] | None = None) -> None:
        super().__init__(parent)
        if metrics_fn is None:
            raise RuntimeError(
                "MetricsMediator requires a metrics_fn. "
                "Pass SystemService.all_metrics from a composition root.")
        self._metrics_fn = metrics_fn
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._subs: list[_Subscription] = []
        self._tick_count = 0

    # -- Registration ----------------------------------------------------------

    def subscribe(
        self,
        callback: Callable[[HardwareMetrics], None],
        period: int = 1,
        guard: Callable[[], bool] | None = None,
    ) -> None:
        """Register a metrics consumer.

        Args:
            callback: Receives ``HardwareMetrics`` on each dispatch.
            period:   Fire every *period* ticks (1 = every tick).
            guard:    Skip dispatch when this returns ``False``.
        """
        self._subs.append(_Subscription(callback, max(1, period), guard))

    def unsubscribe(self, callback: Callable[[HardwareMetrics], None]) -> None:
        """Remove a previously registered consumer."""
        self._subs = [s for s in self._subs if s.callback is not callback]

    # -- Lifecycle -------------------------------------------------------------

    @property
    def is_active(self) -> bool:
        """Whether the metrics timer is currently running."""
        return self._timer.isActive()

    def set_interval(self, interval_ms: int) -> None:
        """Change the tick interval.  Restarts timer if running."""
        if self._timer.isActive():
            self._timer.start(interval_ms)
        else:
            self._timer.setInterval(interval_ms)

    def ensure_running(self, interval_ms: int = 1000) -> None:
        """Start the timer if any subscriber's guard passes.

        Call after state changes (overlay toggled, LED started, etc.)
        to wake the mediator when it was previously idle.  No-op if
        already running.
        """
        if self._timer.isActive():
            return
        for sub in self._subs:
            if sub.guard is None or sub.guard():
                self._timer.start(self._timer.interval() or interval_ms)
                return

    def stop(self) -> None:
        """Stop the timer unconditionally."""
        self._timer.stop()
        self._tick_count = 0

    # -- Core loop -------------------------------------------------------------

    def _tick(self) -> None:
        """Single poll -> dispatch to period-matched, guard-passing subscribers.

        Skips ``get_all_metrics()`` entirely when no subscriber will fire
        this tick (all guards fail or period doesn't match).
        """
        self._tick_count += 1
        # Collect active subscribers before polling sensors
        active: list[_Subscription] = []
        for sub in self._subs:
            if self._tick_count % sub.period == 0:
                if sub.guard is None or sub.guard():
                    active.append(sub)
        if not active:
            return
        try:
            metrics = self._metrics_fn()
        except Exception:
            return
        from ..conf import settings
        HardwareMetrics.with_temp_unit(metrics, settings.temp_unit)
        for sub in active:
            try:
                sub.callback(metrics)
            except Exception:
                log.exception("Metrics subscriber error")
