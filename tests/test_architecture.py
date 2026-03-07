"""Tests verifying OOP design patterns from CLAUDE.md.

Validates that the hexagonal architecture patterns are correctly implemented:
- Dependency Injection
- Strategy Pattern
- Data Transfer Objects (DTOs)
- Service isolation (no Qt dependencies)
- Builder pattern
"""
from __future__ import annotations

import ast
import inspect
import unittest
from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

from tests.conftest import get_pixel, make_device_service, make_test_surface, surface_size
from trcc.core.models import (
    DeviceInfo,
    ThemeData,
    ThemeInfo,
    VideoState,
)
from trcc.services.display import DisplayService
from trcc.services.image import ImageService
from trcc.services.media import MediaService
from trcc.services.overlay import OverlayService
from trcc.services.theme import ThemeService

SERVICES_DIR = Path(__file__).resolve().parent.parent / 'src' / 'trcc' / 'services'


# =============================================================================
# Dependency Injection — services are injectable, not hardcoded
# =============================================================================


class TestDependencyInjection(unittest.TestCase):
    """Services accept injected sub-services — never create their own."""

    def test_display_service_accepts_injected_sub_services(self):
        """DisplayService receives DeviceService, OverlayService, MediaService."""
        dev = make_device_service()
        ovl = OverlayService(renderer=ImageService._r())
        med = MediaService()
        svc = DisplayService(dev, ovl, med)
        self.assertIs(svc.devices, dev)
        self.assertIs(svc.overlay, ovl)
        self.assertIs(svc.media, med)

    @patch('trcc.adapters.infra.data_repository.DataManager.ensure_all')
    def test_builder_wires_services_into_lcd_device(self, _):
        """ControllerBuilder creates LCDDevice with properly wired services."""
        from trcc.core.builder import ControllerBuilder
        from trcc.core.lcd_device import LCDDevice

        lcd = ControllerBuilder().with_renderer(ImageService._r()).build_lcd()
        self.assertIsInstance(lcd, LCDDevice)


# =============================================================================
# Strategy Pattern — swappable behavior based on context
# =============================================================================


class TestStrategyPattern(unittest.TestCase):
    """Algorithms swap dynamically based on device/resolution context."""

    def test_byte_order_strategy_scsi_320(self):
        """SCSI 320x320 uses big-endian (Windows ImageTo565 compat)."""
        self.assertEqual(ImageService.byte_order_for('scsi', (320, 320)), '>')

    def test_byte_order_strategy_scsi_480(self):
        """SCSI non-320 uses little-endian."""
        self.assertEqual(ImageService.byte_order_for('scsi', (480, 480)), '<')

    def test_byte_order_strategy_hid(self):
        """HID uses big-endian for 320x320, little-endian for others."""
        self.assertEqual(ImageService.byte_order_for('hid', (320, 320)), '>')
        self.assertEqual(ImageService.byte_order_for('hid', (480, 480)), '<')
        self.assertEqual(ImageService.byte_order_for('hid', (320, 240)), '<')

    def test_rotation_strategy_0(self):
        img = make_test_surface(4, 8)
        result = ImageService.apply_rotation(img, 0)
        self.assertEqual(surface_size(result), (4, 8))

    def test_rotation_strategy_90(self):
        img = make_test_surface(4, 8)
        result = ImageService.apply_rotation(img, 90)
        self.assertEqual(surface_size(result), (8, 4))

    def test_rotation_strategy_180(self):
        img = make_test_surface(4, 8)
        result = ImageService.apply_rotation(img, 180)
        self.assertEqual(surface_size(result), (4, 8))

    def test_rotation_strategy_270(self):
        img = make_test_surface(4, 8)
        result = ImageService.apply_rotation(img, 270)
        self.assertEqual(surface_size(result), (8, 4))

    def test_brightness_strategy_100_noop(self):
        """100% brightness returns the same object (no processing)."""
        img = make_test_surface(2, 2, (200, 100, 50))
        result = ImageService.apply_brightness(img, 100)
        self.assertIs(result, img)

    def test_brightness_strategy_50_darkens(self):
        img = make_test_surface(1, 1, (200, 100, 50))
        result = ImageService.apply_brightness(img, 50)
        self.assertLess(get_pixel(result, 0, 0)[0], 200)

    def test_theme_filter_strategy_all(self):
        """'all' filter passes everything."""
        theme = ThemeInfo(name='anything')
        self.assertTrue(ThemeService._passes_filter(theme, 'all'))

    def test_theme_filter_strategy_user(self):
        """'user' filter passes Custom_ prefix."""
        theme = ThemeInfo(name='Custom_foo')
        self.assertTrue(ThemeService._passes_filter(theme, 'user'))

    def test_theme_filter_strategy_default_excludes_custom(self):
        """'default' filter excludes Custom_ prefix."""
        theme = ThemeInfo(name='Custom_foo')
        self.assertFalse(ThemeService._passes_filter(theme, 'default'))


# =============================================================================
# Data Transfer Objects — pure dataclasses, no logic
# =============================================================================


class TestDTOs(unittest.TestCase):
    """DTOs are strictly defined structures for cross-boundary data."""

    def test_theme_data_is_dataclass(self):
        """ThemeData is a dataclass with known fields."""
        field_names = {f.name for f in fields(ThemeData)}
        expected = {'background', 'animation_path', 'is_animated',
                    'mask', 'mask_position', 'mask_source_dir'}
        self.assertEqual(field_names, expected)

    def test_theme_data_defaults(self):
        """ThemeData defaults are all None/False — no surprise state."""
        data = ThemeData()
        self.assertIsNone(data.background)
        self.assertIsNone(data.animation_path)
        self.assertFalse(data.is_animated)
        self.assertIsNone(data.mask)
        self.assertIsNone(data.mask_position)
        self.assertIsNone(data.mask_source_dir)

    def test_theme_info_is_dataclass(self):
        field_names = {f.name for f in fields(ThemeInfo)}
        self.assertIn('name', field_names)
        self.assertIn('path', field_names)

    def test_device_info_is_dataclass(self):
        field_names = {f.name for f in fields(DeviceInfo)}
        self.assertIn('name', field_names)
        self.assertIn('path', field_names)
        self.assertIn('protocol', field_names)

    def test_video_state_is_dataclass(self):
        field_names = {f.name for f in fields(VideoState)}
        self.assertIn('current_frame', field_names)
        self.assertIn('total_frames', field_names)
        self.assertIn('fps', field_names)

    def test_theme_data_lives_in_models(self):
        """ThemeData is in core.models, not in services."""
        from trcc.core import models
        self.assertTrue(hasattr(models, 'ThemeData'))

    def test_device_info_lives_in_models(self):
        from trcc.core import models
        self.assertTrue(hasattr(models, 'DeviceInfo'))


# =============================================================================
# Service Isolation — no Qt/GUI dependencies in services
# =============================================================================


class TestServiceIsolation(unittest.TestCase):
    """Services are pure Python — no Qt/PySide6/PyQt6 imports."""

    def _get_imports(self, filepath: Path) -> set[str]:
        """Parse a Python file and return all imported module names."""
        source = filepath.read_text()
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split('.')[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split('.')[0])
        return imports

    def test_no_qt_in_services(self):
        """No service file imports PySide6 or PyQt6."""
        qt_modules = {'PySide6', 'PyQt6', 'PyQt5'}
        for py_file in SERVICES_DIR.glob('*.py'):
            imports = self._get_imports(py_file)
            offenders = imports & qt_modules
            self.assertEqual(
                offenders, set(),
                f"{py_file.name} imports Qt: {offenders}")

    def test_no_qt_in_models(self):
        """Models are pure dataclasses — no Qt."""
        models_path = SERVICES_DIR.parent / 'core' / 'models.py'
        qt_modules = {'PySide6', 'PyQt6', 'PyQt5'}
        imports = self._get_imports(models_path)
        offenders = imports & qt_modules
        self.assertEqual(offenders, set(),
                         f"models.py imports Qt: {offenders}")

    def test_services_init_exports(self):
        """services/__init__.py exports all 6 services."""
        from trcc import services
        expected = {'DeviceService', 'DisplayService', 'ImageService',
                    'MediaService', 'OverlayService', 'ThemeService'}
        for name in expected:
            self.assertTrue(
                hasattr(services, name),
                f"services missing export: {name}")


# =============================================================================
# Service Statelessness — stateless services have only static methods
# =============================================================================


class TestServiceStatelessness(unittest.TestCase):
    """Stateless services (ImageService) use only static methods."""

    def test_image_service_all_static(self):
        """Every public method on ImageService is @staticmethod."""
        for name, method in inspect.getmembers(ImageService, predicate=inspect.isfunction):
            if not name.startswith('_'):
                self.assertTrue(
                    isinstance(inspect.getattr_static(ImageService, name), staticmethod),
                    f"ImageService.{name} should be @staticmethod")

    def test_image_service_no_init_state(self):
        """ImageService has no __init__ — fully stateless."""
        # ImageService inherits object.__init__, has no custom state
        svc = ImageService()
        self.assertEqual(len(svc.__dict__), 0)


if __name__ == '__main__':
    unittest.main()
