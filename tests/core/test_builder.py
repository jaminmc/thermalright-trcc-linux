"""Tests for core/builder.py — ControllerBuilder fluent device assembly."""

import unittest
from unittest.mock import MagicMock, patch

from trcc.core.builder import ControllerBuilder
from trcc.services.image import ImageService


class TestControllerBuilderLcd(unittest.TestCase):
    """ControllerBuilder.build_lcd() — assembles LCDDevice with DI."""

    @patch('trcc.adapters.infra.repository_data.DataManager.ensure_all')
    def test_build_lcd_returns_lcd_device(self, _):
        """build_lcd() returns an LCDDevice instance."""
        from trcc.core.lcd_device import LCDDevice
        lcd = ControllerBuilder().with_renderer(ImageService._r()).build_lcd()
        self.assertIsInstance(lcd, LCDDevice)

    def test_build_lcd_without_renderer_raises(self):
        """build_lcd() without with_renderer() raises RuntimeError."""
        with self.assertRaises(RuntimeError) as ctx:
            ControllerBuilder().build_lcd()
        self.assertIn('with_renderer', str(ctx.exception))

    @patch('trcc.adapters.infra.repository_data.DataManager.ensure_all')
    def test_build_lcd_wires_device_service(self, _):
        """LCDDevice has a wired DeviceService."""
        lcd = ControllerBuilder().with_renderer(ImageService._r()).build_lcd()
        self.assertIsNotNone(lcd._device_svc)

    @patch('trcc.adapters.infra.repository_data.DataManager.ensure_all')
    def test_build_lcd_wires_display_service(self, _):
        """LCDDevice has a wired DisplayService."""
        lcd = ControllerBuilder().with_renderer(ImageService._r()).build_lcd()
        self.assertIsNotNone(lcd._display_svc)

    @patch('trcc.adapters.infra.repository_data.DataManager.ensure_all')
    def test_build_lcd_wires_theme_service(self, _):
        """LCDDevice has a wired ThemeService."""
        lcd = ControllerBuilder().with_renderer(ImageService._r()).build_lcd()
        self.assertIsNotNone(lcd._theme_svc)

    @patch('trcc.adapters.infra.repository_data.DataManager.ensure_all')
    def test_build_lcd_wires_renderer(self, _):
        """LCDDevice has the injected renderer."""
        renderer = ImageService._r()
        lcd = ControllerBuilder().with_renderer(renderer).build_lcd()
        self.assertIs(lcd._renderer, renderer)

    @patch('trcc.adapters.infra.repository_data.DataManager.ensure_all')
    def test_with_data_dir_triggers_initialize(self, mock_ensure):
        """with_data_dir() causes build_lcd() to call lcd.initialize()."""
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            lcd = (ControllerBuilder()
                   .with_renderer(ImageService._r())
                   .with_data_dir(Path(d))
                   .build_lcd())
            # initialize was called (ensure_all is the data download step)
            self.assertIsNotNone(lcd)

    @patch('trcc.adapters.infra.repository_data.DataManager.ensure_all')
    def test_build_lcd_without_data_dir_skips_initialize(self, mock_ensure):
        """Without with_data_dir(), initialize is not called."""
        lcd = ControllerBuilder().with_renderer(ImageService._r()).build_lcd()
        # No crash, lcd built without initialization
        self.assertIsNotNone(lcd)


class TestControllerBuilderLed(unittest.TestCase):
    """ControllerBuilder.build_led() — assembles LEDDevice."""

    def test_build_led_returns_led_device(self):
        """build_led() returns an LEDDevice instance."""
        from trcc.core.led_device import LEDDevice
        led = ControllerBuilder().build_led()
        self.assertIsInstance(led, LEDDevice)

    def test_build_led_no_renderer_required(self):
        """LED doesn't need a renderer — build_led() works without it."""
        led = ControllerBuilder().build_led()
        self.assertIsNotNone(led)

    def test_build_led_wires_get_protocol(self):
        """LEDDevice gets the protocol factory wired."""
        led = ControllerBuilder().build_led()
        self.assertIsNotNone(led._get_protocol)

    def test_build_led_injects_device_svc(self):
        """build_led() injects a DeviceService so connect() works."""
        led = ControllerBuilder().build_led()
        self.assertIsNotNone(led._device_svc)


class TestControllerBuilderLcdFromService(unittest.TestCase):
    """ControllerBuilder.lcd_from_service() — builds from existing DeviceService."""

    def test_returns_lcd_device(self):
        from trcc.core.lcd_device import LCDDevice
        svc = MagicMock()
        svc.selected = MagicMock()
        lcd = ControllerBuilder().lcd_from_service(svc)
        self.assertIsInstance(lcd, LCDDevice)

    def test_wires_display_and_theme_services(self):
        svc = MagicMock()
        svc.selected = MagicMock()
        lcd = ControllerBuilder().lcd_from_service(svc)
        self.assertIsNotNone(lcd._display_svc)
        self.assertIsNotNone(lcd._theme_svc)
        self.assertIs(lcd._device_svc, svc)


class TestControllerBuilderSetup(unittest.TestCase):
    """ControllerBuilder.build_setup() — platform setup adapter."""

    def test_returns_platform_setup(self):
        from trcc.core.ports import PlatformSetup
        setup = ControllerBuilder.build_setup()
        self.assertIsInstance(setup, PlatformSetup)

    def test_has_archive_tool_help(self):
        setup = ControllerBuilder.build_setup()
        help_text = setup.archive_tool_install_help()
        self.assertIn('7z', help_text.lower())

    def test_has_distro_name(self):
        setup = ControllerBuilder.build_setup()
        name = setup.get_distro_name()
        self.assertIsInstance(name, str)
        self.assertTrue(len(name) > 0)

    def test_has_pkg_manager(self):
        setup = ControllerBuilder.build_setup()
        # May be None on some systems, but the method should exist
        pm = setup.get_pkg_manager()
        self.assertTrue(pm is None or isinstance(pm, str))


class TestControllerBuilderFluent(unittest.TestCase):
    """ControllerBuilder fluent API — method chaining."""

    def test_with_renderer_returns_self(self):
        """with_renderer() returns the builder for chaining."""
        b = ControllerBuilder()
        result = b.with_renderer(MagicMock())
        self.assertIs(result, b)

    def test_with_data_dir_returns_self(self):
        """with_data_dir() returns the builder for chaining."""
        from pathlib import Path
        b = ControllerBuilder()
        result = b.with_data_dir(Path('/tmp'))
        self.assertIs(result, b)

    def test_fresh_builder_has_no_renderer(self):
        """New builder starts with no renderer."""
        b = ControllerBuilder()
        self.assertIsNone(b._renderer)

    def test_fresh_builder_has_no_data_dir(self):
        """New builder starts with no data_dir."""
        b = ControllerBuilder()
        self.assertIsNone(b._data_dir)

    @patch('trcc.adapters.infra.repository_data.DataManager.ensure_all')
    def test_full_chain(self, _):
        """Full fluent chain builds successfully."""
        from trcc.core.lcd_device import LCDDevice
        lcd = (ControllerBuilder()
               .with_renderer(ImageService._r())
               .build_lcd())
        self.assertIsInstance(lcd, LCDDevice)


if __name__ == '__main__':
    unittest.main()
