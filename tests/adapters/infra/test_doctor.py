"""Tests for trcc doctor — dependency health check."""

from __future__ import annotations

import sys
import unittest
from collections import namedtuple
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from trcc.adapters.infra.facade_doctor import (
    SelinuxResult,
    _check_binary,
    _check_library,
    _check_python_module,
    _check_rapl_permissions,
    _check_udev_rules,
    _detect_pkg_manager,
    _install_hint,
    _provides_search,
    _read_os_release,
    _selinux_usb_access_allowed,
    check_desktop_entry,
    check_gpu,
    check_polkit,
    check_rapl,
    check_selinux,
    check_system_deps,
    check_udev,
    get_module_version,
    run_doctor,
)

# ── Distro detection ────────────────────────────────────────────────────────


class TestReadOsRelease(unittest.TestCase):
    """Test os-release parsing."""

    @patch('trcc.adapters.infra.facade_doctor.platform.freedesktop_os_release',
           return_value={'ID': 'fedora', 'PRETTY_NAME': 'Fedora 43'})
    def test_uses_platform_api(self, mock_rel):
        result = _read_os_release()
        self.assertEqual(result['ID'], 'fedora')
        mock_rel.assert_called_once()

    @patch('trcc.adapters.infra.facade_doctor.platform.freedesktop_os_release', side_effect=OSError)
    @patch('trcc.adapters.infra.facade_doctor.os.path.isfile', return_value=False)
    def test_fallback_returns_empty(self, _isfile, _rel):
        result = _read_os_release()
        self.assertEqual(result, {})


class TestDetectPkgManager(unittest.TestCase):
    """Test distro → package manager mapping."""

    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'ID': 'fedora', 'ID_LIKE': ''})
    def test_fedora(self, _):
        self.assertEqual(_detect_pkg_manager(), 'dnf')

    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'ID': 'ubuntu', 'ID_LIKE': 'debian'})
    def test_ubuntu(self, _):
        self.assertEqual(_detect_pkg_manager(), 'apt')

    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'ID': 'arch', 'ID_LIKE': ''})
    def test_arch(self, _):
        self.assertEqual(_detect_pkg_manager(), 'pacman')

    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'ID': 'pop', 'ID_LIKE': 'ubuntu debian'})
    def test_pop_os(self, _):
        self.assertEqual(_detect_pkg_manager(), 'apt')

    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'ID': 'nobara', 'ID_LIKE': 'fedora'})
    def test_nobara(self, _):
        self.assertEqual(_detect_pkg_manager(), 'dnf')

    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'ID': 'cachyos', 'ID_LIKE': 'arch'})
    def test_cachyos_id_like_fallback(self, _):
        self.assertEqual(_detect_pkg_manager(), 'pacman')

    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'ID': 'unknowndistro', 'ID_LIKE': ''})
    def test_unknown_returns_none(self, _):
        self.assertIsNone(_detect_pkg_manager())

    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'ID': 'zorin', 'ID_LIKE': 'ubuntu debian'})
    def test_zorin(self, _):
        self.assertEqual(_detect_pkg_manager(), 'apt')

    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'ID': 'void', 'ID_LIKE': ''})
    def test_void(self, _):
        self.assertEqual(_detect_pkg_manager(), 'xbps')

    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'ID': 'opensuse-tumbleweed', 'ID_LIKE': 'suse'})
    def test_opensuse(self, _):
        self.assertEqual(_detect_pkg_manager(), 'zypper')


# ── _provides_search ────────────────────────────────────────────────────────


class TestProvidesSearch:
    """_provides_search — all PM variants and edge cases."""

    @patch("subprocess.run")
    def test_dnf_parses_package_name(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout="sg3_utils-1.47-3.fc43.x86_64 : Utilities for SCSI\n",
        )
        result = _provides_search("sg_raw", "dnf")
        assert result is not None
        assert "sg3_utils" in result

    @patch("subprocess.run")
    def test_dnf_no_match_returns_none(self, mock_run):
        mock_run.return_value = Mock(returncode=1, stdout="")
        result = _provides_search("sg_raw", "dnf")
        assert result is None

    @patch("subprocess.run")
    def test_dnf_returncode_nonzero(self, mock_run):
        mock_run.return_value = Mock(returncode=1, stdout="some output\n")
        result = _provides_search("sg_raw", "dnf")
        assert result is None

    @patch("subprocess.run")
    def test_pacman_parses_package_name(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="extra/sg3_utils\n")
        result = _provides_search("sg_raw", "pacman")
        assert result == "sg3_utils"

    @patch("subprocess.run")
    def test_pacman_no_slash(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="sg3_utils\n")
        result = _provides_search("sg_raw", "pacman")
        assert result == "sg3_utils"

    @patch("subprocess.run")
    def test_pacman_empty_output(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="   \n")
        result = _provides_search("sg_raw", "pacman")
        assert result is None

    @patch("subprocess.run")
    def test_zypper_parses_table_row(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout=(
                "Loading repository data...\n"
                "S | Name     | Summary       | Type\n"
                "--+----------+---------------+------\n"
                "  | sg3_utils | SCSI tools   | package\n"
            ),
        )
        result = _provides_search("sg_raw", "zypper")
        assert result == "sg3_utils"

    @patch("subprocess.run")
    def test_zypper_no_table_rows(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="No packages found.\n")
        result = _provides_search("sg_raw", "zypper")
        assert result is None

    @patch("subprocess.run")
    def test_zypper_returncode_nonzero(self, mock_run):
        mock_run.return_value = Mock(returncode=1, stdout="")
        result = _provides_search("sg_raw", "zypper")
        assert result is None

    @patch("subprocess.run")
    def test_apk_parses_package_name(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="p7zip-17.05-r0\n")
        result = _provides_search("7z", "apk")
        assert result == "p7zip"

    @patch("subprocess.run")
    def test_apk_empty_output(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="")
        result = _provides_search("7z", "apk")
        assert result is None

    @patch("subprocess.run")
    def test_xbps_parses_package_name(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout="[*] sg3_utils-1.47_1  Utilities for SCSI\n",
        )
        result = _provides_search("sg_raw", "xbps")
        assert result is not None

    @patch("subprocess.run")
    def test_xbps_no_match(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="nothing here\n")
        result = _provides_search("sg_raw", "xbps")
        assert result is None

    @patch("subprocess.run")
    def test_timeout_returns_none(self, mock_run):
        import subprocess as _subprocess
        mock_run.side_effect = _subprocess.TimeoutExpired(cmd="dnf", timeout=15)
        result = _provides_search("sg_raw", "dnf")
        assert result is None

    @patch("subprocess.run")
    def test_file_not_found_returns_none(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        result = _provides_search("sg_raw", "pacman")
        assert result is None

    def test_unsupported_pm_returns_none(self):
        result = _provides_search("sg_raw", "emerge")
        assert result is None

    def test_apt_returns_none(self):
        result = _provides_search("sg_raw", "apt")
        assert result is None


# ── Install hints ────────────────────────────────────────────────────────────


class TestInstallHint(unittest.TestCase):
    """Test distro-specific install command generation."""

    def test_fedora_sg_raw(self):
        hint = _install_hint('sg_raw', 'dnf')
        self.assertIn('dnf install', hint)
        self.assertIn('sg3_utils', hint)

    def test_apt_7z(self):
        hint = _install_hint('7z', 'apt')
        self.assertIn('apt install', hint)
        self.assertIn('p7zip-full', hint)

    def test_unknown_pm_shows_all(self):
        hint = _install_hint('sg_raw', None)
        self.assertIn('install one of:', hint)

    def test_unknown_dep(self):
        hint = _install_hint('nonexistent', 'dnf')
        self.assertEqual(hint, 'install nonexistent')

    def test_checkmodule_dnf(self):
        hint = _install_hint('checkmodule', 'dnf')
        self.assertIn('dnf install', hint)
        self.assertIn('checkpolicy', hint)

    def test_checkmodule_apt(self):
        hint = _install_hint('checkmodule', 'apt')
        self.assertIn('apt install', hint)
        self.assertIn('checkpolicy', hint)

    def test_checkmodule_rpm_ostree(self):
        hint = _install_hint('checkmodule', 'rpm-ostree')
        self.assertIn('rpm-ostree install', hint)
        self.assertIn('checkpolicy', hint)

    def test_semodule_package_apt(self):
        hint = _install_hint('semodule_package', 'apt')
        self.assertIn('apt install', hint)
        self.assertIn('semodule-utils', hint)

    def test_semodule_package_dnf(self):
        hint = _install_hint('semodule_package', 'dnf')
        self.assertIn('dnf install', hint)
        self.assertIn('policycoreutils', hint)


class TestInstallHintExtra:
    """_install_hint — additional branches via _provides_search fallback."""

    @patch("trcc.adapters.infra.facade_doctor._provides_search", return_value="sg3_utils")
    def test_provides_search_fallback_used(self, mock_search):
        hint = _install_hint("totally_unknown_tool", "pacman")
        assert "pacman" in hint
        assert "sg3_utils" in hint

    @patch("trcc.adapters.infra.facade_doctor._provides_search", return_value=None)
    def test_provides_search_returns_none_falls_to_generic(self, _):
        hint = _install_hint("totally_unknown_tool", "pacman")
        assert hint == "install totally_unknown_tool"

    def test_pm_none_dep_in_map_shows_all(self):
        hint = _install_hint("sg_raw", None)
        assert "install one of:" in hint
        assert "dnf" in hint

    def test_pm_none_dep_not_in_map(self):
        hint = _install_hint("nonexistent_dep_xyz", None)
        assert hint == "install nonexistent_dep_xyz"

    def test_pacman_sg_raw_mapped(self):
        hint = _install_hint("sg_raw", "pacman")
        assert "pacman" in hint
        assert "sg3_utils" in hint

    def test_zypper_7z_mapped(self):
        hint = _install_hint("7z", "zypper")
        assert "zypper" in hint
        assert "p7zip-full" in hint

    def test_xbps_ffmpeg_mapped(self):
        hint = _install_hint("ffmpeg", "xbps")
        assert "xbps" in hint
        assert "ffmpeg" in hint

    def test_apk_7z_mapped(self):
        hint = _install_hint("7z", "apk")
        assert "apk" in hint
        assert "7zip" in hint


# ── Check helpers ────────────────────────────────────────────────────────────


class TestCheckPythonModule(unittest.TestCase):
    """Test Python module availability checking."""

    def test_installed_module(self):
        result = _check_python_module('os', 'os', required=True, pm=None)
        self.assertTrue(result)

    def test_missing_required(self):
        result = _check_python_module(
            'nonexistent', 'nonexistent_pkg_xyz', required=True, pm=None)
        self.assertFalse(result)

    def test_missing_optional(self):
        result = _check_python_module(
            'nonexistent', 'nonexistent_pkg_xyz', required=False, pm=None)
        self.assertTrue(result)


class TestCheckBinary(unittest.TestCase):
    """Test binary availability checking."""

    @patch('shutil.which', return_value='/usr/bin/7z')
    def test_found(self, _):
        result = _check_binary('7z', required=True, pm='dnf')
        self.assertTrue(result)

    @patch('shutil.which', return_value=None)
    def test_missing_required(self, _):
        result = _check_binary('7z', required=True, pm='dnf')
        self.assertFalse(result)

    @patch('shutil.which', return_value=None)
    def test_missing_optional(self, _):
        result = _check_binary('ffmpeg', required=False, pm='apt')
        self.assertTrue(result)


class TestCheckLibrary(unittest.TestCase):
    """Test shared library checking."""

    @patch('ctypes.util.find_library', return_value='libusb-1.0.so.0')
    def test_found(self, _):
        result = _check_library(
            'libusb-1.0', 'usb-1.0', required=True, pm='dnf', dep_key='libusb')
        self.assertTrue(result)

    @patch('ctypes.util.find_library', return_value=None)
    def test_missing_required(self, _):
        result = _check_library(
            'libusb-1.0', 'usb-1.0', required=True, pm='dnf', dep_key='libusb')
        self.assertFalse(result)


class TestCheckUdevRules(unittest.TestCase):
    """Test udev rules check."""

    @patch('trcc.adapters.infra.facade_doctor.os.path.isfile', return_value=True)
    def test_rules_exist(self, _):
        self.assertTrue(_check_udev_rules())

    @patch('trcc.adapters.infra.facade_doctor.os.path.isfile', return_value=False)
    def test_rules_missing(self, _):
        self.assertFalse(_check_udev_rules())


# ── get_module_version ──────────────────────────────────────────────────────


class TestGetModuleVersion:
    """get_module_version — version attribute handling."""

    def test_real_module_returns_version(self):
        ver = get_module_version("os")
        assert ver is not None

    def test_missing_module_returns_none(self):
        ver = get_module_version("totally_nonexistent_module_xyz")
        assert ver is None

    def test_tuple_version_joined(self):
        fake_mod = MagicMock()
        fake_mod.__version__ = (1, 2, 3)
        with patch("builtins.__import__", return_value=fake_mod):
            ver = get_module_version("fake")
        assert ver == "1.2.3"

    def test_string_version_returned_as_is(self):
        fake_mod = MagicMock()
        fake_mod.__version__ = "6.5.1"
        with patch("builtins.__import__", return_value=fake_mod):
            ver = get_module_version("fake")
        assert ver == "6.5.1"

    def test_empty_version_attribute_returns_empty_string(self):
        fake_mod = MagicMock()
        fake_mod.__version__ = ""
        fake_mod.version = ""
        with patch("builtins.__import__", return_value=fake_mod):
            ver = get_module_version("fake")
        assert ver == ""

    def test_version_attribute_fallback(self):
        fake_mod = MagicMock(spec=[])
        fake_mod.version = "2.0"
        with patch("builtins.__import__", return_value=fake_mod):
            ver = get_module_version("fake")
        assert ver == "2.0"

    def test_pyside6_special_case(self):
        fake_mod = MagicMock()
        fake_mod.__version__ = ""
        fake_mod.version = ""

        import types
        fake_pyside6 = types.ModuleType("PySide6")
        fake_pyside6.__version__ = "6.7.0"  # type: ignore[attr-defined]

        with patch("builtins.__import__", return_value=fake_mod):
            with patch.dict("sys.modules", {"PySide6": fake_pyside6}):
                ver = get_module_version("PySide6")
        assert ver is not None


# ── check_system_deps ───────────────────────────────────────────────────────


class TestCheckSystemDeps:
    """check_system_deps — structured result list."""

    def test_returns_list_of_dep_results(self):
        with (
            patch("trcc.adapters.infra.facade_doctor._detect_pkg_manager", return_value="dnf"),
            patch("trcc.adapters.infra.facade_doctor.get_module_version", return_value="1.0"),
            patch("trcc.adapters.infra.facade_doctor.ctypes.util.find_library", return_value="libusb"),
            patch("trcc.adapters.infra.facade_doctor.shutil.which", return_value="/usr/bin/sg_raw"),
        ):
            results = check_system_deps("dnf")
        names = [r.name for r in results]
        assert "Python" in names
        assert "PySide6" in names
        assert "pyusb" in names
        assert "libusb-1.0" in names
        assert "sg_raw" in names
        assert "7z" in names
        assert "ffmpeg" in names

    def test_python_version_ok(self):
        results = check_system_deps(pm=None)
        py = next(r for r in results if r.name == "Python")
        assert py.ok is True

    def test_python_version_too_old(self):
        VersionInfo = namedtuple("version_info", ["major", "minor", "micro",
                                                   "releaselevel", "serial"])
        fake_info = VersionInfo(3, 7, 0, "final", 0)
        with patch.object(sys, "version_info", fake_info):
            results = check_system_deps(pm=None)
        py = next(r for r in results if r.name == "Python")
        assert py.ok is False
        assert "3.9" in py.note

    def test_apt_adds_xcb_dep(self):
        with (
            patch("trcc.adapters.infra.facade_doctor._detect_pkg_manager", return_value="apt"),
            patch("trcc.adapters.infra.facade_doctor.get_module_version", return_value="1.0"),
            patch("trcc.adapters.infra.facade_doctor.ctypes.util.find_library", return_value="lib"),
            patch("trcc.adapters.infra.facade_doctor.shutil.which", return_value="/usr/bin/x"),
        ):
            results = check_system_deps("apt")
        names = [r.name for r in results]
        assert "libxcb-cursor" in names

    def test_non_apt_no_xcb_dep(self):
        with (
            patch("trcc.adapters.infra.facade_doctor._detect_pkg_manager", return_value="dnf"),
            patch("trcc.adapters.infra.facade_doctor.get_module_version", return_value="1.0"),
            patch("trcc.adapters.infra.facade_doctor.ctypes.util.find_library", return_value="lib"),
            patch("trcc.adapters.infra.facade_doctor.shutil.which", return_value="/usr/bin/x"),
        ):
            results = check_system_deps("dnf")
        names = [r.name for r in results]
        assert "libxcb-cursor" not in names

    def test_missing_module_marked_not_ok(self):
        def mock_ver(imp):
            return None if imp == "usb.core" else "1.0"

        with (
            patch("trcc.adapters.infra.facade_doctor.get_module_version", side_effect=mock_ver),
            patch("trcc.adapters.infra.facade_doctor.ctypes.util.find_library", return_value="lib"),
            patch("trcc.adapters.infra.facade_doctor.shutil.which", return_value="/usr/bin/x"),
        ):
            results = check_system_deps("dnf")
        pyusb = next(r for r in results if r.name == "pyusb")
        assert pyusb.ok is False

    def test_hidapi_optional_not_ok_still_included(self):
        def mock_ver(imp):
            return None if imp == "hid" else "1.0"

        with (
            patch("trcc.adapters.infra.facade_doctor.get_module_version", side_effect=mock_ver),
            patch("trcc.adapters.infra.facade_doctor.ctypes.util.find_library", return_value="lib"),
            patch("trcc.adapters.infra.facade_doctor.shutil.which", return_value="/usr/bin/x"),
        ):
            results = check_system_deps("dnf")
        hid = next(r for r in results if r.name == "hidapi")
        assert hid.required is False

    def test_pm_none_auto_detected(self):
        with (
            patch("trcc.adapters.infra.facade_doctor._detect_pkg_manager", return_value="apt") as mock_pm,
            patch("trcc.adapters.infra.facade_doctor.get_module_version", return_value="1.0"),
            patch("trcc.adapters.infra.facade_doctor.ctypes.util.find_library", return_value="lib"),
            patch("trcc.adapters.infra.facade_doctor.shutil.which", return_value="/usr/bin/x"),
        ):
            check_system_deps(pm=None)
        mock_pm.assert_called_once()


# ── check_gpu ───────────────────────────────────────────────────────────────


def _make_gpu_dev_dir(class_text: str, vendor_text: str,
                      class_exists: bool = True,
                      class_raises: Exception | None = None) -> MagicMock:
    """Build a mock PCI device directory for check_gpu tests."""
    class_p = MagicMock()
    class_p.exists.return_value = class_exists
    if class_raises:
        class_p.read_text.side_effect = class_raises
    else:
        class_p.read_text.return_value = class_text

    vendor_p = MagicMock()
    vendor_p.exists.return_value = True
    vendor_p.read_text.return_value = vendor_text

    dev_dir = MagicMock()
    dev_dir.__truediv__ = lambda s, name: (
        class_p if name == "class" else vendor_p
    )
    return dev_dir


class TestCheckGpu:
    """check_gpu — PCI sysfs scanning."""

    @patch("pathlib.Path")
    def test_no_pci_sysfs(self, MockPath):
        mock_base = MagicMock()
        mock_base.exists.return_value = False
        MockPath.return_value = mock_base
        result = check_gpu()
        assert result == []

    @patch("trcc.adapters.infra.facade_doctor.get_module_version", return_value="11.0")
    @patch("pathlib.Path")
    def test_nvidia_detected_pynvml_installed(self, MockPath, mock_ver):
        mock_base = MagicMock()
        mock_base.exists.return_value = True
        mock_base.iterdir.return_value = [
            _make_gpu_dev_dir("0x030000", "0x10de"),
        ]
        MockPath.return_value = mock_base
        results = check_gpu()
        assert any(g.vendor == "nvidia" for g in results)
        nvidia = next(g for g in results if g.vendor == "nvidia")
        assert nvidia.package_installed is True

    @patch("trcc.adapters.infra.facade_doctor.get_module_version", return_value=None)
    @patch("pathlib.Path")
    def test_nvidia_detected_pynvml_missing(self, MockPath, mock_ver):
        mock_base = MagicMock()
        mock_base.exists.return_value = True
        mock_base.iterdir.return_value = [
            _make_gpu_dev_dir("0x030000", "0x10de"),
        ]
        MockPath.return_value = mock_base
        results = check_gpu()
        nvidia = next(g for g in results if g.vendor == "nvidia")
        assert nvidia.package_installed is False
        assert "pip install" in nvidia.install_cmd

    @patch("pathlib.Path")
    def test_amd_detected(self, MockPath):
        mock_base = MagicMock()
        mock_base.exists.return_value = True
        mock_base.iterdir.return_value = [
            _make_gpu_dev_dir("0x030200", "0x1002"),
        ]
        MockPath.return_value = mock_base
        results = check_gpu()
        assert any(g.vendor == "amd" for g in results)

    @patch("pathlib.Path")
    def test_intel_detected(self, MockPath):
        mock_base = MagicMock()
        mock_base.exists.return_value = True
        mock_base.iterdir.return_value = [
            _make_gpu_dev_dir("0x030000", "0x8086"),
        ]
        MockPath.return_value = mock_base
        results = check_gpu()
        assert any(g.vendor == "intel" for g in results)

    @patch("pathlib.Path")
    def test_non_gpu_pci_class_ignored(self, MockPath):
        mock_base = MagicMock()
        mock_base.exists.return_value = True
        mock_base.iterdir.return_value = [
            _make_gpu_dev_dir("0x020000", "0x10de"),
        ]
        MockPath.return_value = mock_base
        results = check_gpu()
        assert results == []

    @patch("pathlib.Path")
    def test_oserror_on_read_skipped(self, MockPath):
        mock_base = MagicMock()
        mock_base.exists.return_value = True
        mock_base.iterdir.return_value = [
            _make_gpu_dev_dir("", "0x10de", class_raises=OSError("denied")),
        ]
        MockPath.return_value = mock_base
        results = check_gpu()
        assert results == []

    @patch("pathlib.Path")
    def test_missing_class_file_skipped(self, MockPath):
        mock_base = MagicMock()
        mock_base.exists.return_value = True
        mock_base.iterdir.return_value = [
            _make_gpu_dev_dir("0x030000", "0x10de", class_exists=False),
        ]
        MockPath.return_value = mock_base
        results = check_gpu()
        assert results == []


# ── check_udev ──────────────────────────────────────────────────────────────


class TestCheckUdev:
    """check_udev — structured result."""

    @patch("trcc.adapters.infra.facade_doctor.os.path.isfile", return_value=False)
    def test_file_missing(self, _):
        result = check_udev()
        assert result.ok is False
        assert "not installed" in result.message

    @patch("trcc.adapters.infra.facade_doctor.os.path.isfile", return_value=True)
    def test_all_vids_present(self, _):
        from trcc.adapters.detection.factory_detector import DeviceDetector
        all_registries = DeviceDetector._get_all_registries()
        all_vids = {f"{vid:04x}" for vid, _ in all_registries}
        content = " ".join(all_vids)

        from unittest.mock import mock_open as _mock_open
        with patch("builtins.open", _mock_open(read_data=content)):
            with patch(
                "trcc.adapters.device.detector.DeviceDetector._get_all_registries",
                return_value=list(all_registries),
            ):
                result = check_udev()
        assert result.ok is True
        assert result.missing_vids == []

    @patch("trcc.adapters.infra.facade_doctor.os.path.isfile", return_value=True)
    def test_missing_vid_in_file(self, _):
        from trcc.adapters.detection.factory_detector import DeviceDetector
        all_registries = DeviceDetector._get_all_registries()

        from unittest.mock import mock_open as _mock_open
        with patch("builtins.open", _mock_open(read_data="no vids here")):
            with patch(
                "trcc.adapters.device.detector.DeviceDetector._get_all_registries",
                return_value=list(all_registries),
            ):
                result = check_udev()
        assert result.ok is False
        assert len(result.missing_vids) > 0

    @patch("trcc.adapters.infra.facade_doctor.os.path.isfile", return_value=True)
    def test_open_exception_returns_ok(self, _):
        with patch("builtins.open", side_effect=PermissionError):
            result = check_udev()
        assert result.ok is True


# ── SELinux ─────────────────────────────────────────────────────────────────


class TestCheckSelinux(unittest.TestCase):
    """Test SELinux policy check."""

    @patch('subprocess.run', side_effect=FileNotFoundError)
    def test_no_selinux(self, _):
        r = check_selinux()
        self.assertTrue(r.ok)
        self.assertFalse(r.enforcing)
        self.assertIn('not installed', r.message)

    @patch('subprocess.run')
    def test_permissive(self, mock_run):
        mock_run.return_value = Mock(stdout='Permissive\n')
        r = check_selinux()
        self.assertTrue(r.ok)
        self.assertFalse(r.enforcing)

    @patch('subprocess.run')
    def test_enforcing_module_loaded(self, mock_run):
        def side_effect(cmd, **_kw):
            if cmd[0] == 'getenforce':
                return Mock(stdout='Enforcing\n')
            if cmd[0] == 'semodule':
                return Mock(stdout='trcc_usb\nother_mod\n', returncode=0)
            return Mock(stdout='', returncode=0)
        mock_run.side_effect = side_effect
        r = check_selinux()
        self.assertTrue(r.ok)
        self.assertTrue(r.enforcing)
        self.assertTrue(r.module_loaded)

    @patch('subprocess.run')
    def test_enforcing_sesearch_fallback(self, mock_run):
        def side_effect(cmd, **_kw):
            if cmd[0] == 'getenforce':
                return Mock(stdout='Enforcing\n')
            if cmd[0] == 'semodule':
                return Mock(stdout='', returncode=1)
            if cmd[0] == 'sesearch':
                return Mock(
                    stdout='allow unconfined_t usb_device_t:chr_file '
                           '{ ioctl open read write };',
                    returncode=0,
                )
            return Mock(stdout='', returncode=1)
        mock_run.side_effect = side_effect
        r = check_selinux()
        self.assertTrue(r.ok)
        self.assertTrue(r.enforcing)

    @patch('subprocess.run')
    def test_enforcing_module_missing(self, mock_run):
        def side_effect(cmd, **_kw):
            if cmd[0] == 'getenforce':
                return Mock(stdout='Enforcing\n')
            if cmd[0] == 'semodule':
                return Mock(stdout='other_mod\n', returncode=0)
            if cmd[0] == 'sesearch':
                return Mock(stdout='', returncode=1)
            return Mock(stdout='', returncode=1)
        mock_run.side_effect = side_effect
        r = check_selinux()
        self.assertFalse(r.ok)
        self.assertTrue(r.enforcing)
        self.assertFalse(r.module_loaded)
        self.assertIn('not installed', r.message)

    @patch('subprocess.run')
    def test_enforcing_semodule_not_found(self, mock_run):
        def side_effect(cmd, **_kw):
            if cmd[0] == 'getenforce':
                return Mock(stdout='Enforcing\n')
            raise FileNotFoundError
        mock_run.side_effect = side_effect
        r = check_selinux()
        self.assertFalse(r.ok)
        self.assertTrue(r.enforcing)
        self.assertFalse(r.module_loaded)


class TestSelinuxUsbAccessAllowed:
    """_selinux_usb_access_allowed — sesearch parsing."""

    @patch("subprocess.run")
    def test_all_perms_present_returns_true(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout="allow unconfined_t usb_device_t:chr_file { ioctl open read write };\n",
        )
        assert _selinux_usb_access_allowed() is True

    @patch("subprocess.run")
    def test_missing_one_perm_returns_false(self, mock_run):
        mock_run.return_value = Mock(
            returncode=0,
            stdout="allow unconfined_t usb_device_t:chr_file { ioctl open read };\n",
        )
        assert _selinux_usb_access_allowed() is False

    @patch("subprocess.run")
    def test_returncode_nonzero_returns_false(self, mock_run):
        mock_run.return_value = Mock(returncode=1, stdout="")
        assert _selinux_usb_access_allowed() is False

    @patch("subprocess.run")
    def test_empty_stdout_returns_false(self, mock_run):
        mock_run.return_value = Mock(returncode=0, stdout="")
        assert _selinux_usb_access_allowed() is False

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_sesearch_not_found(self, _):
        assert _selinux_usb_access_allowed() is False

    @patch("subprocess.run", side_effect=OSError("timeout"))
    def test_oserror_returns_false(self, _):
        assert _selinux_usb_access_allowed() is False


# ── RAPL permissions ─────────────────────────────────────────────────────────


class TestCheckRaplPermissions(unittest.TestCase):
    """Test _check_rapl_permissions() diagnostics."""

    @patch('os.path.isdir', return_value=False)
    def test_no_powercap_returns_true(self, _):
        self.assertTrue(_check_rapl_permissions())

    @patch('os.access', return_value=True)
    @patch('os.path.isdir', return_value=True)
    @patch('pathlib.Path.glob')
    def test_rapl_readable(self, mock_glob, mock_isdir, mock_access):
        mock_energy = Mock(spec=Path)
        mock_energy.__str__ = lambda s: '/sys/class/powercap/intel-rapl:0/energy_uj'
        mock_glob.return_value = [mock_energy]
        self.assertTrue(_check_rapl_permissions())

    @patch('os.access', return_value=False)
    @patch('os.path.isdir', return_value=True)
    @patch('pathlib.Path.glob')
    def test_rapl_not_readable(self, mock_glob, mock_isdir, mock_access):
        mock_energy = Mock(spec=Path)
        mock_energy.__str__ = lambda s: '/sys/class/powercap/intel-rapl:0/energy_uj'
        mock_glob.return_value = [mock_energy]
        self.assertFalse(_check_rapl_permissions())

    @patch('os.path.isdir', return_value=True)
    @patch('pathlib.Path.glob', return_value=[])
    def test_no_rapl_domains(self, mock_glob, _):
        self.assertTrue(_check_rapl_permissions())


class TestCheckRapl:
    """check_rapl — RaplResult structure."""

    @patch("pathlib.Path")
    def test_no_powercap_not_applicable(self, MockPath):
        mock_base = MagicMock()
        mock_base.exists.return_value = False
        MockPath.return_value = mock_base
        result = check_rapl()
        assert result.applicable is False
        assert result.ok is True

    @patch("pathlib.Path")
    def test_no_rapl_domains_not_applicable(self, MockPath):
        mock_base = MagicMock()
        mock_base.exists.return_value = True
        mock_base.glob.return_value = []
        MockPath.return_value = mock_base
        result = check_rapl()
        assert result.applicable is False
        assert result.ok is True

    @patch("os.access", return_value=True)
    @patch("pathlib.Path")
    def test_all_domains_readable(self, MockPath, mock_access):
        mock_f = MagicMock()
        mock_f.__str__ = lambda s: "/sys/class/powercap/intel-rapl:0/energy_uj"
        mock_base = MagicMock()
        mock_base.exists.return_value = True
        mock_base.glob.return_value = [mock_f]
        MockPath.return_value = mock_base
        result = check_rapl()
        assert result.ok is True
        assert result.domain_count == 1
        assert result.applicable is True

    @patch("os.access", return_value=False)
    @patch("pathlib.Path")
    def test_unreadable_domains(self, MockPath, mock_access):
        mock_f = MagicMock()
        mock_f.__str__ = lambda s: "/sys/class/powercap/intel-rapl:0/energy_uj"
        mock_base = MagicMock()
        mock_base.exists.return_value = True
        mock_base.glob.return_value = [mock_f]
        MockPath.return_value = mock_base
        result = check_rapl()
        assert result.ok is False
        assert result.domain_count == 1


# ── check_polkit ────────────────────────────────────────────────────────────


class TestCheckPolkit:
    """check_polkit — file presence check."""

    @patch("trcc.adapters.infra.facade_doctor.os.path.isfile", return_value=True)
    def test_installed(self, _):
        result = check_polkit()
        assert result.ok is True
        assert "installed" in result.message

    @patch("trcc.adapters.infra.facade_doctor.os.path.isfile", return_value=False)
    def test_not_installed(self, _):
        result = check_polkit()
        assert result.ok is False
        assert "not installed" in result.message


# ── check_desktop_entry ─────────────────────────────────────────────────────


class TestCheckDesktopEntry:
    """check_desktop_entry — .desktop file presence."""

    def test_entry_exists(self, tmp_path, monkeypatch):
        desktop_dir = tmp_path / ".local" / "share" / "applications"
        desktop_dir.mkdir(parents=True)
        (desktop_dir / "trcc-linux.desktop").touch()
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert check_desktop_entry() is True

    def test_entry_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert check_desktop_entry() is False


# ── run_doctor ──────────────────────────────────────────────────────────────


class TestRunDoctor(unittest.TestCase):
    """Test run_doctor() return codes."""

    @patch('trcc.adapters.infra.facade_doctor._check_rapl_permissions', return_value=True)
    @patch('trcc.adapters.infra.facade_doctor.check_selinux',
           return_value=SelinuxResult(ok=True, message='not installed'))
    @patch('trcc.adapters.infra.facade_doctor._check_udev_rules', return_value=True)
    @patch('trcc.adapters.infra.facade_doctor._check_library', return_value=True)
    @patch('trcc.adapters.infra.facade_doctor._check_binary', return_value=True)
    @patch('trcc.adapters.infra.facade_doctor._check_python_module', return_value=True)
    @patch('trcc.adapters.infra.facade_doctor._detect_pkg_manager', return_value='dnf')
    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'PRETTY_NAME': 'TestOS'})
    def test_all_ok_returns_0(self, *_):
        self.assertEqual(run_doctor(), 0)

    @patch('trcc.adapters.infra.facade_doctor._check_rapl_permissions', return_value=True)
    @patch('trcc.adapters.infra.facade_doctor.check_selinux',
           return_value=SelinuxResult(ok=True, message='not installed'))
    @patch('trcc.adapters.infra.facade_doctor._check_udev_rules', return_value=False)
    @patch('trcc.adapters.infra.facade_doctor._check_library', return_value=True)
    @patch('trcc.adapters.infra.facade_doctor._check_binary', return_value=True)
    @patch('trcc.adapters.infra.facade_doctor._check_python_module', return_value=True)
    @patch('trcc.adapters.infra.facade_doctor._detect_pkg_manager', return_value='apt')
    @patch('trcc.adapters.infra.facade_doctor._read_os_release',
           return_value={'PRETTY_NAME': 'Ubuntu 24.04'})
    def test_missing_udev_returns_1(self, *_):
        self.assertEqual(run_doctor(), 1)


class TestRunDoctorExtra:
    """run_doctor — additional branches."""

    def test_all_ok_returns_0(self, capsys):
        with (
            patch("trcc.adapters.infra.facade_doctor._detect_pkg_manager", return_value="dnf"),
            patch("trcc.adapters.infra.facade_doctor._read_os_release",
                  return_value={"PRETTY_NAME": "TestOS"}),
            patch("trcc.adapters.infra.facade_doctor._check_python_module", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_binary", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_library", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_udev_rules", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_rapl_permissions", return_value=True),
            patch("trcc.adapters.infra.facade_doctor.check_selinux",
                  return_value=SelinuxResult(ok=True, message="not installed")),
            patch("trcc.adapters.infra.facade_doctor.check_polkit",
                  return_value=MagicMock(ok=True, message="polkit policy installed")),
            patch("trcc.adapters.infra.facade_doctor._check_gpu_packages"),
        ):
            rc = run_doctor()
        assert rc == 0
        captured = capsys.readouterr()
        assert "All required dependencies OK" in captured.out

    def test_missing_module_returns_1(self, capsys):
        with (
            patch("trcc.adapters.infra.facade_doctor._detect_pkg_manager", return_value="dnf"),
            patch("trcc.adapters.infra.facade_doctor._read_os_release",
                  return_value={"PRETTY_NAME": "TestOS"}),
            patch("trcc.adapters.infra.facade_doctor._check_python_module", return_value=False),
            patch("trcc.adapters.infra.facade_doctor._check_binary", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_library", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_udev_rules", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_rapl_permissions", return_value=True),
            patch("trcc.adapters.infra.facade_doctor.check_selinux",
                  return_value=SelinuxResult(ok=True, message="not installed")),
            patch("trcc.adapters.infra.facade_doctor.check_polkit",
                  return_value=MagicMock(ok=True, message="polkit policy installed")),
            patch("trcc.adapters.infra.facade_doctor._check_gpu_packages"),
        ):
            rc = run_doctor()
        assert rc == 1
        captured = capsys.readouterr()
        assert "missing" in captured.out

    def test_apt_distro_checks_xcb(self, capsys):
        check_lib_calls: list = []

        def capture_check_lib(*args, **kwargs):
            check_lib_calls.append(args)
            return True

        with (
            patch("trcc.adapters.infra.facade_doctor._detect_pkg_manager", return_value="apt"),
            patch("trcc.adapters.infra.facade_doctor._read_os_release",
                  return_value={"PRETTY_NAME": "Ubuntu 24.04"}),
            patch("trcc.adapters.infra.facade_doctor._check_python_module", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_binary", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_library",
                  side_effect=capture_check_lib),
            patch("trcc.adapters.infra.facade_doctor._check_udev_rules", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_rapl_permissions", return_value=True),
            patch("trcc.adapters.infra.facade_doctor.check_selinux",
                  return_value=SelinuxResult(ok=True, message="not installed")),
            patch("trcc.adapters.infra.facade_doctor.check_polkit",
                  return_value=MagicMock(ok=True, message="polkit policy installed")),
            patch("trcc.adapters.infra.facade_doctor._check_gpu_packages"),
        ):
            run_doctor()

        so_names = [args[1] for args in check_lib_calls]
        assert "xcb-cursor" in so_names

    def test_selinux_enforcing_not_ok_prints_hint(self, capsys):
        with (
            patch("trcc.adapters.infra.facade_doctor._detect_pkg_manager", return_value="dnf"),
            patch("trcc.adapters.infra.facade_doctor._read_os_release",
                  return_value={"PRETTY_NAME": "Fedora 43"}),
            patch("trcc.adapters.infra.facade_doctor._check_python_module", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_binary", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_library", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_udev_rules", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_rapl_permissions", return_value=True),
            patch("trcc.adapters.infra.facade_doctor.check_selinux",
                  return_value=SelinuxResult(
                      ok=False,
                      message="SELinux enforcing — USB policy not installed",
                      enforcing=True,
                  )),
            patch("trcc.adapters.infra.facade_doctor.check_polkit",
                  return_value=MagicMock(ok=True, message="polkit policy installed")),
            patch("trcc.adapters.infra.facade_doctor._check_gpu_packages"),
        ):
            rc = run_doctor()
        assert rc == 1
        captured = capsys.readouterr()
        assert "setup-selinux" in captured.out

    def test_polkit_not_installed_prints_optional(self, capsys):
        with (
            patch("trcc.adapters.infra.facade_doctor._detect_pkg_manager", return_value="dnf"),
            patch("trcc.adapters.infra.facade_doctor._read_os_release",
                  return_value={"PRETTY_NAME": "Fedora 43"}),
            patch("trcc.adapters.infra.facade_doctor._check_python_module", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_binary", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_library", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_udev_rules", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_rapl_permissions", return_value=True),
            patch("trcc.adapters.infra.facade_doctor.check_selinux",
                  return_value=SelinuxResult(ok=True, message="not installed")),
            patch("trcc.adapters.infra.facade_doctor.check_polkit",
                  return_value=MagicMock(ok=False,
                                        message="polkit policy not installed")),
            patch("trcc.adapters.infra.facade_doctor._check_gpu_packages"),
        ):
            rc = run_doctor()
        assert rc == 0
        captured = capsys.readouterr()
        assert "setup-polkit" in captured.out

    def test_missing_binary_returns_1(self, capsys):
        with (
            patch("trcc.adapters.infra.facade_doctor._detect_pkg_manager", return_value="dnf"),
            patch("trcc.adapters.infra.facade_doctor._read_os_release",
                  return_value={"PRETTY_NAME": "TestOS"}),
            patch("trcc.adapters.infra.facade_doctor._check_python_module", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_binary", return_value=False),
            patch("trcc.adapters.infra.facade_doctor._check_library", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_udev_rules", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_rapl_permissions", return_value=True),
            patch("trcc.adapters.infra.facade_doctor.check_selinux",
                  return_value=SelinuxResult(ok=True, message="not installed")),
            patch("trcc.adapters.infra.facade_doctor.check_polkit",
                  return_value=MagicMock(ok=True, message="polkit policy installed")),
            patch("trcc.adapters.infra.facade_doctor._check_gpu_packages"),
        ):
            rc = run_doctor()
        assert rc == 1

    def test_output_includes_distro_name(self, capsys):
        with (
            patch("trcc.adapters.infra.facade_doctor._detect_pkg_manager", return_value="dnf"),
            patch("trcc.adapters.infra.facade_doctor._read_os_release",
                  return_value={"PRETTY_NAME": "MyDistro 42"}),
            patch("trcc.adapters.infra.facade_doctor._check_python_module", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_binary", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_library", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_udev_rules", return_value=True),
            patch("trcc.adapters.infra.facade_doctor._check_rapl_permissions", return_value=True),
            patch("trcc.adapters.infra.facade_doctor.check_selinux",
                  return_value=SelinuxResult(ok=True, message="not installed")),
            patch("trcc.adapters.infra.facade_doctor.check_polkit",
                  return_value=MagicMock(ok=True, message="polkit policy installed")),
            patch("trcc.adapters.infra.facade_doctor._check_gpu_packages"),
        ):
            run_doctor()
        captured = capsys.readouterr()
        assert "MyDistro 42" in captured.out


# ── CLI dispatch ─────────────────────────────────────────────────────────────


class TestDoctorCLI(unittest.TestCase):
    """Test doctor command dispatch from CLI."""

    @patch('trcc.adapters.infra.facade_doctor.run_doctor', return_value=0)
    @patch('sys.argv', ['trcc', 'doctor'])
    def test_dispatch(self, mock_doctor):
        from trcc.cli import main
        result = main()
        self.assertEqual(result, 0)
        mock_doctor.assert_called_once()
