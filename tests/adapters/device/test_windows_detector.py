"""Tests for Windows USB device detector (mocked — runs on Linux)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

MODULE = 'trcc.adapters.detection.facade_windows'


# ── VID/PID Parsing ───────────────────────────────────────────────────


class TestParseVidPid:

    def test_standard_format(self):
        from trcc.adapters.detection.facade_windows import _parse_vid_pid
        vid, pid = _parse_vid_pid('USB\\VID_0416&PID_5020\\12345')
        assert vid == 0x0416
        assert pid == 0x5020

    def test_lowercase(self):
        from trcc.adapters.detection.facade_windows import _parse_vid_pid
        vid, pid = _parse_vid_pid('USB\\VID_0416&PID_5020\\abc')
        assert vid == 0x0416

    def test_no_match(self):
        from trcc.adapters.detection.facade_windows import _parse_vid_pid
        vid, pid = _parse_vid_pid('PCI\\VEN_8086&DEV_1234')
        assert vid is None
        assert pid is None

    def test_empty_string(self):
        from trcc.adapters.detection.facade_windows import _parse_vid_pid
        vid, pid = _parse_vid_pid('')
        assert vid is None
        assert pid is None

    def test_partial_match(self):
        from trcc.adapters.detection.facade_windows import _parse_vid_pid
        vid, pid = _parse_vid_pid('VID_041')  # Too short
        assert vid is None


# ── Device Matching ───────────────────────────────────────────────────


class TestMatchDevice:

    def test_unknown_vid_pid_returns_none(self):
        from trcc.adapters.detection.facade_windows import _match_device
        pnp = MagicMock()
        pnp.DeviceID = 'USB\\VID_FFFF&PID_FFFF'
        result = _match_device(0xFFFF, 0xFFFF, pnp)
        assert result is None

    def test_known_scsi_device(self):
        """Known SCSI VID:PID should return DetectedDevice with protocol='scsi'."""
        from trcc.adapters.detection.facade_windows import _match_device
        from trcc.adapters.detection.factory_detector import KNOWN_DEVICES

        if not KNOWN_DEVICES:
            pytest.skip("No SCSI devices in registry")

        vid, pid = next(iter(KNOWN_DEVICES))
        pnp = MagicMock()
        pnp.DeviceID = f'USB\\VID_{vid:04X}&PID_{pid:04X}'

        with patch(f'{MODULE}._find_physical_drive', return_value='\\\\.\\PhysicalDrive2'):
            result = _match_device(vid, pid, pnp)

        assert result is not None
        assert result.vid == vid
        assert result.pid == pid
        assert result.protocol == 'scsi'
        assert result.scsi_device == '\\\\.\\PhysicalDrive2'

    def test_known_hid_lcd_device(self):
        """Known HID LCD VID:PID should return DetectedDevice with protocol='hid'."""
        from trcc.adapters.detection.facade_windows import _match_device
        from trcc.adapters.detection.factory_detector import _HID_LCD_DEVICES

        if not _HID_LCD_DEVICES:
            pytest.skip("No HID LCD devices in registry")

        vid, pid = next(iter(_HID_LCD_DEVICES))
        pnp = MagicMock()
        pnp.DeviceID = f'USB\\VID_{vid:04X}&PID_{pid:04X}'

        result = _match_device(vid, pid, pnp)
        assert result is not None
        assert result.protocol == 'hid'
        assert result.scsi_device is None

    def test_known_bulk_device(self):
        """Known Bulk VID:PID should return protocol='bulk'."""
        from trcc.adapters.detection.facade_windows import _match_device
        from trcc.adapters.detection.factory_detector import _BULK_DEVICES

        if not _BULK_DEVICES:
            pytest.skip("No Bulk devices in registry")

        vid, pid = next(iter(_BULK_DEVICES))
        pnp = MagicMock()
        pnp.DeviceID = 'USB\\test'

        result = _match_device(vid, pid, pnp)
        assert result is not None
        assert result.protocol == 'bulk'
        assert result.device_type == 4

    def test_known_ly_device(self):
        """Known LY VID:PID should return protocol='ly'."""
        from trcc.adapters.detection.facade_windows import _match_device
        from trcc.adapters.detection.factory_detector import _LY_DEVICES

        if not _LY_DEVICES:
            pytest.skip("No LY devices in registry")

        vid, pid = next(iter(_LY_DEVICES))
        pnp = MagicMock()
        pnp.DeviceID = 'USB\\test'

        result = _match_device(vid, pid, pnp)
        assert result is not None
        assert result.protocol == 'ly'
        assert result.device_type == 10

    def test_known_led_device(self):
        """Known LED VID:PID should return protocol='hid', implementation='hid_led'."""
        from trcc.adapters.detection.facade_windows import _match_device
        from trcc.adapters.detection.factory_detector import _LED_DEVICES

        if not _LED_DEVICES:
            pytest.skip("No LED devices in registry")

        vid, pid = next(iter(_LED_DEVICES))
        pnp = MagicMock()
        pnp.DeviceID = 'USB\\test'

        result = _match_device(vid, pid, pnp)
        assert result is not None
        assert result.protocol == 'hid'
        assert result.implementation == 'hid_led'
        assert result.device_type == 0


# ── Detector.detect() ─────────────────────────────────────────────────


class TestWindowsDetector:

    def test_returns_empty_without_wmi(self):
        """On Linux (no wmi), returns empty list."""
        from trcc.adapters.detection.facade_windows import WindowsDeviceDetector
        devices = WindowsDeviceDetector.detect()
        assert devices == []


# ── Physical Drive Finder ─────────────────────────────────────────────


class TestFindPhysicalDrive:

    def test_returns_none_without_wmi(self):
        """On Linux, returns None (wmi not available)."""
        from trcc.adapters.detection.facade_windows import _find_physical_drive
        result = _find_physical_drive(0x0416, 0x5020)
        assert result is None

    def test_strategy1_vid_in_disk_pnpdeviceid(self):
        """Direct VID match in disk PNPDeviceID."""
        from trcc.adapters.detection.facade_windows import _find_physical_drive

        disk = MagicMock()
        disk.PNPDeviceID = 'USB\\VID_0402&PID_3922\\12345'
        disk.DeviceID = '\\\\.\\PhysicalDrive1'

        mock_wmi_mod = MagicMock()
        mock_wmi_instance = MagicMock()
        mock_wmi_mod.WMI.return_value = mock_wmi_instance
        mock_wmi_instance.Win32_DiskDrive.return_value = [disk]

        with patch.dict('sys.modules', {'wmi': mock_wmi_mod}):
            result = _find_physical_drive(0x0402, 0x3922)

        assert result == '\\\\.\\PhysicalDrive1'

    def test_strategy2_usbstor_vendor_match(self):
        """USBSTOR disk matched via known vendor string (VEN_USBLCD)."""
        from trcc.adapters.detection.facade_windows import _find_physical_drive

        # Disk with USBSTOR path (no VID in PNPDeviceID)
        usbstor_disk = MagicMock()
        usbstor_disk.PNPDeviceID = (
            r'USBSTOR\DISK&VEN_USBLCD&PROD_USB_PRC_SYSTEM&REV_\7&AF300EF&0'
        )
        usbstor_disk.DeviceID = '\\\\.\\PhysicalDrive1'
        usbstor_disk.InterfaceType = 'USB'
        usbstor_disk.Size = '0'

        # QEMU system disk (should not match)
        qemu_disk = MagicMock()
        qemu_disk.PNPDeviceID = r'SCSI\DISK&VEN_QEMU&PROD_HARDDISK\4&35424867'
        qemu_disk.DeviceID = '\\\\.\\PhysicalDrive0'
        qemu_disk.InterfaceType = 'SCSI'
        qemu_disk.Size = '64424509440'

        # USB controller device confirming VID/PID exists
        usb_rel = MagicMock()
        usb_rel.Dependent = (
            r'\\HOST\root\cimv2:Win32_PnPEntity.DeviceID='
            r'"USB\VID_0402&PID_3922\6&1C4D2F9B&0&21"'
        )

        mock_wmi_mod = MagicMock()
        mock_wmi_instance = MagicMock()
        mock_wmi_mod.WMI.return_value = mock_wmi_instance
        mock_wmi_instance.Win32_DiskDrive.return_value = [qemu_disk, usbstor_disk]
        mock_wmi_instance.Win32_USBControllerDevice.return_value = [usb_rel]

        with patch.dict('sys.modules', {'wmi': mock_wmi_mod}):
            result = _find_physical_drive(0x0402, 0x3922)

        assert result == '\\\\.\\PhysicalDrive1'

    def test_strategy2_ignores_usb_flash_drive(self):
        """USB flash drive should not match — wrong vendor name and large size."""
        from trcc.adapters.detection.facade_windows import _find_physical_drive

        flash_drive = MagicMock()
        flash_drive.PNPDeviceID = (
            r'USBSTOR\DISK&VEN_KINGSTON&PROD_DATATRAVELER&REV_1.0\1234'
        )
        flash_drive.DeviceID = '\\\\.\\PhysicalDrive2'
        flash_drive.InterfaceType = 'USB'
        flash_drive.Size = '32212254720'  # 32GB

        usb_rel = MagicMock()
        usb_rel.Dependent = (
            r'\\HOST\root\cimv2:Win32_PnPEntity.DeviceID='
            r'"USB\VID_0402&PID_3922\6&1C4D2F9B&0&21"'
        )

        mock_wmi_mod = MagicMock()
        mock_wmi_instance = MagicMock()
        mock_wmi_mod.WMI.return_value = mock_wmi_instance
        mock_wmi_instance.Win32_DiskDrive.return_value = [flash_drive]
        mock_wmi_instance.Win32_USBControllerDevice.return_value = [usb_rel]

        with patch.dict('sys.modules', {'wmi': mock_wmi_mod}):
            result = _find_physical_drive(0x0402, 0x3922)

        # Flash drive: wrong vendor, >1MB — should not match
        assert result is None

    def test_strategy2_fallback_zero_size_disk(self):
        """Unknown USBSTOR vendor but <1MB size — fallback match."""
        from trcc.adapters.detection.facade_windows import _find_physical_drive

        tiny_disk = MagicMock()
        tiny_disk.PNPDeviceID = (
            r'USBSTOR\DISK&VEN_UNKNOWN&PROD_DEVICE&REV_\12345'
        )
        tiny_disk.DeviceID = '\\\\.\\PhysicalDrive3'
        tiny_disk.InterfaceType = 'USB'
        tiny_disk.Size = '0'

        usb_rel = MagicMock()
        usb_rel.Dependent = (
            r'\\HOST\root\cimv2:Win32_PnPEntity.DeviceID='
            r'"USB\VID_0402&PID_3922\6&1C4D2F9B&0&21"'
        )

        mock_wmi_mod = MagicMock()
        mock_wmi_instance = MagicMock()
        mock_wmi_mod.WMI.return_value = mock_wmi_instance
        mock_wmi_instance.Win32_DiskDrive.return_value = [tiny_disk]
        mock_wmi_instance.Win32_USBControllerDevice.return_value = [usb_rel]

        with patch.dict('sys.modules', {'wmi': mock_wmi_mod}):
            result = _find_physical_drive(0x0402, 0x3922)

        assert result == '\\\\.\\PhysicalDrive3'

    def test_no_usb_device_no_fallback(self):
        """No USB VID/PID confirmed — strategy 2 should not run."""
        from trcc.adapters.detection.facade_windows import _find_physical_drive

        usbstor_disk = MagicMock()
        usbstor_disk.PNPDeviceID = r'USBSTOR\DISK&VEN_USBLCD&PROD_X\1'
        usbstor_disk.DeviceID = '\\\\.\\PhysicalDrive1'
        usbstor_disk.InterfaceType = 'USB'

        mock_wmi_mod = MagicMock()
        mock_wmi_instance = MagicMock()
        mock_wmi_mod.WMI.return_value = mock_wmi_instance
        mock_wmi_instance.Win32_DiskDrive.return_value = [usbstor_disk]
        mock_wmi_instance.Win32_USBControllerDevice.return_value = []

        with patch.dict('sys.modules', {'wmi': mock_wmi_mod}):
            result = _find_physical_drive(0x0402, 0x3922)

        assert result is None

    def test_strategy3_ctypes_vendor_match(self):
        """Strategy 3: WMI fails, ctypes scan finds USB drive with LCD vendor."""
        from trcc.adapters.detection.facade_windows import _find_physical_drive

        # WMI fails entirely
        mock_wmi_mod = MagicMock()
        mock_wmi_mod.WMI.side_effect = Exception("WMI unavailable")

        # ctypes scan finds a USB drive with USBLCD vendor
        with patch.dict('sys.modules', {'wmi': mock_wmi_mod}), \
             patch(f'{MODULE}._scan_physical_drives_ctypes',
                   return_value=[('\\\\.\\PhysicalDrive1', 'USBLCD')]):
            result = _find_physical_drive(0x0402, 0x3922)

        assert result == '\\\\.\\PhysicalDrive1'

    def test_strategy3_single_usb_drive_fallback(self):
        """Strategy 3: unknown vendor but only one USB drive — fallback match."""
        from trcc.adapters.detection.facade_windows import _find_physical_drive

        mock_wmi_mod = MagicMock()
        mock_wmi_mod.WMI.side_effect = Exception("WMI unavailable")

        with patch.dict('sys.modules', {'wmi': mock_wmi_mod}), \
             patch(f'{MODULE}._scan_physical_drives_ctypes',
                   return_value=[('\\\\.\\PhysicalDrive2', 'UNKNOWN_DEVICE')]):
            result = _find_physical_drive(0x0402, 0x3922)

        assert result == '\\\\.\\PhysicalDrive2'

    def test_strategy3_multiple_usb_drives_no_vendor_match(self):
        """Strategy 3: multiple USB drives, no vendor match — returns None."""
        from trcc.adapters.detection.facade_windows import _find_physical_drive

        mock_wmi_mod = MagicMock()
        mock_wmi_mod.WMI.side_effect = Exception("WMI unavailable")

        with patch.dict('sys.modules', {'wmi': mock_wmi_mod}), \
             patch(f'{MODULE}._scan_physical_drives_ctypes',
                   return_value=[('\\\\.\\PhysicalDrive1', 'KINGSTON'),
                                 ('\\\\.\\PhysicalDrive2', 'SANDISK')]):
            result = _find_physical_drive(0x0402, 0x3922)

        assert result is None

    def test_strategy3_no_usb_drives(self):
        """Strategy 3: no USB drives found — returns None."""
        from trcc.adapters.detection.facade_windows import _find_physical_drive

        mock_wmi_mod = MagicMock()
        mock_wmi_mod.WMI.side_effect = Exception("WMI unavailable")

        with patch.dict('sys.modules', {'wmi': mock_wmi_mod}), \
             patch(f'{MODULE}._scan_physical_drives_ctypes',
                   return_value=[]):
            result = _find_physical_drive(0x0402, 0x3922)

        assert result is None
