"""Tests for trcc doctor — dependency health check."""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from trcc.adapters.infra.doctor import (
    SelinuxResult,
    _check_binary,
    _check_library,
    _check_python_module,
    _check_rapl_permissions,
    _check_udev_rules,
    _detect_pkg_manager,
    _install_hint,
    _read_os_release,
    check_selinux,
    run_doctor,
)

# ── Distro detection ────────────────────────────────────────────────────────


class TestReadOsRelease(unittest.TestCase):
    """Test os-release parsing."""

    @patch('trcc.adapters.infra.doctor.platform.freedesktop_os_release',
           return_value={'ID': 'fedora', 'PRETTY_NAME': 'Fedora 43'})
    def test_uses_platform_api(self, mock_rel):
        result = _read_os_release()
        self.assertEqual(result['ID'], 'fedora')
        mock_rel.assert_called_once()

    @patch('trcc.adapters.infra.doctor.platform.freedesktop_os_release', side_effect=OSError)
    @patch('trcc.adapters.infra.doctor.os.path.isfile', return_value=False)
    def test_fallback_returns_empty(self, _isfile, _rel):
        result = _read_os_release()
        self.assertEqual(result, {})


class TestDetectPkgManager(unittest.TestCase):
    """Test distro → package manager mapping."""

    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'ID': 'fedora', 'ID_LIKE': ''})
    def test_fedora(self, _):
        self.assertEqual(_detect_pkg_manager(), 'dnf')

    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'ID': 'ubuntu', 'ID_LIKE': 'debian'})
    def test_ubuntu(self, _):
        self.assertEqual(_detect_pkg_manager(), 'apt')

    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'ID': 'arch', 'ID_LIKE': ''})
    def test_arch(self, _):
        self.assertEqual(_detect_pkg_manager(), 'pacman')

    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'ID': 'pop', 'ID_LIKE': 'ubuntu debian'})
    def test_pop_os(self, _):
        self.assertEqual(_detect_pkg_manager(), 'apt')

    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'ID': 'nobara', 'ID_LIKE': 'fedora'})
    def test_nobara(self, _):
        self.assertEqual(_detect_pkg_manager(), 'dnf')

    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'ID': 'cachyos', 'ID_LIKE': 'arch'})
    def test_cachyos_id_like_fallback(self, _):
        self.assertEqual(_detect_pkg_manager(), 'pacman')

    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'ID': 'unknowndistro', 'ID_LIKE': ''})
    def test_unknown_returns_none(self, _):
        self.assertIsNone(_detect_pkg_manager())

    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'ID': 'zorin', 'ID_LIKE': 'ubuntu debian'})
    def test_zorin(self, _):
        self.assertEqual(_detect_pkg_manager(), 'apt')

    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'ID': 'void', 'ID_LIKE': ''})
    def test_void(self, _):
        self.assertEqual(_detect_pkg_manager(), 'xbps')

    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'ID': 'opensuse-tumbleweed', 'ID_LIKE': 'suse'})
    def test_opensuse(self, _):
        self.assertEqual(_detect_pkg_manager(), 'zypper')


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


# ── Check helpers ────────────────────────────────────────────────────────────


class TestCheckPythonModule(unittest.TestCase):
    """Test Python module availability checking."""

    def test_installed_module(self):
        """Existing module (os) returns True."""
        result = _check_python_module('os', 'os', required=True, pm=None)
        self.assertTrue(result)

    def test_missing_required(self):
        """Missing required module returns False."""
        result = _check_python_module(
            'nonexistent', 'nonexistent_pkg_xyz', required=True, pm=None)
        self.assertFalse(result)

    def test_missing_optional(self):
        """Missing optional module returns True (not a failure)."""
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

    @patch('trcc.adapters.infra.doctor.os.path.isfile', return_value=True)
    def test_rules_exist(self, _):
        self.assertTrue(_check_udev_rules())

    @patch('trcc.adapters.infra.doctor.os.path.isfile', return_value=False)
    def test_rules_missing(self, _):
        self.assertFalse(_check_udev_rules())


# ── Integration: run_doctor() ────────────────────────────────────────────────


class TestRunDoctor(unittest.TestCase):
    """Test run_doctor() return codes."""

    @patch('trcc.adapters.infra.doctor._check_rapl_permissions', return_value=True)
    @patch('trcc.adapters.infra.doctor.check_selinux',
           return_value=SelinuxResult(ok=True, message='not installed'))
    @patch('trcc.adapters.infra.doctor._check_udev_rules', return_value=True)
    @patch('trcc.adapters.infra.doctor._check_library', return_value=True)
    @patch('trcc.adapters.infra.doctor._check_binary', return_value=True)
    @patch('trcc.adapters.infra.doctor._check_python_module', return_value=True)
    @patch('trcc.adapters.infra.doctor._detect_pkg_manager', return_value='dnf')
    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'PRETTY_NAME': 'TestOS'})
    def test_all_ok_returns_0(self, *_):
        self.assertEqual(run_doctor(), 0)

    @patch('trcc.adapters.infra.doctor._check_rapl_permissions', return_value=True)
    @patch('trcc.adapters.infra.doctor.check_selinux',
           return_value=SelinuxResult(ok=True, message='not installed'))
    @patch('trcc.adapters.infra.doctor._check_udev_rules', return_value=False)
    @patch('trcc.adapters.infra.doctor._check_library', return_value=True)
    @patch('trcc.adapters.infra.doctor._check_binary', return_value=True)
    @patch('trcc.adapters.infra.doctor._check_python_module', return_value=True)
    @patch('trcc.adapters.infra.doctor._detect_pkg_manager', return_value='apt')
    @patch('trcc.adapters.infra.doctor._read_os_release',
           return_value={'PRETTY_NAME': 'Ubuntu 24.04'})
    def test_missing_udev_returns_1(self, *_):
        self.assertEqual(run_doctor(), 1)


# ── RAPL permissions ─────────────────────────────────────────────────────────


class TestCheckRaplPermissions(unittest.TestCase):
    """Test _check_rapl_permissions() diagnostics."""

    @patch('os.path.isdir', return_value=False)
    def test_no_powercap_returns_true(self, _):
        """No powercap subsystem — not applicable, returns True."""
        self.assertTrue(_check_rapl_permissions())

    @patch('os.access', return_value=True)
    @patch('os.path.isdir', return_value=True)
    @patch('pathlib.Path.glob')
    def test_rapl_readable(self, mock_glob, mock_isdir, mock_access):
        """RAPL energy files readable — returns True."""
        from pathlib import Path
        mock_energy = Mock(spec=Path)
        mock_energy.__str__ = lambda s: '/sys/class/powercap/intel-rapl:0/energy_uj'
        mock_glob.return_value = [mock_energy]
        self.assertTrue(_check_rapl_permissions())

    @patch('os.access', return_value=False)
    @patch('os.path.isdir', return_value=True)
    @patch('pathlib.Path.glob')
    def test_rapl_not_readable(self, mock_glob, mock_isdir, mock_access):
        """RAPL energy files not readable — returns False."""
        from pathlib import Path
        mock_energy = Mock(spec=Path)
        mock_energy.__str__ = lambda s: '/sys/class/powercap/intel-rapl:0/energy_uj'
        mock_glob.return_value = [mock_energy]
        self.assertFalse(_check_rapl_permissions())

    @patch('os.path.isdir', return_value=True)
    @patch('pathlib.Path.glob', return_value=[])
    def test_no_rapl_domains(self, mock_glob, _):
        """powercap exists but no intel-rapl domains — returns True."""
        self.assertTrue(_check_rapl_permissions())


# ── CLI dispatch ─────────────────────────────────────────────────────────────


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
        """semodule -l fails (non-root) but sesearch finds permissions."""
        def side_effect(cmd, **_kw):
            if cmd[0] == 'getenforce':
                return Mock(stdout='Enforcing\n')
            if cmd[0] == 'semodule':
                return Mock(stdout='', returncode=1)  # permission denied
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
        """semodule says no module, sesearch finds no permissions."""
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
        """Neither semodule nor sesearch available."""
        def side_effect(cmd, **_kw):
            if cmd[0] == 'getenforce':
                return Mock(stdout='Enforcing\n')
            raise FileNotFoundError
        mock_run.side_effect = side_effect
        r = check_selinux()
        self.assertFalse(r.ok)
        self.assertTrue(r.enforcing)
        self.assertFalse(r.module_loaded)


class TestDoctorCLI(unittest.TestCase):
    """Test doctor command dispatch from CLI."""

    @patch('trcc.adapters.infra.doctor.run_doctor', return_value=0)
    @patch('sys.argv', ['trcc', 'doctor'])
    def test_dispatch(self, mock_doctor):
        from trcc.cli import main
        result = main()
        self.assertEqual(result, 0)
        mock_doctor.assert_called_once()
