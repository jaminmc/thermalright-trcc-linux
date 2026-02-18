"""Unified segment display renderer for all LED device styles.

OOP architecture separating layout data (class attributes) from rendering
logic (methods).  Each style subclass holds its LED index mappings as data
and implements ``compute_mask()`` as business logic.

Class hierarchy::

    SegmentDisplay (ABC)     — encoding tables (data) + encoding methods (logic)
    ├── AX120Display         — style 1:  30 LEDs, 3-digit, 4-phase rotation
    ├── PA120Display         — style 2:  84 LEDs, 4 simultaneous values
    ├── AK120Display         — style 3:  69 LEDs, 2-phase CPU/GPU
    ├── LC1Display           — style 4:  38 LEDs, mode-based 3-phase
    ├── LF8Display           — style 5/11: 93 LEDs, 4-metric 2-phase
    │   └── LF12Display      — style 6:  124 LEDs = LF8 + 31 decoration
    ├── LF10Display          — style 7:  116 LEDs, 13-segment + decoration
    ├── CZ1Display           — style 8:  18 LEDs, 2-digit 4-phase
    ├── LC2Display           — style 9:  61 LEDs, clock display
    └── LF11Display          — style 10: 38 LEDs, 4-phase sensor

Reverse-engineered from UCScreenLED.cs (SetMyNumeral variants) and
FormLED.cs (GetVal rotation logic).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from ...core.models import HardwareMetrics

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Base class — encoding tables (data) + encoding methods (logic)
# ═══════════════════════════════════════════════════════════════════════

class SegmentDisplay(ABC):
    """Base class for LED segment display renderers.

    **Data** lives in class attributes:
        - Encoding tables (``CHAR_7SEG``, ``CHAR_13SEG``, wire orders)
        - Subclass LED index constants (DIGITS, ALWAYS_ON, PHASES, etc.)

    **Logic** lives in methods:
        - Shared encoding helpers (``_encode_3digit``, ``_encode_2digit_partial``, etc.)
        - Subclass ``compute_mask()`` implementations
    """

    # ── 7-Segment encoding data ────────────────────────────────────

    CHAR_7SEG: Dict[str, Set[str]] = {
        '0': {'a', 'b', 'c', 'd', 'e', 'f'},
        '1': {'b', 'c'},
        '2': {'a', 'b', 'd', 'e', 'g'},
        '3': {'a', 'b', 'c', 'd', 'g'},
        '4': {'b', 'c', 'f', 'g'},
        '5': {'a', 'c', 'd', 'f', 'g'},
        '6': {'a', 'c', 'd', 'e', 'f', 'g'},
        '7': {'a', 'b', 'c'},
        '8': {'a', 'b', 'c', 'd', 'e', 'f', 'g'},
        '9': {'a', 'b', 'c', 'd', 'f', 'g'},
        ' ': set(),
        'C': {'a', 'd', 'e', 'f'},
        'F': {'a', 'e', 'f', 'g'},
        'H': {'b', 'c', 'e', 'f', 'g'},
        'G': {'a', 'b', 'c', 'd', 'f', 'g'},
    }

    WIRE_7SEG = ('a', 'b', 'c', 'd', 'e', 'f', 'g')

    # ── 13-Segment encoding data (style 7 / LF10) ─────────────────

    CHAR_13SEG: Dict[str, Set[str]] = {
        '0': set(),  # hundreds=0 → blank (leading zero suppression)
        '1': {'c', 'd', 'e', 'f', 'g'},
        '2': {'a', 'b', 'c', 'd', 'e', 'g', 'h', 'i', 'j', 'k', 'm'},
        '3': {'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'k', 'm'},
        '4': {'a', 'c', 'd', 'e', 'f', 'g', 'k', 'l', 'm'},
        '5': {'a', 'b', 'c', 'e', 'f', 'g', 'h', 'i', 'k', 'l', 'm'},
        '6': {'a', 'b', 'c', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm'},
        '7': {'a', 'b', 'c', 'd', 'e', 'f', 'g'},
        '8': {'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm'},
        '9': {'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'k', 'l', 'm'},
        ' ': set(),
    }

    WIRE_13SEG = ('a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm')

    # ── Abstract interface ─────────────────────────────────────────

    @property
    @abstractmethod
    def mask_size(self) -> int:
        """Total LED count for this style's mask."""

    @property
    @abstractmethod
    def phase_count(self) -> int:
        """Number of rotation phases."""

    @abstractmethod
    def compute_mask(
        self,
        metrics: HardwareMetrics,
        phase: int = 0,
        temp_unit: str = "C",
        **kw: Any,
    ) -> List[bool]:
        """Compute boolean LED mask from sensor metrics and rotation phase."""



    # ── Temperature conversion ────────────────────────────────────

    @staticmethod
    def _to_display_temp(celsius: float, temp_unit: str) -> int:
        """Convert temperature for display. C#: value * 9 / 5 + 32."""
        v = int(celsius)
        if temp_unit == "F":
            v = v * 9 // 5 + 32
        return v

    # ── Shared encoding logic ──────────────────────────────────────

    def _encode_3digit(
        self,
        value: int,
        digit_leds: Tuple[Tuple[int, ...], ...],
        mask: List[bool],
    ) -> None:
        """Encode 0-999 into 3 seven-segment digits with leading-zero suppression."""
        v = max(0, min(999, value))
        d_h, d_t, d_o = v // 100, (v % 100) // 10, v % 10
        chars = [str(d_h), str(d_t), str(d_o)]
        if d_h == 0:
            chars[0] = ' '
            if d_t == 0:
                chars[1] = ' '
        for digit_idx, ch in enumerate(chars):
            segs = self.CHAR_7SEG.get(ch, set())
            leds = digit_leds[digit_idx]
            for wire_idx, seg_name in enumerate(self.WIRE_7SEG):
                if seg_name in segs:
                    mask[leds[wire_idx]] = True

    def _encode_4digit(
        self,
        value: int,
        digit_leds: Tuple[Tuple[int, ...], ...],
        mask: List[bool],
    ) -> None:
        """Encode 0-9999 into 4 seven-segment digits with leading-zero suppression.

        C# SetMyNumeral MHz: num4=thousands, num=hundreds, num2=tens, num3=ones.
        """
        v = max(0, min(9999, value))
        d_th, d_h = v // 1000, (v % 1000) // 100
        d_t, d_o = (v % 100) // 10, v % 10
        chars = [str(d_th), str(d_h), str(d_t), str(d_o)]
        if d_th == 0:
            chars[0] = ' '
            if d_h == 0:
                chars[1] = ' '
                if d_t == 0:
                    chars[2] = ' '
        for digit_idx, ch in enumerate(chars):
            segs = self.CHAR_7SEG.get(ch, set())
            leds = digit_leds[digit_idx]
            for wire_idx, seg_name in enumerate(self.WIRE_7SEG):
                if seg_name in segs:
                    mask[leds[wire_idx]] = True

    def _encode_5digit(
        self,
        value: int,
        digit_leds: Tuple[Tuple[int, ...], ...],
        mask: List[bool],
    ) -> None:
        """Encode 0-99999 into 5 seven-segment digits with leading-zero suppression."""
        v = max(0, min(99999, value))
        digits = [(v // 10000), (v % 10000) // 1000, (v % 1000) // 100,
                  (v % 100) // 10, v % 10]
        chars = [str(d) for d in digits]
        # Suppress leading zeros
        for i in range(4):  # don't suppress ones digit
            if digits[i] == 0:
                chars[i] = ' '
            else:
                break
        for digit_idx, ch in enumerate(chars):
            segs = self.CHAR_7SEG.get(ch, set())
            leds = digit_leds[digit_idx]
            for wire_idx, seg_name in enumerate(self.WIRE_7SEG):
                if seg_name in segs:
                    mask[leds[wire_idx]] = True

    def _encode_2digit_partial(
        self,
        value: int,
        digit_leds: Tuple[Tuple[int, ...], ...],
        partial_bc: Optional[Tuple[int, int]],
        mask: List[bool],
    ) -> None:
        """Encode 0-199 into 2 full digits + optional partial '1' for hundreds."""
        v = max(0, min(199, value))
        if v >= 100 and partial_bc:
            mask[partial_bc[0]] = True
            mask[partial_bc[1]] = True
            v -= 100
        d_t, d_o = v // 10, v % 10
        chars = [str(d_t) if d_t > 0 else ' ', str(d_o)]
        for digit_idx, ch in enumerate(chars):
            segs = self.CHAR_7SEG.get(ch, set())
            leds = digit_leds[digit_idx]
            for wire_idx, seg_name in enumerate(self.WIRE_7SEG):
                if seg_name in segs:
                    mask[leds[wire_idx]] = True

    def _encode_unit(
        self,
        mode: int,
        digit_leds: Tuple[int, ...],
        mask: List[bool],
    ) -> None:
        """Encode unit symbol: 0=C, -1=F, 1=MHz('H'), 2=GB('G')."""
        ch = {0: 'C', -1: 'F', 1: 'H', 2: 'G'}.get(mode, ' ')
        segs = self.CHAR_7SEG.get(ch, set())
        for wire_idx, seg_name in enumerate(self.WIRE_7SEG):
            if seg_name in segs:
                mask[digit_leds[wire_idx]] = True

    def _encode_2digit(
        self,
        value: int,
        digit_leds: Tuple[Tuple[int, ...], ...],
        mask: List[bool],
    ) -> None:
        """Encode 0-99 into 2 seven-segment digits."""
        v = max(0, min(99, value))
        d_t, d_o = v // 10, v % 10
        chars = [str(d_t) if d_t > 0 else ' ', str(d_o)]
        for digit_idx, ch in enumerate(chars):
            segs = self.CHAR_7SEG.get(ch, set())
            leds = digit_leds[digit_idx]
            for wire_idx, seg_name in enumerate(self.WIRE_7SEG):
                if seg_name in segs:
                    mask[leds[wire_idx]] = True

    def _encode_clock_digit(
        self,
        value: int,
        digit_leds: Tuple[int, ...],
        mask: List[bool],
        suppress_zero: bool = False,
    ) -> None:
        """Encode single digit 0-9 for clock display."""
        if suppress_zero and value == 0:
            return
        segs = self.CHAR_7SEG.get(str(value), set())
        for wire_idx, seg_name in enumerate(self.WIRE_7SEG):
            if seg_name in segs:
                mask[digit_leds[wire_idx]] = True

    def _encode_3digit_13seg(
        self,
        value: int,
        digits_13: Tuple[Tuple[int, ...], ...],
        mask: List[bool],
    ) -> None:
        """Encode value with 13-seg hundreds, 7-seg tens/ones."""
        v = max(0, min(999, value))
        d_h, d_t, d_o = v // 100, (v % 100) // 10, v % 10

        # Hundreds: 13-segment encoding
        segs_h = self.CHAR_13SEG.get(str(d_h), set())
        leds_h = digits_13[0]
        for wire_idx, seg_name in enumerate(self.WIRE_13SEG):
            if seg_name in segs_h:
                mask[leds_h[wire_idx]] = True

        # Tens: 7-segment with leading zero suppression
        if not (d_h == 0 and d_t == 0):
            segs_t = self.CHAR_7SEG.get(str(d_t), set())
            leds_t = digits_13[1]
            for wire_idx, seg_name in enumerate(self.WIRE_7SEG):
                if seg_name in segs_t:
                    mask[leds_t[wire_idx]] = True

        # Ones: 7-segment (always shown)
        segs_o = self.CHAR_7SEG.get(str(d_o), set())
        leds_o = digits_13[2]
        for wire_idx, seg_name in enumerate(self.WIRE_7SEG):
            if seg_name in segs_o:
                mask[leds_o[wire_idx]] = True


# ═══════════════════════════════════════════════════════════════════════
# Style 1 — AX120_DIGITAL (30 LEDs, 3 digits, 4-phase rotation)
# ═══════════════════════════════════════════════════════════════════════

class AX120Display(SegmentDisplay):
    """Style 1 — AX120 Digital: 30-LED, 3-digit, 4-phase sensor rotation.

    Layout: [always-on(2)][CPU(2)][GPU(2)][C][F][%][Digit1(7)][Digit2(7)][Digit3(7)]
    Phases: CPU temp -> CPU usage -> GPU temp -> GPU usage
    """

    # ── Layout data ────────────────────────────────────────────────
    ALWAYS_ON = (0, 1)
    CELSIUS = 6
    FAHRENHEIT = 7
    PERCENT = 8
    DIGITS: Tuple[Tuple[int, ...], ...] = (
        (9, 10, 11, 12, 13, 14, 15),
        (16, 17, 18, 19, 20, 21, 22),
        (23, 24, 25, 26, 27, 28, 29),
    )
    PHASES = (
        ('cpu_temp', (2, 3), True),
        ('cpu_percent', (2, 3), False),
        ('gpu_temp', (4, 5), True),
        ('gpu_usage', (4, 5), False),
    )

    # ── Interface ──────────────────────────────────────────────────

    @property
    def mask_size(self) -> int:
        return 30

    @property
    def phase_count(self) -> int:
        return 4

    def compute_mask(self, metrics: HardwareMetrics, phase: int = 0,
                     temp_unit: str = "C", **kw: Any) -> List[bool]:
        mask = [False] * 30
        for idx in self.ALWAYS_ON:
            mask[idx] = True

        metric_key, source_leds, is_temp = self.PHASES[phase % 4]
        for idx in source_leds:
            mask[idx] = True

        if is_temp:
            mask[self.FAHRENHEIT if temp_unit == "F" else self.CELSIUS] = True
        else:
            mask[self.PERCENT] = True

        value = int(getattr(metrics, metric_key, 0))
        if is_temp:
            value = self._to_display_temp(value, temp_unit)
        self._encode_3digit(value, self.DIGITS, mask)
        return mask


# ═══════════════════════════════════════════════════════════════════════
# Style 2 — PA120_DIGITAL (84 LEDs, simultaneous 4-value, remap)
# ═══════════════════════════════════════════════════════════════════════

class PA120Display(SegmentDisplay):
    """Style 2 — PA120 Digital: 84-LED, simultaneous CPU/GPU temp+usage.

    Shows all 4 metrics at once (no rotation).  Remapped style.
    Layout: [indicators(10)][cpuTemp 3d][cpuUse 2d+partial][gap][gpuTemp 3d][gpuUse 1d+partial+partial]
    """

    # ── Layout data (C# UCScreenLED.cs indices) ────────────────────
    # Index 0 unused (WATT=1 not used for PA120).  Index 30 = gap.
    # SSD1/HSD1/BFB1 are aliases — same physical LED as SSD/HSD/BFB.
    CPU1, CPU2 = 2, 3        # Cpu1, Cpu2 indicators
    GPU1, GPU2 = 4, 5        # Gpu1, Gpu2 indicators
    SSD, HSD = 6, 7          # °C, °F (shared for CPU+GPU side)
    BFB = 8                   # % (shared for CPU+GPU side)
    SSD1, HSD1, BFB1 = 6, 7, 8  # aliases (same LED index as SSD/HSD/BFB)

    CPU_TEMP_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (9, 10, 11, 12, 13, 14, 15),   # LEDA1..LEDG1
        (16, 17, 18, 19, 20, 21, 22),  # LEDA2..LEDG2
        (23, 24, 25, 26, 27, 28, 29),  # LEDA3..LEDG3
    )
    CPU_USE_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (31, 32, 33, 34, 35, 36, 37),  # LEDA4..LEDG4 (index 30 = gap)
        (38, 39, 40, 41, 42, 43, 44),  # LEDA5..LEDG5
    )
    CPU_USE_PARTIAL = (80, 81)   # LEDB11/LEDC11 overflow for "1xx"

    GPU_TEMP_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (45, 46, 47, 48, 49, 50, 51),  # LEDA6..LEDG6
        (52, 53, 54, 55, 56, 57, 58),  # LEDA7..LEDG7
        (59, 60, 61, 62, 63, 64, 65),  # LEDA8..LEDG8
    )
    GPU_USE_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (66, 67, 68, 69, 70, 71, 72),  # LEDA9..LEDG9
        (73, 74, 75, 76, 77, 78, 79),  # LEDA10..LEDG10
    )
    GPU_USE_PARTIAL = (82, 83)   # LEDB12/LEDC12 overflow for "1xx"

    # ── Interface ──────────────────────────────────────────────────

    @property
    def mask_size(self) -> int:
        return 84

    @property
    def phase_count(self) -> int:
        return 1

    def compute_mask(self, metrics: HardwareMetrics, phase: int = 0,
                     temp_unit: str = "C", **kw: Any) -> List[bool]:
        mask = [False] * 84

        # Always-on indicators
        for idx in (self.CPU1, self.CPU2, self.GPU1, self.GPU2,
                    self.BFB, self.BFB1):
            mask[idx] = True

        # Temperature unit indicators
        if temp_unit == "C":
            mask[self.SSD] = True
            mask[self.SSD1] = True
        else:
            mask[self.HSD] = True
            mask[self.HSD1] = True

        # All 4 metrics simultaneously
        self._encode_3digit(
            self._to_display_temp(getattr(metrics, 'cpu_temp', 0), temp_unit),
            self.CPU_TEMP_DIGITS, mask,
        )
        self._encode_2digit_partial(
            int(getattr(metrics, 'cpu_percent', 0)),
            self.CPU_USE_DIGITS, self.CPU_USE_PARTIAL, mask,
        )
        self._encode_3digit(
            self._to_display_temp(getattr(metrics, 'gpu_temp', 0), temp_unit),
            self.GPU_TEMP_DIGITS, mask,
        )

        # GPU usage: 2 full digits + partial overflow (same pattern as CPU usage)
        self._encode_2digit_partial(
            int(getattr(metrics, 'gpu_usage', 0)),
            self.GPU_USE_DIGITS, self.GPU_USE_PARTIAL, mask,
        )

        return mask


# ═══════════════════════════════════════════════════════════════════════
# Style 3 — AK120_DIGITAL (64 LEDs, 2-phase CPU/GPU, remap)
# ═══════════════════════════════════════════════════════════════════════

class AK120Display(SegmentDisplay):
    """Style 3 — AK120 Digital: 69-LED mask, 2-phase CPU/GPU rotation.

    Shows watt + temp + usage per phase (CPU or GPU).  Remapped style.
    """

    # ── Layout data ────────────────────────────────────────────────
    CPU1 = 0
    WATT = 1
    SSD = 2       # °C
    HSD = 3       # °F
    BFB = 4       # %
    GPU1 = 5

    WATT_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (6, 7, 8, 9, 10, 11, 12),
        (13, 14, 15, 16, 17, 18, 19),
        (20, 21, 22, 23, 24, 25, 26),
    )
    TEMP_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (27, 28, 29, 30, 31, 32, 33),
        (34, 35, 36, 37, 38, 39, 40),
        (41, 42, 43, 44, 45, 46, 47),
    )
    USE_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (48, 49, 50, 51, 52, 53, 54),
        (55, 56, 57, 58, 59, 60, 61),
    )
    USE_PARTIAL = (62, 63)

    PHASES = (
        ('cpu_temp', 'cpu_percent', 'cpu_power', CPU1),
        ('gpu_temp', 'gpu_usage', 'gpu_power', GPU1),
    )

    # ── Interface ──────────────────────────────────────────────────

    @property
    def mask_size(self) -> int:
        return 69

    @property
    def phase_count(self) -> int:
        return 2

    def compute_mask(self, metrics: HardwareMetrics, phase: int = 0,
                     temp_unit: str = "C", **kw: Any) -> List[bool]:
        mask = [False] * 69

        mask[self.WATT] = True
        mask[self.BFB] = True

        temp_key, use_key, watt_key, source_idx = self.PHASES[phase % 2]
        mask[source_idx] = True
        mask[self.SSD if temp_unit == "C" else self.HSD] = True

        self._encode_3digit(int(getattr(metrics, watt_key, 0)), self.WATT_DIGITS, mask)
        self._encode_3digit(self._to_display_temp(getattr(metrics, temp_key, 0), temp_unit), self.TEMP_DIGITS, mask)
        self._encode_2digit_partial(
            int(getattr(metrics, use_key, 0)), self.USE_DIGITS, self.USE_PARTIAL, mask,
        )
        return mask


# ═══════════════════════════════════════════════════════════════════════
# Style 4 — LC1 (31 LEDs, mode-based 3-phase, remap)
# ═══════════════════════════════════════════════════════════════════════

class LC1Display(SegmentDisplay):
    """Style 4 — LC1: 38-LED mask, mode-based 3-phase (temp/MHz/GB).

    NVMe memory device — displays different metrics with unit symbol.
    Sub-style 0 = memory mode (temp/MHz*DDR/GB).
    Sub-style 1 = hard disk mode (temp/RPM/MHz).
    Remapped style.
    """

    # ── Layout data ────────────────────────────────────────────────
    SSD = 0       # °C/°F indicator
    MTNO = 1      # MHz indicator
    GNO = 2       # GB indicator

    DIGITS: Tuple[Tuple[int, ...], ...] = (
        (3, 4, 5, 6, 7, 8, 9),
        (10, 11, 12, 13, 14, 15, 16),
        (17, 18, 19, 20, 21, 22, 23),
    )
    UNIT_DIGIT = (24, 25, 26, 27, 28, 29, 30)

    # Sub-style 0: memory mode phases
    PHASES_MEM = (
        ('mem_temp', 0, SSD),     # temperature
        ('mem_clock', 1, MTNO),   # MHz (* memoryRatio)
        ('mem_used', 2, GNO),     # GB
    )
    # Sub-style 1: hard disk mode phases
    PHASES_DISK = (
        ('disk_temp', 0, SSD),    # temperature
        ('disk_read', 1, MTNO),   # RPM/MHz
        ('disk_activity', 2, GNO),  # activity
    )

    # ── Interface ──────────────────────────────────────────────────

    @property
    def mask_size(self) -> int:
        return 38

    @property
    def phase_count(self) -> int:
        return 3

    # All 4 digit positions for 4-digit modes (MHz/GB)
    ALL_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (3, 4, 5, 6, 7, 8, 9),
        (10, 11, 12, 13, 14, 15, 16),
        (17, 18, 19, 20, 21, 22, 23),
        (24, 25, 26, 27, 28, 29, 30),
    )

    def compute_mask(self, metrics: HardwareMetrics, phase: int = 0,
                     temp_unit: str = "C", **kw: Any) -> List[bool]:
        mask = [False] * 38

        sub_style = kw.get('sub_style', 0)
        memory_ratio = kw.get('memory_ratio', 2)
        phases = self.PHASES_DISK if sub_style == 1 else self.PHASES_MEM

        metric_key, mode, indicator_idx = phases[phase % 3]
        mask[indicator_idx] = True
        value = int(getattr(metrics, metric_key, 0))

        if mode == 0:
            # Temperature: 3 digits + C/F unit symbol on digit 4
            if temp_unit == "F":
                value = self._to_display_temp(value, "F")
            self._encode_3digit(value, self.DIGITS, mask)
            unit_mode = -1 if temp_unit == "F" else 0
            self._encode_unit(unit_mode, self.UNIT_DIGIT, mask)
        else:
            # MHz/GB/RPM: 4-digit number using all 4 positions
            if sub_style == 0 and mode == 1:
                value *= memory_ratio  # DDR multiplier for memory clock
            self._encode_4digit(value, self.ALL_DIGITS, mask)

        return mask


# ═══════════════════════════════════════════════════════════════════════
# Style 5/11 — LF8/LF15 (93 LEDs, 4-metric 2-phase CPU/GPU)
# ═══════════════════════════════════════════════════════════════════════

class LF8Display(SegmentDisplay):
    """Style 5/11 — LF8/LF15: 93-LED, 4-metric 2-phase CPU/GPU.

    Shows temp + watt + MHz + usage per phase (CPU or GPU).
    Style 11 (LF15) uses identical layout.
    """

    # ── Layout data ────────────────────────────────────────────────
    CPU1 = 0
    GPU1 = 1
    SSD = 2
    HSD = 3
    WATT = 4
    MHZ = 5
    BFB = 6

    TEMP_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (7, 8, 9, 10, 11, 12, 13),
        (14, 15, 16, 17, 18, 19, 20),
        (21, 22, 23, 24, 25, 26, 27),
    )
    WATT_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (28, 29, 30, 31, 32, 33, 34),
        (35, 36, 37, 38, 39, 40, 41),
        (42, 43, 44, 45, 46, 47, 48),
    )
    MHZ_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (49, 50, 51, 52, 53, 54, 55),    # seg7 = thousands
        (56, 57, 58, 59, 60, 61, 62),    # seg8 = hundreds
        (63, 64, 65, 66, 67, 68, 69),    # seg9 = tens
        (70, 71, 72, 73, 74, 75, 76),    # seg10 = ones
    )
    USE_DIGITS: Tuple[Tuple[int, ...], ...] = (
        (77, 78, 79, 80, 81, 82, 83),    # seg11 = tens
        (84, 85, 86, 87, 88, 89, 90),    # seg12 = ones
    )
    USE_PARTIAL = (91, 92)                    # seg13 partial = hundreds (B,C)

    PHASES = (
        ('cpu_temp', 'cpu_power', 'cpu_freq', 'cpu_percent', CPU1),
        ('gpu_temp', 'gpu_power', 'gpu_clock', 'gpu_usage', GPU1),
    )

    # ── Interface ──────────────────────────────────────────────────

    @property
    def mask_size(self) -> int:
        return 93

    @property
    def phase_count(self) -> int:
        return 2

    def compute_mask(self, metrics: HardwareMetrics, phase: int = 0,
                     temp_unit: str = "C", **kw: Any) -> List[bool]:
        mask = [False] * self.mask_size

        mask[self.WATT] = True
        mask[self.MHZ] = True
        mask[self.BFB] = True

        temp_key, watt_key, mhz_key, use_key, src = self.PHASES[phase % 2]
        mask[src] = True
        mask[self.SSD if temp_unit == "C" else self.HSD] = True

        self._encode_3digit(self._to_display_temp(getattr(metrics, temp_key, 0), temp_unit), self.TEMP_DIGITS, mask)
        self._encode_3digit(int(getattr(metrics, watt_key, 0)), self.WATT_DIGITS, mask)
        self._encode_4digit(int(getattr(metrics, mhz_key, 0)), self.MHZ_DIGITS, mask)
        self._encode_2digit_partial(
            int(getattr(metrics, use_key, 0)), self.USE_DIGITS, self.USE_PARTIAL, mask,
        )
        return mask


# ═══════════════════════════════════════════════════════════════════════
# Style 6 — LF12 (124 LEDs = LF8 + 31 decoration)
# ═══════════════════════════════════════════════════════════════════════

class LF12Display(LF8Display):
    """Style 6 — LF12: 124-LED = LF8 digits + 31 always-on decoration LEDs."""

    # ── Additional layout data ─────────────────────────────────────
    DECORATION = tuple(range(93, 124))

    @property
    def mask_size(self) -> int:
        return 124

    def compute_mask(self, metrics: HardwareMetrics, phase: int = 0,
                     temp_unit: str = "C", **kw: Any) -> List[bool]:
        # Compute digit mask using parent's logic on a 124-element mask
        mask = [False] * 124

        mask[self.WATT] = True
        mask[self.MHZ] = True
        mask[self.BFB] = True

        temp_key, watt_key, mhz_key, use_key, src = self.PHASES[phase % 2]
        mask[src] = True
        mask[self.SSD if temp_unit == "C" else self.HSD] = True

        self._encode_3digit(self._to_display_temp(getattr(metrics, temp_key, 0), temp_unit), self.TEMP_DIGITS, mask)
        self._encode_3digit(int(getattr(metrics, watt_key, 0)), self.WATT_DIGITS, mask)
        self._encode_4digit(int(getattr(metrics, mhz_key, 0)), self.MHZ_DIGITS, mask)
        self._encode_2digit_partial(
            int(getattr(metrics, use_key, 0)), self.USE_DIGITS, self.USE_PARTIAL, mask,
        )

        # Decoration LEDs — always on
        for idx in self.DECORATION:
            mask[idx] = True
        return mask


# ═══════════════════════════════════════════════════════════════════════
# Style 7 — LF10 (116 LEDs, 13-segment, simultaneous CPU+GPU temp)
# ═══════════════════════════════════════════════════════════════════════

class LF10Display(SegmentDisplay):
    """Style 7 — LF10: 116-LED, 13-segment CPU+GPU temp + 32 decoration.

    6 digits x 13 LEDs each.  Hundreds use 13-segment encoding,
    tens/ones use standard 7-segment.
    """

    # ── Layout data ────────────────────────────────────────────────
    CPU1 = 0
    SSD = 1       # °C (CPU)
    HSD = 2       # °F (CPU)
    GPU1 = 3
    SSD1 = 4      # °C (GPU)
    HSD1 = 5      # °F (GPU)

    DIGIT_LEDS_13: Tuple[Tuple[int, ...], ...] = (
        tuple(range(6, 19)),     # Digit 1: CPU temp hundreds (13 LEDs)
        tuple(range(19, 32)),    # Digit 2: CPU temp tens
        tuple(range(32, 45)),    # Digit 3: CPU temp ones
        tuple(range(45, 58)),    # Digit 4: GPU temp hundreds
        tuple(range(58, 71)),    # Digit 5: GPU temp tens
        tuple(range(71, 84)),    # Digit 6: GPU temp ones
    )

    DECORATION = tuple(range(84, 116))

    # ── Interface ──────────────────────────────────────────────────

    @property
    def mask_size(self) -> int:
        return 116

    @property
    def phase_count(self) -> int:
        return 1

    def compute_mask(self, metrics: HardwareMetrics, phase: int = 0,
                     temp_unit: str = "C", **kw: Any) -> List[bool]:
        mask = [False] * 116

        mask[self.CPU1] = True
        mask[self.GPU1] = True

        if temp_unit == "C":
            mask[self.SSD] = True
            mask[self.SSD1] = True
        else:
            mask[self.HSD] = True
            mask[self.HSD1] = True

        # CPU temp (digits 1-3)
        self._encode_3digit_13seg(
            self._to_display_temp(getattr(metrics, 'cpu_temp', 0), temp_unit),
            self.DIGIT_LEDS_13[0:3], mask,
        )
        # GPU temp (digits 4-6)
        self._encode_3digit_13seg(
            self._to_display_temp(getattr(metrics, 'gpu_temp', 0), temp_unit),
            self.DIGIT_LEDS_13[3:6], mask,
        )

        for idx in self.DECORATION:
            mask[idx] = True
        return mask


# ═══════════════════════════════════════════════════════════════════════
# Style 8 — CZ1 (18 LEDs, 2 digits, 4-phase rotation)
# ═══════════════════════════════════════════════════════════════════════

class CZ1Display(SegmentDisplay):
    """Style 8 — CZ1: 18-LED, 2-digit, 4-phase sensor rotation.

    Smallest digit display.  4 indicator LEDs + 2 x 7-segment digits.
    """

    # ── Layout data ────────────────────────────────────────────────
    CPU1 = 0
    GPU1 = 1
    CPU2 = 2
    GPU2 = 3

    DIGITS: Tuple[Tuple[int, ...], ...] = (
        (4, 5, 6, 7, 8, 9, 10),
        (11, 12, 13, 14, 15, 16, 17),
    )

    PHASES = (
        ('cpu_temp', (CPU1,)),
        ('cpu_percent', (CPU2,)),
        ('gpu_temp', (GPU1,)),
        ('gpu_usage', (GPU2,)),
    )

    # ── Interface ──────────────────────────────────────────────────

    @property
    def mask_size(self) -> int:
        return 18

    @property
    def phase_count(self) -> int:
        return 4

    def compute_mask(self, metrics: HardwareMetrics, phase: int = 0,
                     temp_unit: str = "C", **kw: Any) -> List[bool]:
        mask = [False] * 18

        metric_key, indicator_on = self.PHASES[phase % 4]
        for idx in indicator_on:
            mask[idx] = True

        value = int(getattr(metrics, metric_key, 0))
        if 'temp' in metric_key:
            value = self._to_display_temp(value, temp_unit)
        self._encode_2digit(value, self.DIGITS, mask)
        return mask


# ═══════════════════════════════════════════════════════════════════════
# Style 9 — LC2 (61 LEDs, clock display, 7 decoration)
# ═══════════════════════════════════════════════════════════════════════

class LC2Display(SegmentDisplay):
    """Style 9 — LC2: 61-LED clock display (HH:MM + MM/DD + decoration).

    Uses datetime instead of sensor metrics.  Indices 0-2 are reserved.
    """

    # ── Layout data ────────────────────────────────────────────────
    # Indices 0-2: time colon dots (0, 1) + date separator (2) — always on
    COLON_AND_SEP = (0, 1, 2)

    DIGITS: Tuple[Tuple[int, ...], ...] = (
        (3, 4, 5, 6, 7, 8, 9),        # Hour tens
        (10, 11, 12, 13, 14, 15, 16),  # Hour ones
        (17, 18, 19, 20, 21, 22, 23),  # Minute tens
        (24, 25, 26, 27, 28, 29, 30),  # Minute ones
        (31, 32, 33, 34, 35, 36, 37),  # Month ones (full digit)
        (38, 39, 40, 41, 42, 43, 44),  # Day tens (full digit)
        (45, 46, 47, 48, 49, 50, 51),  # Day ones (full digit)
    )
    MONTH_TENS_BC = (52, 53)  # B8/C8 — partial for month tens (0 or 1)
    DECORATION = tuple(range(54, 61))  # 7 weekday bar indicators

    # ── Interface ──────────────────────────────────────────────────

    @property
    def mask_size(self) -> int:
        return 61

    @property
    def phase_count(self) -> int:
        return 1

    def compute_mask(self, metrics: HardwareMetrics, phase: int = 0,
                     temp_unit: str = "C", **kw: Any) -> List[bool]:
        mask = [False] * 61

        is_24h = kw.get('is_24h', True)
        week_sunday = kw.get('week_sunday', False)
        now = datetime.now()

        # Time colons + date separator — always on
        for idx in self.COLON_AND_SEP:
            mask[idx] = True

        hour = now.hour
        if not is_24h:
            hour = hour % 12
            if hour == 0:
                hour = 12

        # HH:MM (suppress hour tens leading zero in 12h mode)
        self._encode_clock_digit(hour // 10, self.DIGITS[0], mask,
                                 suppress_zero=(not is_24h))
        self._encode_clock_digit(hour % 10, self.DIGITS[1], mask)
        self._encode_clock_digit(now.minute // 10, self.DIGITS[2], mask)
        self._encode_clock_digit(now.minute % 10, self.DIGITS[3], mask)

        # Month tens: partial B/C only (can only show "1" or blank)
        m_tens = now.month // 10
        if m_tens == 1:
            mask[self.MONTH_TENS_BC[0]] = True  # B segment
            mask[self.MONTH_TENS_BC[1]] = True  # C segment

        # Month ones: full digit at DIGITS[4]
        self._encode_clock_digit(now.month % 10, self.DIGITS[4], mask)

        # Day: tens (full) + ones (full)
        self._encode_clock_digit(now.day // 10, self.DIGITS[5], mask,
                                 suppress_zero=True)
        self._encode_clock_digit(now.day % 10, self.DIGITS[6], mask)

        # Weekday progressive fill (C#: isOn[ZhuangShi1]=true always,
        # isOn[ZhuangShi2]=(w>0), isOn[ZhuangShi3]=(w>1), ... isOn[ZhuangShi7]=(w>5))
        # Python weekday: 0=Mon..6=Sun; C# DayOfWeek: 0=Sun..6=Sat
        py_wd = now.weekday()  # 0=Mon..6=Sun
        if week_sunday:
            # Sunday-start: Sun=0, Mon=1, ..., Sat=6
            w = (py_wd + 1) % 7
        else:
            # Monday-start: Mon=0, ..., Sun=6
            w = py_wd
        for i, idx in enumerate(self.DECORATION):
            mask[idx] = (i == 0) or (w > i - 1)

        return mask


# ═══════════════════════════════════════════════════════════════════════
# Style 10 — LF11 (38 LEDs, 4-phase sensor rotation)
# ═══════════════════════════════════════════════════════════════════════

class LF11Display(SegmentDisplay):
    """Style 10 — LF11: 38-LED, hard-disk sensor rotation.

    C# SetMyNumeralHardDisk: mode 0 = SSD temp (3-digit + C/F),
    mode 1 = BFB/fan (5-digit), mode 2 = MHz (5-digit).
    """

    # ── Layout data ────────────────────────────────────────────────
    SSD = 0       # °C/°F indicator
    BFB = 1       # % / fan indicator (shared with MTNo)
    MHZ_IND = 2   # MHz indicator (shared with GNo)

    DIGITS: Tuple[Tuple[int, ...], ...] = (
        (3, 4, 5, 6, 7, 8, 9),
        (10, 11, 12, 13, 14, 15, 16),
        (17, 18, 19, 20, 21, 22, 23),
        (24, 25, 26, 27, 28, 29, 30),
        (31, 32, 33, 34, 35, 36, 37),
    )

    # (metric_key, mode): mode 0=temp, 1=BFB/5-digit, 2=MHz/5-digit
    PHASES = (
        ('disk_temp', 0),
        ('disk_activity', 1),
        ('disk_read', 2),
    )

    # ── Interface ──────────────────────────────────────────────────

    @property
    def mask_size(self) -> int:
        return 38

    @property
    def phase_count(self) -> int:
        return 3

    def compute_mask(self, metrics: HardwareMetrics, phase: int = 0,
                     temp_unit: str = "C", **kw: Any) -> List[bool]:
        mask = [False] * 38

        metric_key, mode = self.PHASES[phase % 3]
        value = int(getattr(metrics, metric_key, 0))

        if mode == 0:
            # Temperature: SSD indicator, 3-digit + C/F unit on digits 4-5
            mask[self.SSD] = True
            value = self._to_display_temp(value, temp_unit)
            self._encode_3digit(value, self.DIGITS[0:3], mask)
            unit_mode = -1 if temp_unit == "F" else 0
            self._encode_unit(unit_mode, self.DIGITS[3], mask)
        elif mode == 1:
            # BFB/fan: 5-digit value across all positions
            mask[self.BFB] = True
            self._encode_5digit(value, self.DIGITS, mask)
        else:
            # MHz: 5-digit value across all positions
            mask[self.MHZ_IND] = True
            self._encode_5digit(value, self.DIGITS, mask)

        return mask


# ═══════════════════════════════════════════════════════════════════════
# Display registry — style_id → SegmentDisplay instance
# ═══════════════════════════════════════════════════════════════════════

DISPLAYS: Dict[int, SegmentDisplay] = {
    1: AX120Display(),
    2: PA120Display(),
    3: AK120Display(),
    4: LC1Display(),
    5: LF8Display(),
    6: LF12Display(),
    7: LF10Display(),
    8: CZ1Display(),
    9: LC2Display(),
    10: LF11Display(),
    11: LF8Display(),   # LF15 = same layout as LF8
    # 12: LF13 — pure RGB, no digit display
    # 13: HR10 — handled by device_led_hr10.py
}


# ═══════════════════════════════════════════════════════════════════════
# Module-level convenience API
# ═══════════════════════════════════════════════════════════════════════

def compute_mask(
    style_id: int,
    metrics: HardwareMetrics,
    phase: int = 0,
    temp_unit: str = "C",
    is_24h: bool = True,
    week_sunday: bool = False,
) -> List[bool]:
    """Compute LED on/off mask for any supported style.

    Args:
        style_id: LED device style (1-11).
        metrics: HardwareMetrics DTO with sensor readings.
        phase: Current rotation phase (0-based).
        temp_unit: "C" or "F".
        is_24h: 24-hour clock mode (style 9 only).
        week_sunday: Week starts on Sunday (style 9 only).

    Returns:
        Boolean mask in logical index space, or empty list if style
        has no digit display (12) or is handled elsewhere (13).
    """
    display = DISPLAYS.get(style_id)
    if display is None:
        return []
    return display.compute_mask(
        metrics, phase, temp_unit,
        is_24h=is_24h, week_sunday=week_sunday,
    )


def get_display(style_id: int) -> Optional[SegmentDisplay]:
    """Get the SegmentDisplay instance for a style, or None."""
    return DISPLAYS.get(style_id)


def has_segment_display(style_id: int) -> bool:
    """Whether this style has digit display support."""
    return style_id in DISPLAYS
