"""GUI composition root — wires TrccApp + Qt adapter.

Single entry point for the graphical interface. Owns all DI wiring:
    TrccApp.init() → renderer → system_svc → setup → autostart → TRCCApp

TRCCApp knows nothing about TrccApp. It implements AppObserver and receives
devices via on_app_event. All adapter deps are injected here.
"""
from __future__ import annotations

import logging
import os
import signal
import sys

log = logging.getLogger(__name__)


def launch(verbosity: int = 0, decorated: bool = False,
           start_hidden: bool = False) -> int:
    """Bootstrap and run the GUI application.

    Returns the Qt exit code.
    """
    from trcc.core.app import TrccApp

    # ── Bootstrap core ────────────────────────────────────────────────────
    app = TrccApp.init(verbosity)

    # ── Renderer (LCD needs Qt surface) ──────────────────────────────────
    from trcc.adapters.render.qt import QtRenderer
    app.set_renderer(QtRenderer())

    # ── Platform deps ─────────────────────────────────────────────────────
    setup    = app.build_setup()
    autostart = app.build_autostart()
    mem_fn, disk_fn = app.build_hardware_fns()

    # ── Single-instance lock ──────────────────────────────────────────────
    lock = setup.acquire_instance_lock()
    if lock is None:
        setup.raise_existing_instance()
        return 0

    # ── System service (OS-specific sensors) ──────────────────────────────
    system_svc = app.build_system()
    app.set_system(system_svc)

    from trcc.services.system import set_instance
    set_instance(system_svc)

    # ── Qt bootstrap ──────────────────────────────────────────────────────
    from trcc.qt_components.assets import _PKG_ASSETS_DIR, set_assets_dir
    set_assets_dir(setup.resolve_assets_dir(_PKG_ASSETS_DIR))

    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.services=false")
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    os.environ.pop("QT_QPA_PLATFORM", None)  # clear offscreen set by CLI

    setup.configure_dpi()

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    qapp = QApplication(sys.argv)
    qapp.setQuitOnLastWindowClosed(False)
    qapp.setDesktopFileName("trcc-linux")
    qapp.setProperty("_instance_lock", lock)

    font = QFont("Microsoft YaHei", 10)
    if not font.exactMatch():
        font = QFont("Sans Serif", 10)
    qapp.setFont(font)

    # ── GUI adapter — receives everything injected, knows nothing of TrccApp ─
    from trcc.qt_components.trcc_app import TRCCApp
    window = TRCCApp(
        system_svc=system_svc,
        setup=setup,
        autostart=autostart,
        mem_fn=mem_fn,
        disk_fn=disk_fn,
        decorated=decorated,
    )

    # ── IPC server ────────────────────────────────────────────────────────
    from trcc.core.lcd_device import LCDDevice
    from trcc.ipc import IPCServer
    ipc_display = LCDDevice(device_svc=None)   # device wired later via on_app_event
    ipc_led = app.build_led()
    ipc_server = IPCServer(ipc_display, ipc_led)
    ipc_server.start()
    window._ipc_server = ipc_server

    # ── Register window as observer, scan, start metrics ─────────────────
    # scan() dispatches DEVICES_CHANGED → window.on_app_event → handlers created
    app.register(window)  # type: ignore[arg-type]
    app.scan()
    app.start_metrics_loop()

    # ── IPC raise + signals ───────────────────────────────────────────────
    signal.signal(signal.SIGINT, lambda *_: qapp.quit())
    setup.wire_ipc_raise(qapp, window)

    if not start_hidden:
        window.show()

    return qapp.exec()
