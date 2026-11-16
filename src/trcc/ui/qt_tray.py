"""Shared system-tray behaviour for the Qt UIs (gui + qtgui).

Both windows want the same tray: an icon with Show/Hide, a checkable
"Display on LCD", and Exit.  Click toggles visibility, and a window-close
hides to the tray instead of quitting — so the LCD keeps running.  Exit
closes that window only; ``trcc kill`` is what stops the App.  Unchecking
"Display on LCD" blanks the panel and stops updates; it does not stop the
App.  The check dispatches here, so both skins share one behaviour.
This lived only in ``ui/gui/trcc_app.py``; extracted here so both skins
share ONE implementation.

Composition, not a mixin: ``QMainWindow`` / ``QFrame`` + ``ABC`` raises a
metaclass ``TypeError`` (see ``BasePanel``), and a plain controller keeps the
tray policy in one testable place.  Each window owns its OWN cleanup on a real
quit — the controller only decides *hide-to-tray vs. real-quit*.

Usage::

    self._tray = TrayController(self, icon=...)
    self._tray.install()

    def closeEvent(self, event):
        if self._tray.intercept_close(event):
            return                       # diverted to the tray
        ...skin-specific cleanup...
        event.accept()                   # a genuine quit
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QCloseEvent, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from ..core.commands import PanelOutput, SetPanelOutput

log = logging.getLogger(__name__)


class TrayController:
    """Owns a window's tray icon + its hide-to-tray close behaviour."""

    def __init__(
        self,
        window: QWidget,
        *,
        icon: QIcon,
        tooltip: str = "TRCC Linux",
    ) -> None:
        log.debug("__init__: window=%s", window)
        self._window = window
        self._icon = icon
        self._tooltip = tooltip
        self._force_quit = False
        self._tray: QSystemTrayIcon | None = None
        self._display_action: QAction | None = None
        self._lcd_app: Any = None

    def install(
        self,
        *,
        app: Any = None,
        bus: Any = None,
        connection: Qt.ConnectionType = Qt.ConnectionType.QueuedConnection,
    ) -> None:
        """Create the tray icon + Show/Hide + Display on LCD + Exit, and show it.

        *app* and *bus* make the check the App's: the tray dispatches
        ``SetPanelOutput`` and follows ``PanelOutputChanged``, so a second
        window opens agreeing with the first.  Without them the check is
        local, which is what a test of hide-to-tray needs.
        """
        display_on = True
        if app is not None:
            shown = app.dispatch(PanelOutput())
            display_on = bool(shown.enabled)
            self._lcd_app = app
        log.info("TrayController.install: close hides to the tray, "
                 "display_on=%s", display_on)
        self._window.setWindowIcon(self._icon)
        tray = QSystemTrayIcon(self._icon, self._window)
        tray.setToolTip(self._tooltip)
        menu = QMenu()
        if (show_action := menu.addAction("Show/Hide")):
            show_action.triggered.connect(self.toggle_visibility)
        if (display := menu.addAction("Display on LCD")):
            display.setCheckable(True)
            display.setChecked(display_on)
            display.toggled.connect(self._on_display_toggled)
            self._display_action = display
        menu.addSeparator()
        if (exit_action := menu.addAction("Exit")):
            exit_action.triggered.connect(self.request_quit)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_activated)
        tray.show()
        self._tray = tray
        if bus is not None:
            bus.panel_output_changed.connect(self._on_lcd_display, type=connection)

    def _on_lcd_display(self, event: object) -> None:
        """Another window, or this one's own command, moved the switch."""
        enabled = bool(getattr(event, "enabled", True))
        log.info("TrayController: LCD display is %s", enabled)
        self.show_lcd_display(enabled)

    def show_lcd_display(self, enabled: bool) -> None:
        """Move the check to *enabled* without asking the handler again."""
        log.info("TrayController.show_lcd_display: %s", enabled)
        action = self._display_action
        if action is None or action.isChecked() == enabled:
            return
        action.blockSignals(True)
        action.setChecked(enabled)
        action.blockSignals(False)

    def _on_display_toggled(self, checked: bool) -> None:
        log.info("TrayController: Display on LCD -> %s", checked)
        app = self._lcd_app
        if app is None:
            log.info("TrayController: no App for the LCD switch")
            return
        result = app.dispatch(SetPanelOutput(enabled=checked))
        if not result.ok:
            log.warning("TrayController: %s", result.message)
            self.notify("LCD display", result.message)
        self.show_lcd_display(result.enabled)

    # ── Actions ───────────────────────────────────────────────────────

    def _on_activated(self, reason: Any) -> None:
        log.info("TrayController: activated reason=%s", reason)
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_visibility()

    def toggle_visibility(self) -> None:
        if self._window.isVisible():
            log.info("TrayController.toggle_visibility: hide")
            self._window.hide()
        else:
            self.raise_window()

    def raise_window(self) -> None:
        log.info("TrayController.raise_window")
        self._window.show()
        self._window.activateWindow()
        self._window.raise_()

    def request_quit(self) -> None:
        log.info("TrayController.request_quit")
        self._force_quit = True
        self._window.close()

    def notify(self, title: str, message: str, msecs: int = 8000) -> None:
        log.debug("notify: title=%s message=%s", title, message)
        if self._tray is not None and QSystemTrayIcon.isSystemTrayAvailable():
            self._tray.showMessage(
                title, message, QSystemTrayIcon.MessageIcon.Warning, msecs,
            )

    # ── Close ─────────────────────────────────────────────────────────

    def intercept_close(self, event: QCloseEvent) -> bool:
        """Divert a window-close to the tray, or let it proceed to a real quit.

        Returns ``True`` when the close was diverted (the caller must return
        early); ``False`` when this is a genuine quit (the caller does its own
        cleanup and accepts the event).

        Every OS hides — the C# oracle's own close button does exactly that
        (``Form1.cs:784``).  Windows used to MINIMISE instead, behind a flag
        only a tray restore cleared: restore from the taskbar, close again,
        and the app quit (measured on the win11 VM).
        """
        if (
            not self._force_quit
            and self._tray is not None
            and self._tray.isSystemTrayAvailable()
            and self._tray.isVisible()
        ):
            event.ignore()
            log.info("TrayController.intercept_close: hide to tray")
            self._window.hide()
            return True
        log.info("TrayController.intercept_close: real quit")
        if self._tray is not None:
            self._tray.hide()
        return False
