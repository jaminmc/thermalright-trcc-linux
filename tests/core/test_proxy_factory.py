"""Tests for ipc.py proxy factory functions."""

from trcc.core.instance import InstanceKind
from trcc.ipc import (
    DeviceProxy,
    create_device_proxy,
)


class TestCreateDeviceProxy:
    """create_device_proxy() returns DeviceProxy with correct transport."""

    def test_gui_returns_ipc_transport(self):
        proxy = create_device_proxy(InstanceKind.GUI)
        assert isinstance(proxy, DeviceProxy)
        assert proxy.is_ipc

    def test_api_returns_api_transport(self):
        proxy = create_device_proxy(InstanceKind.API)
        assert isinstance(proxy, DeviceProxy)
        assert not proxy.is_ipc


class TestBackwardCompatAliases:
    """Backward-compat aliases still work."""

    def test_create_lcd_proxy_alias(self):
        from trcc.ipc import create_lcd_proxy
        proxy = create_lcd_proxy(InstanceKind.GUI)
        assert isinstance(proxy, DeviceProxy)

    def test_create_led_proxy_alias(self):
        from trcc.ipc import create_led_proxy
        proxy = create_led_proxy(InstanceKind.GUI)
        assert isinstance(proxy, DeviceProxy)

    def test_display_proxy_alias(self):
        from trcc.ipc import DisplayProxy
        assert DisplayProxy is DeviceProxy

    def test_led_proxy_alias(self):
        from trcc.ipc import LEDProxy
        assert LEDProxy is DeviceProxy
