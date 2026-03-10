"""Tests for services/device.py — device detection, selection, and frame sending.

Covers:
- Construction and strict DI
- detect() — device enumeration, LED enrichment
- select() / selected property
- scan_and_select() — priority: explicit path > saved > first
- _discover_resolution() — handshake, no-op when already known
- send_rgb565() — thread-safe, busy guard
- send_pil() — encode cache by id()
- send_rgb565_async() — persistent send worker queue
- is_busy property
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from trcc.core.models import DetectedDevice, DeviceInfo
from trcc.services.device import DeviceService


def _make_detected(name: str = 'LCD', vid: int = 0x0402, pid: int = 0x3922,
                   protocol: str = 'scsi', impl: str = 'scsi',
                   scsi_device: str = '/dev/sg0',
                   usb_path: str = '1-001') -> DetectedDevice:
    return DetectedDevice(
        vendor_name='Thermalright',
        product_name=name,
        model=name,
        vid=vid,
        pid=pid,
        protocol=protocol,
        device_type='lcd',
        implementation=impl,
        scsi_device=scsi_device,
        usb_path=usb_path,
    )


def _make_service(devices: list[DetectedDevice] | None = None,
                  ) -> DeviceService:
    detect_fn = MagicMock(return_value=devices or [])
    probe_led_fn = MagicMock(return_value=None)
    get_protocol = MagicMock()
    return DeviceService(
        detect_fn=detect_fn,
        probe_led_fn=probe_led_fn,
        get_protocol=get_protocol,
    )


# =========================================================================
# Construction
# =========================================================================


class TestConstruction:
    def test_strict_di_requires_all_deps(self):
        with pytest.raises(RuntimeError, match="requires"):
            DeviceService()

    def test_initial_state(self):
        svc = _make_service()
        assert svc.selected is None
        assert svc.devices == []
        assert svc.is_busy is False


# =========================================================================
# Detection
# =========================================================================


class TestDetect:
    def test_detect_returns_device_infos(self):
        raw = [_make_detected('LCD1'), _make_detected('LCD2')]
        svc = _make_service(raw)
        devices = svc.detect()
        assert len(devices) == 2
        assert devices[0].name == 'Thermalright LCD1'
        assert devices[1].name == 'Thermalright LCD2'

    def test_device_index_assigned(self):
        raw = [_make_detected('A'), _make_detected('B')]
        svc = _make_service(raw)
        devices = svc.detect()
        assert devices[0].device_index == 0
        assert devices[1].device_index == 1

    def test_detect_empty(self):
        svc = _make_service([])
        assert svc.detect() == []

    def test_led_device_enrichment(self):
        raw = [_make_detected('LED', impl='hid_led')]
        svc = _make_service(raw)
        probe_result = MagicMock()
        probe_result.style.style_id = 5
        probe_result.style.model_name = 'LF8'
        probe_result.pm = 120
        svc._probe_led_fn.return_value = probe_result

        devices = svc.detect()
        assert devices[0].led_style_id == 5
        assert devices[0].model == 'LF8'

    def test_led_enrichment_failure_silent(self):
        raw = [_make_detected('LED', impl='hid_led')]
        svc = _make_service(raw)
        svc._probe_led_fn.side_effect = RuntimeError("probe failed")
        devices = svc.detect()
        assert len(devices) == 1  # Still detected, just not enriched

    def test_import_error_returns_empty(self):
        svc = _make_service()
        svc._detect_fn.side_effect = ImportError("no pyusb")
        assert svc.detect() == []


# =========================================================================
# Selection
# =========================================================================


class TestSelection:
    def test_select(self):
        svc = _make_service()
        dev = DeviceInfo(name='test', path='/dev/sg0', vid=1, pid=2,
                         device_index=0)
        svc.select(dev)
        assert svc.selected is dev

    def test_scan_and_select_explicit_path(self):
        raw = [
            _make_detected('A', scsi_device='/dev/sg0'),
            _make_detected('B', scsi_device='/dev/sg1'),
        ]
        svc = _make_service(raw)
        result = svc.scan_and_select(device_path='/dev/sg1')
        assert result is not None
        assert result.path == '/dev/sg1'

    def test_scan_and_select_explicit_path_not_found_falls_back(self):
        raw = [_make_detected('A', scsi_device='/dev/sg0')]
        svc = _make_service(raw)
        result = svc.scan_and_select(device_path='/dev/sg99')
        assert result is not None
        assert result.path == '/dev/sg0'  # Falls back to first

    @patch('trcc.conf.Settings')
    def test_scan_and_select_saved_preference(self, mock_settings):
        raw = [
            _make_detected('A', scsi_device='/dev/sg0'),
            _make_detected('B', scsi_device='/dev/sg1'),
        ]
        svc = _make_service(raw)
        mock_settings.get_selected_device.return_value = '/dev/sg1'
        result = svc.scan_and_select()
        assert result.path == '/dev/sg1'

    @patch('trcc.conf.Settings')
    def test_scan_and_select_no_saved_uses_first(self, mock_settings):
        raw = [_make_detected('A', scsi_device='/dev/sg0')]
        svc = _make_service(raw)
        mock_settings.get_selected_device.return_value = None
        result = svc.scan_and_select()
        assert result.path == '/dev/sg0'

    def test_scan_and_select_no_devices(self):
        svc = _make_service([])
        result = svc.scan_and_select()
        assert result is None


# =========================================================================
# Resolution discovery
# =========================================================================


class TestDiscoverResolution:
    def test_handshake_sets_resolution(self):
        raw = [_make_detected('LCD')]
        svc = _make_service(raw)
        protocol = MagicMock()
        handshake_result = MagicMock()
        handshake_result.resolution = (480, 480)
        handshake_result.fbl = 72
        protocol.handshake.return_value = handshake_result
        svc._get_protocol.return_value = protocol

        svc.detect()
        dev = svc.devices[0]
        dev.resolution = (0, 0)
        svc._discover_resolution(dev)
        assert dev.resolution == (480, 480)
        assert dev.fbl_code == 72

    def test_no_op_when_resolution_known(self):
        svc = _make_service()
        dev = DeviceInfo(name='t', path='p', vid=1, pid=2, device_index=0)
        dev.resolution = (320, 320)
        svc._discover_resolution(dev)
        svc._get_protocol.assert_not_called()

    def test_handshake_failure_silent(self):
        svc = _make_service()
        dev = DeviceInfo(name='t', path='p', vid=1, pid=2, device_index=0)
        dev.resolution = (0, 0)
        svc._get_protocol.side_effect = RuntimeError("no device")
        svc._discover_resolution(dev)  # Should not raise
        assert dev.resolution == (0, 0)


# =========================================================================
# Send
# =========================================================================


class TestSend:
    def test_send_rgb565_no_device(self):
        svc = _make_service()
        assert svc.send_rgb565(b'\x00' * 100, 320, 320) is False

    def test_send_rgb565_success(self):
        svc = _make_service()
        dev = DeviceInfo(name='t', path='p', vid=1, pid=2, device_index=0)
        svc.select(dev)
        protocol = MagicMock()
        protocol.send_image.return_value = True
        svc._get_protocol.return_value = protocol

        assert svc.send_rgb565(b'\x00' * 100, 320, 320) is True
        protocol.send_image.assert_called_once()

    def test_send_rgb565_busy_skips(self):
        svc = _make_service()
        dev = DeviceInfo(name='t', path='p', vid=1, pid=2, device_index=0)
        svc.select(dev)

        # Simulate busy state
        svc._send_busy = True
        assert svc.send_rgb565(b'\x00', 320, 320) is False

    def test_send_pil_cache_hit(self):
        svc = _make_service()
        dev = DeviceInfo(name='t', path='p', vid=1, pid=2, device_index=0)
        dev.resolution = (320, 320)
        svc.select(dev)
        protocol = MagicMock()
        protocol.send_image.return_value = True
        svc._get_protocol.return_value = protocol

        img = MagicMock()
        cached_data = b'\x00' * 50
        svc._last_encode_id = id(img)
        svc._last_encode_data = cached_data

        svc.send_pil(img, 320, 320)
        # Should use cached data, not re-encode
        protocol.send_image.assert_called_once_with(cached_data, 320, 320)

    def test_send_pil_callback(self):
        svc = _make_service()
        dev = DeviceInfo(name='t', path='p', vid=1, pid=2, device_index=0)
        svc.select(dev)
        protocol = MagicMock()
        protocol.send_image.return_value = True
        svc._get_protocol.return_value = protocol

        callback = MagicMock()
        svc.on_frame_sent = callback

        img = MagicMock()
        svc._last_encode_id = id(img)
        svc._last_encode_data = b'\x00'
        svc.send_pil(img, 320, 320)
        callback.assert_called_once_with(img)

    def test_send_error_returns_false(self):
        svc = _make_service()
        dev = DeviceInfo(name='t', path='p', vid=1, pid=2, device_index=0)
        svc.select(dev)
        svc._get_protocol.side_effect = RuntimeError("disconnected")

        assert svc.send_rgb565(b'\x00', 320, 320) is False
        assert svc.is_busy is False  # Lock released on error


# =========================================================================
# Async send
# =========================================================================


class TestAsyncSend:
    def test_send_rgb565_async_queues(self):
        svc = _make_service()
        dev = DeviceInfo(name='t', path='p', vid=1, pid=2, device_index=0)
        svc.select(dev)
        # Don't actually start worker
        svc._ensure_send_worker = MagicMock()
        svc.send_rgb565_async(b'\x00', 320, 320)
        assert len(svc._send_queue) == 1

    def test_queue_maxlen_1_latest_wins(self):
        svc = _make_service()
        svc._ensure_send_worker = MagicMock()
        svc.send_rgb565_async(b'\x01', 320, 320)
        svc.send_rgb565_async(b'\x02', 320, 320)
        assert len(svc._send_queue) == 1
        assert svc._send_queue[0][0] == b'\x02'


# =========================================================================
# Protocol info
# =========================================================================


class TestProtocolInfo:
    def test_no_protocol_info_fn(self):
        svc = _make_service()
        svc._get_protocol_info = None
        assert svc.get_protocol_info() is None

    def test_protocol_info_exception(self):
        svc = _make_service()
        svc._get_protocol_info = MagicMock(side_effect=RuntimeError("err"))
        assert svc.get_protocol_info() is None

    def test_protocol_info_success(self):
        svc = _make_service()
        svc._get_protocol_info = MagicMock(return_value="scsi_v2")
        dev = DeviceInfo(name='t', path='p', vid=1, pid=2, device_index=0)
        svc.select(dev)
        assert svc.get_protocol_info() == "scsi_v2"
