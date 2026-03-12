"""Tests for core/encoding.py — RGB565 encoding utilities."""

import struct
import unittest

from trcc.core.encoding import byte_order_for, rgb_to_bytes


class TestByteOrderFor(unittest.TestCase):
    """byte_order_for() — determines RGB565 byte order from device profile."""

    # ── FBL-based (delegates to DeviceProfile) ────────────────────────

    def test_fbl_100_big_endian(self):
        """FBL 100 (320x320) → big-endian."""
        self.assertEqual(byte_order_for('scsi', (320, 320), fbl=100), '>')

    def test_fbl_101_big_endian(self):
        self.assertEqual(byte_order_for('scsi', (320, 320), fbl=101), '>')

    def test_fbl_102_big_endian(self):
        self.assertEqual(byte_order_for('scsi', (320, 320), fbl=102), '>')

    def test_fbl_51_little_endian(self):
        """FBL 51 HID Type 2 → little-endian (SPIMode=2 only for SPI mode 1)."""
        self.assertEqual(byte_order_for('scsi', (320, 240), fbl=51), '<')

    def test_fbl_53_little_endian(self):
        """FBL 53 HID Type 2 → little-endian."""
        self.assertEqual(byte_order_for('scsi', (320, 240), fbl=53), '<')

    def test_fbl_36_little_endian(self):
        """FBL 36 (240x240) → little-endian."""
        self.assertEqual(byte_order_for('hid', (240, 240), fbl=36), '<')

    def test_fbl_50_little_endian(self):
        self.assertEqual(byte_order_for('scsi', (320, 240), fbl=50), '<')

    def test_fbl_72_little_endian(self):
        self.assertEqual(byte_order_for('hid', (480, 480), fbl=72), '<')

    def test_fbl_129_little_endian(self):
        self.assertEqual(byte_order_for('hid', (480, 480), fbl=129), '<')

    # ── Fallback (no FBL) ─────────────────────────────────────────────

    def test_no_fbl_320x320_big_endian(self):
        """320x320 without FBL → big-endian (safe default)."""
        self.assertEqual(byte_order_for('scsi', (320, 320)), '>')

    def test_no_fbl_480x480_little_endian(self):
        self.assertEqual(byte_order_for('scsi', (480, 480)), '<')

    def test_no_fbl_240x240_little_endian(self):
        self.assertEqual(byte_order_for('hid', (240, 240)), '<')

    def test_no_fbl_320x240_little_endian(self):
        self.assertEqual(byte_order_for('scsi', (320, 240)), '<')

    # ── Protocol doesn't affect FBL-based result ──────────────────────

    def test_protocol_irrelevant_with_fbl(self):
        """Protocol string is ignored when FBL is provided."""
        for proto in ('scsi', 'hid', 'bulk'):
            with self.subTest(proto=proto):
                self.assertEqual(byte_order_for(proto, (320, 320), fbl=100), '>')
                self.assertEqual(byte_order_for(proto, (480, 480), fbl=72), '<')

    # ── Every big-endian FBL ──────────────────────────────────────────

    def test_all_big_endian_fbls(self):
        """Every big-endian FBL returns '>'."""
        for fbl in (100, 101, 102):
            with self.subTest(fbl=fbl):
                self.assertEqual(byte_order_for('hid', (0, 0), fbl=fbl), '>')

    def test_all_little_endian_fbls(self):
        """Every non-BE, non-JPEG FBL returns '<'."""
        for fbl in (36, 37, 50, 51, 53, 58, 64, 72, 129):
            with self.subTest(fbl=fbl):
                self.assertEqual(byte_order_for('hid', (0, 0), fbl=fbl), '<')


class TestRgbToBytes(unittest.TestCase):
    """rgb_to_bytes() — single pixel RGB → RGB565 conversion."""

    def test_pure_red(self):
        """Pure red (255,0,0) → 0xF800 in RGB565."""
        result = rgb_to_bytes(255, 0, 0, '>')
        self.assertEqual(result, struct.pack('>H', 0xF800))

    def test_pure_green(self):
        """Pure green (0,255,0) → 0x07E0 in RGB565."""
        result = rgb_to_bytes(0, 255, 0, '>')
        self.assertEqual(result, struct.pack('>H', 0x07E0))

    def test_pure_blue(self):
        """Pure blue (0,0,255) → 0x001F in RGB565."""
        result = rgb_to_bytes(0, 0, 255, '>')
        self.assertEqual(result, struct.pack('>H', 0x001F))

    def test_white(self):
        """White (255,255,255) → 0xFFFF."""
        result = rgb_to_bytes(255, 255, 255, '>')
        self.assertEqual(result, struct.pack('>H', 0xFFFF))

    def test_black(self):
        """Black (0,0,0) → 0x0000."""
        result = rgb_to_bytes(0, 0, 0, '>')
        self.assertEqual(result, b'\x00\x00')

    def test_big_endian_byte_order(self):
        """Big-endian packs MSB first."""
        result = rgb_to_bytes(255, 0, 0, '>')
        self.assertEqual(result[0], 0xF8)
        self.assertEqual(result[1], 0x00)

    def test_little_endian_byte_order(self):
        """Little-endian packs LSB first."""
        result = rgb_to_bytes(255, 0, 0, '<')
        self.assertEqual(result[0], 0x00)
        self.assertEqual(result[1], 0xF8)

    def test_output_is_2_bytes(self):
        """Every pixel encodes to exactly 2 bytes."""
        for r, g, b in [(0, 0, 0), (128, 64, 32), (255, 255, 255)]:
            with self.subTest(r=r, g=g, b=b):
                self.assertEqual(len(rgb_to_bytes(r, g, b)), 2)

    def test_default_byte_order_is_big_endian(self):
        """Default byte_order parameter is '>'."""
        self.assertEqual(rgb_to_bytes(255, 0, 0), rgb_to_bytes(255, 0, 0, '>'))

    def test_bit_masking(self):
        """RGB565: R uses 5 bits (& 0xF8), G uses 6 bits (& 0xFC), B uses 5 bits (>> 3)."""
        # R=0b11111111 → top 5 bits = 0b11111 (31)
        # G=0b11111111 → top 6 bits = 0b111111 (63)
        # B=0b11111111 → top 5 bits = 0b11111 (31)
        result = struct.unpack('>H', rgb_to_bytes(255, 255, 255, '>'))[0]
        r5 = (result >> 11) & 0x1F
        g6 = (result >> 5) & 0x3F
        b5 = result & 0x1F
        self.assertEqual(r5, 31)
        self.assertEqual(g6, 63)
        self.assertEqual(b5, 31)

    def test_low_bits_discarded(self):
        """Low bits below RGB565 precision are discarded."""
        # R=0b00000111 → top 5 = 0 (masked by & 0xF8)
        # G=0b00000011 → top 6 = 0 (masked by & 0xFC)
        # B=0b00000111 → >> 3 = 0
        result = rgb_to_bytes(7, 3, 7, '>')
        self.assertEqual(result, b'\x00\x00')


if __name__ == '__main__':
    unittest.main()
