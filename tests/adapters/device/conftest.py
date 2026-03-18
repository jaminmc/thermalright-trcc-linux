"""Shared fixtures for device adapter tests (includes HID testing setup)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from trcc.adapters.detection.factory_detector import enable_hid_testing
from trcc.adapters.transport.adapter_hid import UsbTransport


@pytest.fixture(autouse=True)
def _enable_hid_for_tests():
    """Auto-enable HID testing for every test in adapters/device/."""
    enable_hid_testing()


@pytest.fixture(autouse=True)
def _patch_hid_sleep():
    """Disable time.sleep in HID device modules for fast tests."""
    with patch("trcc.adapters.transport.adapter_hid.time.sleep"), \
         patch("trcc.adapters.transport.adapter_led.time.sleep"):
        yield


def make_mock_transport() -> MagicMock:
    """Create a MagicMock that satisfies the UsbTransport interface."""
    t = MagicMock(spec=UsbTransport)
    t.is_open = True
    return t
