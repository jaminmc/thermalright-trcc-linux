"""LCD command handler — driving port boundary for all LCD operations.

LCDCommandHandler closes over an LCDDevice and dispatches every LCD command
via a single match statement. build_lcd_bus / build_lcd_gui_bus are the only
public entry points — callers never instantiate the handler directly.
"""
from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, ClassVar

from ..command_bus import (
    Command,
    CommandBus,
    CommandResult,
    LoggingMiddleware,
    TimingMiddleware,
)
from ..commands.lcd import (
    EnableOverlayCommand,
    EnsureDataCommand,
    ExportThemeCommand,
    ImportThemeCommand,
    InitializeDeviceCommand,
    LoadMaskCommand,
    LoadThemeByNameCommand,
    PauseVideoCommand,
    PlayVideoLoopCommand,
    RenderAndSendCommand,
    RenderOverlayFromDCCommand,
    ResetDisplayCommand,
    RestoreLastThemeCommand,
    SaveThemeCommand,
    SeekVideoCommand,
    SelectThemeCommand,
    SendColorCommand,
    SendFrameCommand,
    SendImageCommand,
    SetBrightnessCommand,
    SetFlashIndexCommand,
    SetMaskPositionCommand,
    SetOverlayConfigCommand,
    SetResolutionCommand,
    SetRotationCommand,
    SetSplitModeCommand,
    SetVideoFitModeCommand,
    StopVideoCommand,
    UpdateMetricsLCDCommand,
    UpdateVideoCacheTextCommand,
)
from .base import DeviceCommandHandler

if TYPE_CHECKING:
    from ..lcd_device import LCDDevice
    from ..ports import EnsureDataFn

log = logging.getLogger(__name__)


class LCDCommandHandler(DeviceCommandHandler):
    """Handles all LCD commands — one __call__, one match statement.

    Closes over lcd and ensure_fn. Both CLI and GUI buses use this handler;
    the GUI bus adds RateLimitMiddleware on top.
    """

    __slots__ = ('_lcd', '_ensure_fn')

    handles: ClassVar[tuple[type[Command], ...]] = (
        RestoreLastThemeCommand,
        SetBrightnessCommand,
        SetRotationCommand,
        SendColorCommand,
        SendImageCommand,
        LoadThemeByNameCommand,
        SelectThemeCommand,
        SaveThemeCommand,
        ExportThemeCommand,
        ImportThemeCommand,
        LoadMaskCommand,
        RenderOverlayFromDCCommand,
        SetOverlayConfigCommand,
        ResetDisplayCommand,
        InitializeDeviceCommand,
        SetResolutionCommand,
        PlayVideoLoopCommand,
        SetSplitModeCommand,
        EnableOverlayCommand,
        UpdateMetricsLCDCommand,
        EnsureDataCommand,
        StopVideoCommand,
        PauseVideoCommand,
        SeekVideoCommand,
        SetVideoFitModeCommand,
        UpdateVideoCacheTextCommand,
        SetFlashIndexCommand,
        SetMaskPositionCommand,
        SendFrameCommand,
        RenderAndSendCommand,
    )

    def __init__(self, lcd: LCDDevice, ensure_fn: EnsureDataFn | None = None) -> None:
        self._lcd = lcd
        self._ensure_fn = ensure_fn

    def __call__(self, cmd: Command) -> CommandResult:  # noqa: C901
        match cmd:
            case RestoreLastThemeCommand():
                return CommandResult.from_dict(self._lcd.restore_last_theme())

            case SetBrightnessCommand(level=level):
                return CommandResult.from_dict(self._lcd.set_brightness(level))

            case SetRotationCommand(degrees=degrees):
                return CommandResult.from_dict(self._lcd.set_rotation(degrees))

            case SendColorCommand(r=r, g=g, b=b):
                return CommandResult.from_dict(self._lcd.send_color(r, g, b))

            case SendImageCommand(image_path=image_path):
                return CommandResult.from_dict(self._lcd.send_image(image_path))

            case LoadThemeByNameCommand(name=name, width=width, height=height):
                return CommandResult.from_dict(
                    self._lcd.load_theme_by_name(name, width, height))

            case SelectThemeCommand(theme=theme):
                return CommandResult.from_dict(self._lcd.select(theme))

            case SaveThemeCommand(name=name, data_dir=data_dir):
                return CommandResult.from_dict(self._lcd.save(name, data_dir))

            case ExportThemeCommand(path=path):
                return CommandResult.from_dict(self._lcd.export_config(path))

            case ImportThemeCommand(path=path, data_dir=data_dir):
                return CommandResult.from_dict(self._lcd.import_config(path, data_dir))

            case LoadMaskCommand(mask_path=mask_path):
                return CommandResult.from_dict(
                    self._lcd.load_mask_standalone(mask_path))

            case RenderOverlayFromDCCommand(dc_path=dc_path, send=send, output=output,
                                             metrics=metrics):
                return CommandResult.from_dict(
                    self._lcd.render_overlay_from_dc(
                        dc_path, send=send, output=output or None,
                        metrics=metrics))

            case SetOverlayConfigCommand(config=config):
                return CommandResult.from_dict(self._lcd.set_config(config))

            case ResetDisplayCommand():
                return CommandResult.from_dict(self._lcd.reset())

            case InitializeDeviceCommand(width=width, height=height):
                log.debug("InitializeDeviceCommand: width=%d height=%d", width, height)
                import trcc.conf as _conf
                _conf.settings.set_resolution(width, height)
                self._lcd.initialize(_conf.settings.user_data_dir)
                self(EnsureDataCommand(width=width, height=height))
                return CommandResult.ok(
                    message=f"Device initialized at {width}x{height}")

            case SetResolutionCommand(width=width, height=height):
                log.debug("SetResolutionCommand: width=%d height=%d", width, height)
                result = self._lcd.set_resolution(width, height)
                if width and height:
                    self(EnsureDataCommand(width=width, height=height))
                return CommandResult.from_dict(result)

            case PlayVideoLoopCommand(video_path=video_path, loop=loop, duration=duration):
                return CommandResult.from_dict(
                    self._lcd.play_video_loop(video_path, loop=loop, duration=duration))

            case SetSplitModeCommand(mode=mode):
                return CommandResult.from_dict(self._lcd.set_split_mode(mode))

            case EnableOverlayCommand(on=on):
                return CommandResult.from_dict(self._lcd.enable_overlay(on))

            case UpdateMetricsLCDCommand(metrics=metrics):
                if not self._validate_metrics(metrics):
                    return CommandResult.fail(
                        "invalid metrics: expected non-None value")
                return CommandResult.from_dict(self._lcd.update_metrics(metrics))

            case EnsureDataCommand(width=width, height=height):
                log.debug("EnsureDataCommand: spawning background thread width=%d height=%d", width, height)
                ensure_fn = self._ensure_fn
                lcd = self._lcd

                def _bg() -> None:
                    import trcc.conf as _conf
                    if ensure_fn is not None:
                        ensure_fn(width, height)
                    _conf.settings.set_resolution(width, height)
                    lcd.notify_data_ready()

                threading.Thread(
                    target=_bg, daemon=True, name="data-extract").start()
                return CommandResult.ok(
                    message=f"Data download started for {width}x{height}")

            case StopVideoCommand():
                return CommandResult.from_dict(self._lcd.stop())

            case PauseVideoCommand():
                return CommandResult.from_dict(self._lcd.pause())

            case SeekVideoCommand(percent=percent):
                return CommandResult.from_dict(self._lcd.seek(percent))

            case SetVideoFitModeCommand(mode=mode):
                return CommandResult.from_dict(self._lcd.set_fit_mode(mode))

            case UpdateVideoCacheTextCommand(metrics=metrics):
                return CommandResult.from_dict(self._lcd.update_video_cache_text(metrics))

            case SetFlashIndexCommand(index=index):
                return CommandResult.from_dict(self._lcd.set_flash_index(index))

            case SetMaskPositionCommand(x=x, y=y):
                return CommandResult.from_dict(self._lcd.set_mask_position(x, y))

            case SendFrameCommand(image=image):
                if image is None:
                    return CommandResult.fail("SendFrameCommand: no image provided")
                self._lcd.send(image)
                return CommandResult.ok(message="Frame sent")

            case RenderAndSendCommand(skip_if_video=skip_if_video):
                return CommandResult.from_dict(
                    self._lcd.render_and_send(skip_if_video))

            case _:
                return CommandResult.fail(
                    f"BUG: unhandled LCD command {type(cmd).__name__}")

    def __repr__(self) -> str:
        return f"LCDCommandHandler(lcd={self._lcd!r})"


def build_lcd_bus(
    lcd: LCDDevice,
    ensure_fn: EnsureDataFn | None = None,
) -> CommandBus:
    """Build a CommandBus for CLI/API LCD operations.

    Logging + timing middleware. One handler instance shared across all
    registered command types — auto-registered from LCDCommandHandler.handles.
    """
    log.debug("build_lcd_bus: lcd=%r ensure_fn=%r", lcd, ensure_fn)
    h = LCDCommandHandler(lcd, ensure_fn)
    bus = (CommandBus()
           .add_middleware(LoggingMiddleware())
           .add_middleware(TimingMiddleware(threshold_ms=200.0)))
    for cmd_type in LCDCommandHandler.handles:
        bus.register(cmd_type, h)
    return bus


def build_lcd_gui_bus(
    lcd: LCDDevice,
    ensure_fn: EnsureDataFn | None = None,
) -> CommandBus:
    """Build a CommandBus for GUI LCD operations.

    Adds RateLimitMiddleware — GUI slider events fire continuously and must
    not saturate the USB bus.
    """
    log.debug("build_lcd_gui_bus: lcd=%r", lcd)
    return build_lcd_bus(lcd, ensure_fn)
