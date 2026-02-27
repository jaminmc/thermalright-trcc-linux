"""Pydantic request/response models for all API endpoints."""
from __future__ import annotations

from pydantic import BaseModel

# ── Device models ──────────────────────────────────────────────────────

class DeviceResponse(BaseModel):
    id: int
    name: str
    vid: int
    pid: int
    protocol: str
    resolution: tuple[int, int]
    path: str


class ThemeResponse(BaseModel):
    name: str
    category: str
    is_animated: bool
    has_config: bool
    preview_url: str = ""


class WebThemeResponse(BaseModel):
    id: str
    category: str
    preview_url: str
    has_video: bool = False


class MaskResponse(BaseModel):
    name: str
    preview_url: str


# ── Display request models ─────────────────────────────────────────────

class ColorRequest(BaseModel):
    hex: str


class BrightnessRequest(BaseModel):
    level: int


class RotationRequest(BaseModel):
    degrees: int


class SplitRequest(BaseModel):
    mode: int


# ── LED request models ─────────────────────────────────────────────────

class LEDColorRequest(BaseModel):
    hex: str


class LEDModeRequest(BaseModel):
    mode: str


class LEDBrightnessRequest(BaseModel):
    level: int


class LEDSensorRequest(BaseModel):
    source: str


class ZoneColorRequest(BaseModel):
    hex: str


class ZoneModeRequest(BaseModel):
    mode: str


class ZoneBrightnessRequest(BaseModel):
    level: int


class ZoneToggleRequest(BaseModel):
    on: bool


class ZoneSyncRequest(BaseModel):
    enabled: bool
    interval: int | None = None


class SegmentToggleRequest(BaseModel):
    on: bool


class ClockFormatRequest(BaseModel):
    is_24h: bool


class TempUnitRequest(BaseModel):
    unit: str


# ── Theme request models ───────────────────────────────────────────────

class ThemeLoadRequest(BaseModel):
    name: str
    resolution: str | None = None


class ThemeSaveRequest(BaseModel):
    name: str
