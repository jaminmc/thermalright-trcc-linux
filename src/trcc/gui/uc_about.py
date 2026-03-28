"""
PyQt6 UCAbout - Control Center / About panel.

Matches Windows TRCC.UCAbout (1274x800)
Shows auto-start, temperature unit, HDD toggle, refresh interval,
language selection, app info, and website link.

Windows controls (from UCAbout.cs):
- button1:      (297, 174) 14x14  Auto-start checkbox
- buttonC:      (297, 214) 14x14  Celsius radio
- buttonF:      (387, 214) 14x14  Fahrenheit radio
- buttonYP:     (297, 254) 14x14  HDD info checkbox
- textBoxTimer: (299, 291) 36x16  Refresh interval (1-100)
- Language checkboxes at y=413/443 (v2.1.4, shifted for Running Mode row)
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import webbrowser
from pathlib import Path
from threading import Thread
from urllib.request import urlopen

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QIntValidator
from PySide6.QtWidgets import QLabel, QLineEdit, QPushButton, QToolTip

from .assets import Assets
from .base import BasePanel, create_image_button, set_background_pixmap
from .constants import Layout, Sizes, Styles

log = logging.getLogger(__name__)

from trcc.core.ports import AutostartManager  # noqa: E402


def ensure_autostart(manager: AutostartManager) -> bool:
    """Auto-enable autostart on first launch; refresh on subsequent launches."""
    return manager.ensure()


_GITHUB_LATEST = (
    'https://api.github.com/repos/Lexonight1/thermalright-trcc-linux'
    '/releases/latest'
)


def _check_latest_release() -> tuple[str, dict[str, str]] | None:
    """Fetch latest GitHub release. Returns (version, {ext: download_url}) or None."""
    from urllib.request import Request
    try:
        req = Request(_GITHUB_LATEST, headers={'Accept': 'application/vnd.github+json'})
        with urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            tag = data.get('tag_name', '')
            ver = tag.lstrip('v') if tag else None
            if not ver:
                return None
            # Map file extensions to download URLs
            assets: dict[str, str] = {}
            for asset in data.get('assets', []):
                name = asset.get('name', '')
                url = asset.get('browser_download_url', '')
                if name.endswith('.pkg.tar.zst'):
                    assets['pacman'] = url
                elif name.endswith('.rpm'):
                    assets['dnf'] = url
                elif name.endswith('.deb'):
                    assets['apt'] = url
            return ver, assets
    except Exception:
        return None


def _parse_version(v: str) -> tuple[int, ...]:
    """Parse '3.0.9' into (3, 0, 9) for comparison."""
    return tuple(int(x) for x in v.split('.'))


def _detect_distro() -> str:
    """Detect the Linux distro ID (e.g. 'fedora', 'arch', 'ubuntu')."""
    try:
        with open('/etc/os-release') as f:
            for line in f:
                if line.startswith('ID='):
                    return line.strip().split('=', 1)[1].strip('"')
    except OSError:
        pass
    return 'unknown'


def _detect_install_method() -> str:
    """Detect how trcc-linux was installed.

    Returns 'pipx', 'pip', 'pacman', 'dnf', or 'apt'.
    """
    # pipx installs into its own venv
    if 'pipx' in sys.prefix:
        return 'pipx'
    try:
        from importlib.metadata import distribution
        dist = distribution('trcc-linux')
        installer = (dist.read_text('INSTALLER') or '').strip()
        if installer == 'pip':
            return 'pip'
    except Exception:
        pass
    # Detect which package manager installed it
    for mgr in ('pacman', 'dnf', 'apt'):
        if shutil.which(mgr):
            return mgr
    return 'pip'  # fallback


def _get_install_info() -> tuple[str, str]:
    """Get install method and distro. Detects and saves on first call."""
    from ..conf import Settings
    info = Settings.get_install_info()
    if info:
        return info['method'], info['distro']
    method = _detect_install_method()
    distro = _detect_distro()
    Settings.save_install_info(method, distro)
    log.info("Recorded install info: method=%s, distro=%s", method, distro)
    return method, distro


class UCAbout(BasePanel):
    """
    Control Center panel matching Windows UCAbout.

    Size: 1274x800 (same as FormCZTV content area).
    Background image is localized (A0关于{lang}.png).
    Interactive elements are invisible overlays on the background image text.
    """

    CMD_STARTUP = 0
    CMD_HDD_REFRESH = 16
    CMD_LANGUAGE = 32
    CMD_CLOSE = 255

    language_changed = Signal(str)       # lang suffix
    close_requested = Signal()
    temp_unit_changed = Signal(str)      # 'C' or 'F'
    startup_changed = Signal(bool)       # auto-start enabled
    hdd_toggle_changed = Signal(bool)    # HDD info enabled
    refresh_changed = Signal(int)        # refresh interval (seconds)
    _update_available = Signal(str, dict) # (version, {mgr: download_url})
    _upgrade_finished = Signal(bool)     # True=success, False=failure

    def __init__(self, parent=None, autostart_manager: AutostartManager | None = None):
        super().__init__(parent, width=Sizes.FORM_W, height=Sizes.FORM_H)

        self._autostart_manager = autostart_manager
        self._lang_buttons: dict[str, QPushButton] = {}  # Legacy — populated by combo in trcc_app
        self._temp_mode = 'C'
        self._autostart = autostart_manager.is_enabled() if autostart_manager else False
        from ..conf import settings
        self._read_hdd = settings.hdd_enabled
        self._refresh_interval = settings.refresh_interval

        # Load checkbox pixmaps
        sz = Layout.ABOUT_CHECKBOX_SIZE
        self._cb_off = Assets.load_pixmap(Assets.CHECKBOX_OFF, sz, sz)
        self._cb_on = Assets.load_pixmap(Assets.CHECKBOX_ON, sz, sz)

        self._setup_ui()
        self._apply_localized_background()

    def _apply_localized_background(self):
        """Set background image (no tiling)."""
        set_background_pixmap(self, Assets.ABOUT_BG)

    def _setup_ui(self):
        """Build UI with invisible click targets over background image text."""
        # Close / logout button (top-right)
        self.close_btn = create_image_button(
            self, *Layout.ABOUT_CLOSE_BTN,
            Assets.ABOUT_LOGOUT, Assets.ABOUT_LOGOUT_HOVER,
            fallback_text="X"
        )
        self.close_btn.clicked.connect(self._on_close)

        # === Auto-start checkbox (button1) ===
        self.startup_btn = self._make_checkbox(
            *Layout.ABOUT_STARTUP, checked=self._autostart)
        self.startup_btn.clicked.connect(self._on_startup_clicked)

        # === Temperature unit radio buttons ===
        self.celsius_btn = self._make_checkbox(*Layout.ABOUT_CELSIUS, checked=True)
        self.celsius_btn.clicked.connect(lambda: self._set_temp('C'))
        self.fahrenheit_btn = self._make_checkbox(*Layout.ABOUT_FAHRENHEIT)
        self.fahrenheit_btn.clicked.connect(lambda: self._set_temp('F'))

        # === HDD info checkbox (buttonYP) ===
        self.hdd_btn = self._make_checkbox(*Layout.ABOUT_HDD, checked=self._read_hdd)
        self.hdd_btn.clicked.connect(self._on_hdd_clicked)

        # === Data refresh interval input (textBoxTimer) ===
        self.refresh_input = QLineEdit(str(self._refresh_interval), self)
        self.refresh_input.setGeometry(*Layout.ABOUT_REFRESH_INPUT)
        self.refresh_input.setMaxLength(3)
        self.refresh_input.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.refresh_input.setValidator(QIntValidator(1, 100, self))
        self.refresh_input.setStyleSheet(
            "background-color: black; color: #B4964F; border: none;"
            " font-family: 'Microsoft YaHei'; font-size: 9pt;"
        )
        self.refresh_input.setToolTip("Data refresh interval (seconds)")
        self.refresh_input.editingFinished.connect(self._on_refresh_changed)

        # === Running Mode radio buttons (v2.1.4: buttonSingle / buttonMulti) ===
        # Visual-only — always multi-threaded on Linux (Qt signals handle threading)
        self.single_thread_btn = self._make_checkbox(
            *Layout.ABOUT_SINGLE_THREAD, checked=False)
        self.single_thread_btn.clicked.connect(lambda: self._set_thread_mode(False))
        self.multi_thread_btn = self._make_checkbox(
            *Layout.ABOUT_MULTI_THREAD, checked=True)
        self.multi_thread_btn.clicked.connect(lambda: self._set_thread_mode(True))

        # Website button (invisible, over background text area)
        self.website_btn = QPushButton(self)
        self.website_btn.setGeometry(*Layout.ABOUT_WEBSITE)
        self.website_btn.setFlat(True)
        self.website_btn.setStyleSheet(Styles.FLAT_BUTTON)
        self.website_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.website_btn.setToolTip("Open thermalright.com")
        self.website_btn.clicked.connect(
            lambda: webbrowser.open('https://www.thermalright.com'))

        # Version label
        from trcc.__version__ import __version__
        self.version_label = QLabel(__version__, self)
        self.version_label.setGeometry(*Layout.ABOUT_VERSION)
        self.version_label.setStyleSheet(
            "color: white; font-size: 16px; font-weight: bold; background: transparent;"
        )
        self.version_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        # === Software update area (buttonBCZT — dark icon baked into background) ===
        # Light overlay shown on top when update is available
        self._update_tooltip = "Running latest"
        self._update_rect = self.rect().__class__(  # QRect
            *Layout.ABOUT_UPDATE_BTN)

        # Overlay label — shows light update icon when update available
        self._update_overlay = QLabel(self)
        self._update_overlay.setGeometry(*Layout.ABOUT_UPDATE_BTN)
        px = Assets.load_pixmap(Assets.UPDATE_BTN, *Layout.ABOUT_UPDATE_BTN[2:])
        if not px.isNull():
            self._update_overlay.setPixmap(px)
        self._update_overlay.hide()

        # Invisible click target (always present over the baked-in dark icon)
        self.update_btn = QPushButton(self)
        self.update_btn.setGeometry(*Layout.ABOUT_UPDATE_BTN)
        self.update_btn.setFlat(True)
        self.update_btn.setStyleSheet(Styles.FLAT_BUTTON)
        self.update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.update_btn.installEventFilter(self)
        self.update_btn.clicked.connect(self._on_update_clicked)
        self._update_available.connect(self._on_update_result)
        self._upgrade_finished.connect(self._on_upgrade_done)
        self._latest_version: str | None = None
        self._install_method, self._distro = _get_install_info()

        # Check GitHub for updates in background, then every hour
        self._update_timer = QTimer(self)
        self._update_timer.timeout.connect(
            lambda: Thread(target=self._check_for_update, daemon=True).start())
        self._update_timer.start(60 * 60 * 1000)  # 1 hour
        Thread(target=self._check_for_update, daemon=True).start()

    def _show_update_tooltip(self):
        """Show tooltip to the right of the update button, vertically centered."""
        tip_pos = self.mapToGlobal(
            QPoint(self._update_rect.right() + 4,
                   self._update_rect.center().y() - 36))
        QToolTip.showText(tip_pos, self._update_tooltip, self,
                          self._update_rect)

    def event(self, e: QEvent) -> bool:
        """Show update tooltip to the right of the button area."""
        if e.type() == QEvent.Type.ToolTip:
            pos = e.pos()  # pyright: ignore[reportAttributeAccessIssue]
            if self._update_rect.contains(pos):
                self._show_update_tooltip()
                return True
        return super().event(e)

    def eventFilter(self, obj, e: QEvent) -> bool:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Intercept tooltip on update button to use same custom position."""
        if obj is self.update_btn and e.type() == QEvent.Type.ToolTip:
            self._show_update_tooltip()
            return True
        return super().eventFilter(obj, e)

    def _make_checkbox(self, x, y, w, h, checked=False):
        """Create a checkbox-style toggle button using Windows checkbox images."""
        btn = QPushButton(self)
        btn.setGeometry(x, y, w, h)
        btn.setFlat(True)
        btn.setCheckable(True)
        btn.setChecked(checked)
        btn.setStyleSheet(Styles.FLAT_BUTTON)

        if not self._cb_off.isNull() and not self._cb_on.isNull():
            icon = QIcon(self._cb_off)
            icon.addPixmap(self._cb_on, QIcon.Mode.Normal, QIcon.State.On)
            btn.setIcon(icon)
            btn.setIconSize(btn.size())
        return btn

    # --- Auto-start ---

    def _on_startup_clicked(self):
        """Toggle auto-start on login."""
        self._autostart = self.startup_btn.isChecked()
        if self._autostart_manager:
            if self._autostart:
                self._autostart_manager.enable()
            else:
                self._autostart_manager.disable()
        self.startup_changed.emit(self._autostart)
        self.invoke_delegate(self.CMD_STARTUP, self._autostart)

    # --- Temperature unit ---

    def _set_temp(self, mode: str):
        """Toggle temperature unit (radio behavior)."""
        self._temp_mode = mode
        self.celsius_btn.setChecked(mode == 'C')
        self.fahrenheit_btn.setChecked(mode == 'F')
        self.temp_unit_changed.emit(mode)

    @property
    def temp_mode(self):
        return self._temp_mode

    # --- HDD info ---

    def _on_hdd_clicked(self):
        """Toggle hard disk information reading."""
        self._read_hdd = self.hdd_btn.isChecked()
        self.hdd_toggle_changed.emit(self._read_hdd)
        self.invoke_delegate(self.CMD_HDD_REFRESH, self._read_hdd,
                             self._refresh_interval)

    @property
    def read_hdd(self):
        return self._read_hdd

    # --- Refresh interval ---

    def _on_refresh_changed(self):
        """Handle refresh interval input change (1-100 seconds)."""
        text = self.refresh_input.text().strip()
        if not text:
            self.refresh_input.setText("1")
            text = "1"
        val = max(1, min(100, int(text)))
        self.refresh_input.setText(str(val))
        self._refresh_interval = val
        self.refresh_changed.emit(val)
        self.invoke_delegate(self.CMD_HDD_REFRESH, self._read_hdd, val)

    @property
    def refresh_interval(self):
        return self._refresh_interval

    # --- Running Mode ---

    def _set_thread_mode(self, multi: bool):
        """Toggle running mode radio buttons (visual only, not wired)."""
        self.single_thread_btn.setChecked(not multi)
        self.multi_thread_btn.setChecked(multi)

    # --- Language ---

    def _on_lang_clicked(self, lang_suffix: str):
        """Handle language selection."""
        self.language_changed.emit(lang_suffix)

    # --- Software update ---

    # Install commands per package manager (pkexec provides the sudo prompt)
    _PKG_INSTALL: dict[str, list[str]] = {
        'pacman': ['pkexec', 'pacman', '-U', '--noconfirm'],
        'dnf':    ['pkexec', 'dnf', 'install', '-y'],
        'apt':    ['pkexec', 'apt', 'install', '-y'],
    }

    def _check_for_update(self):
        """Background thread: query GitHub releases and emit result via signal."""
        result = _check_latest_release()
        if result:
            ver, assets = result
            self._update_available.emit(ver, assets)

    def _on_update_result(self, latest: str, assets: dict[str, str]):
        """Handle version check result (runs on main thread via signal)."""
        from trcc.__version__ import __version__
        if _parse_version(latest) > _parse_version(__version__):
            self._latest_version = latest
            self._pkg_assets = assets
            self._update_tooltip = f"Version {latest} available — click to update"
            self._update_overlay.show()
            log.info("Update available: %s → %s", __version__, latest)

    def _on_update_clicked(self):
        """Perform update based on install method."""
        if not self._latest_version:
            return

        self._update_overlay.hide()
        self._update_tooltip = "Updating..."
        log.info("Starting %s upgrade to %s",
                 self._install_method, self._latest_version)
        Thread(target=self._run_upgrade, daemon=True).start()

    def _run_upgrade(self):
        """Background thread: run upgrade via pip/pipx/package manager."""
        import subprocess
        import tempfile

        from trcc.core.platform import SUBPROCESS_NO_WINDOW as _no_window
        method = self._install_method
        ver = self._latest_version or ""

        if method == 'pipx':
            cmd = ['pipx', 'upgrade', 'trcc-linux']
        elif method == 'pip':
            cmd = [sys.executable, '-m', 'pip', 'install',
                   '--upgrade', 'trcc-linux']
        elif method in self._PKG_INSTALL:
            # Download package from GitHub release, install via pkexec
            url = getattr(self, '_pkg_assets', {}).get(method)
            if not url:
                log.error("No %s package in release assets", method)
                self._upgrade_finished.emit(False)
                return
            raw_name = url.rsplit('/', 1)[-1]
            # Sanitize: strip path separators, reject traversal attempts
            filename = Path(raw_name).name
            if not filename or '..' in filename:
                log.error("Unsafe filename in release URL: %s", raw_name)
                self._upgrade_finished.emit(False)
                return
            pkg_path = Path(tempfile.mkdtemp(prefix='trcc_pkg_')) / filename
            try:
                from urllib.request import urlretrieve
                log.info("Downloading %s", url)
                urlretrieve(url, pkg_path)
            except Exception:
                log.error("Failed to download %s", url)
                self._upgrade_finished.emit(False)
                return
            cmd = [*self._PKG_INSTALL[method], str(pkg_path)]
        else:
            log.error("Unknown install method: %s", method)
            self._upgrade_finished.emit(False)
            return

        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True,
                           creationflags=_no_window)
            log.info("Upgrade to %s successful — restart to apply", ver)
            self._upgrade_finished.emit(True)
        except subprocess.CalledProcessError as e:
            log.error("Upgrade failed: %s", e.stderr)
            self._upgrade_finished.emit(False)

    def _on_upgrade_done(self, success: bool):
        """Post-upgrade: show restart message or re-enable button on failure."""
        if success:
            self._update_tooltip = "Updated — restart to apply"
        else:
            self._update_tooltip = (
                f"Version {self._latest_version} available — click to retry")
            self._update_overlay.show()

    # --- Close ---

    def _on_close(self):
        """Handle close/back button."""
        self.close_requested.emit()

    # --- Public API ---

    def sync_language(self):
        """Sync background to current settings.lang."""
        self._apply_localized_background()
