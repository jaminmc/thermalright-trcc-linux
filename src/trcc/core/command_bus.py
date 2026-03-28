"""Command pattern infrastructure — CommandBus, Middleware, Command ABCs.

All three interfaces (CLI, API, GUI) dispatch Command objects through a
CommandBus. Cross-cutting concerns (logging, timing, rate limiting) are
implemented as Middleware and applied once here instead of scattered
across three adapters.

Design rules:
- Commands are frozen dataclasses — value objects, no behaviour.
- Middleware chain is FIFO outer-to-inner (first added = outermost wrapper).
- Each composition root owns its own CommandBus instance — no global singleton.
- Handlers are callables registered via bus.register() — no reflection magic.
- Domain failures return CommandResult(success=False) — only unregistered
  commands raise (KeyError — a programming error, not a runtime failure).
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeAlias

log = logging.getLogger(__name__)


# ── Result ─────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class CommandResult:
    """Wraps the dict all device methods already return.

    success: mirrors result["success"]
    payload: the full original dict for adapter-specific fields
    """
    success: bool
    payload: dict[str, Any]

    def __bool__(self) -> bool:
        return self.success

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CommandResult:
        return cls(success=bool(d.get("success")), payload=d)

    @classmethod
    def ok(cls, **kwargs: Any) -> CommandResult:
        return cls(success=True, payload={"success": True, **kwargs})

    @classmethod
    def fail(cls, error: str, **kwargs: Any) -> CommandResult:
        return cls(success=False, payload={"success": False, "error": error, **kwargs})


# ── Command base hierarchy ──────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Command:
    """Base for all commands.

    Frozen dataclass: commands are value objects — parameters only, no behaviour.
    Subclass per operation, one field per parameter.
    """


@dataclass(frozen=True, slots=True)
class OSCommand(Command):
    """Marker base for OS/platform commands — platform init, device discovery, connect."""


@dataclass(frozen=True, slots=True)
class LCDCommand(Command):
    """Marker base for all LCD commands (ISP — adapters import only this family)."""


@dataclass(frozen=True, slots=True)
class LEDCommand(Command):
    """Marker base for all LED commands (ISP — adapters import only this family)."""


# ── Middleware ABC ──────────────────────────────────────────────────────────

HandlerFn: TypeAlias = Callable[[Command], CommandResult]


class Middleware(ABC):
    """Single link in the middleware chain.

    OCP: add a new cross-cutting concern by writing a new Middleware subclass
    and registering it on the bus — zero changes to existing code.
    """

    @abstractmethod
    def handle(self, command: Command, next_fn: HandlerFn) -> CommandResult:
        """Process command, then call next_fn(command) to continue the chain."""


# ── Built-in middleware ─────────────────────────────────────────────────────

class LoggingMiddleware(Middleware):
    """Log every command dispatch at DEBUG; log failures at WARNING."""

    def handle(self, command: Command, next_fn: HandlerFn) -> CommandResult:
        log.debug("dispatch %s", command.__class__.__name__)
        result = next_fn(command)
        if not result.success:
            log.warning(
                "command %s failed: %s",
                command.__class__.__name__,
                result.payload.get("error", "unknown"),
            )
        return result


class TimingMiddleware(Middleware):
    """Log a WARNING when a command takes longer than threshold_ms."""

    def __init__(self, threshold_ms: float = 500.0) -> None:
        self._threshold_ms = threshold_ms

    def handle(self, command: Command, next_fn: HandlerFn) -> CommandResult:
        t0 = time.perf_counter()
        result = next_fn(command)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if elapsed_ms > self._threshold_ms:
            log.warning(
                "slow command %s: %.1f ms",
                command.__class__.__name__,
                elapsed_ms,
            )
        return result


class RateLimitMiddleware(Middleware):
    """Skip commands arriving faster than min_interval_ms per command type.

    Intended for high-frequency GUI slider events (brightness, rotation)
    that must not saturate the USB bus. Skipped commands return a success
    result with skipped=True so callers need not special-case them.

    Only command types listed in ``only`` are throttled. All other command
    types pass through immediately — state-change commands (EnableOverlay,
    RenderAndSend, etc.) must never be silently dropped.
    """

    def __init__(
        self,
        min_interval_ms: float = 50.0,
        only: frozenset[type[Command]] | None = None,
    ) -> None:
        self._min_interval_ms = min_interval_ms
        self._only = only  # None = throttle all (legacy), frozenset = allowlist
        self._last: dict[type[Command], float] = {}

    def handle(self, command: Command, next_fn: HandlerFn) -> CommandResult:
        cmd_type = type(command)
        if self._only is not None and cmd_type not in self._only:
            return next_fn(command)
        now = time.perf_counter()
        if (now - self._last.get(cmd_type, 0.0)) * 1000 < self._min_interval_ms:
            return CommandResult.ok(skipped=True, message="rate limited")
        self._last[cmd_type] = now
        return next_fn(command)


# ── CommandBus ──────────────────────────────────────────────────────────────

class CommandBus:
    """Dispatch commands through a middleware chain to registered handlers.

    DIP: depends on Command/Middleware/HandlerFn abstractions only.
    OCP: new commands via register(), new concerns via add_middleware().
    SRP: dispatches only — handlers own business logic.

    Each composition root (CLI, API, GUI) creates its own instance so
    middleware profiles can differ per interface.

    Usage::

        bus = (CommandBus()
               .add_middleware(LoggingMiddleware())
               .add_middleware(TimingMiddleware()))
        bus.register(SetBrightnessCommand,
                     lambda cmd: CommandResult.from_dict(lcd.set_brightness(cmd.level)))
        result = bus.dispatch(SetBrightnessCommand(level=2))
    """

    def __init__(self) -> None:
        self._middleware: list[Middleware] = []
        self._handlers: dict[type[Command], HandlerFn] = {}

    def add_middleware(self, middleware: Middleware) -> CommandBus:
        """Append middleware. Returns self for fluent chaining."""
        self._middleware.append(middleware)
        return self

    def __or__(self, middleware: Middleware) -> CommandBus:
        """Append middleware via | operator: bus | RateLimitMiddleware(50.0)."""
        return self.add_middleware(middleware)

    def __ior__(self, middleware: Middleware) -> CommandBus:
        """Append middleware via |= operator: bus |= RateLimitMiddleware(50.0)."""
        return self.add_middleware(middleware)

    def register(self, command_type: type[Command], handler: HandlerFn) -> CommandBus:
        """Register a handler callable for a command type. Returns self."""
        self._handlers[command_type] = handler
        return self

    def has_middleware(self, cls: type) -> bool:
        """Return True if a middleware of the given type is registered."""
        return any(isinstance(m, cls) for m in self._middleware)

    def __contains__(self, cls: type) -> bool:
        """Support `TimingMiddleware in bus` syntax."""
        return self.has_middleware(cls)

    def dispatch(self, command: Command) -> CommandResult:
        """Run command through the full middleware chain then the handler.

        Raises:
            KeyError: command type has no registered handler (programming error).
        """
        handler = self._handlers.get(type(command))
        if handler is None:
            raise KeyError(
                f"No handler registered for {type(command).__name__}. "
                "Call bus.register() before dispatching."
            )

        # Build chain tail-to-head: handler is the innermost callable.
        # make_next captures loop variables explicitly to avoid Python's
        # late-binding trap.
        chain: HandlerFn = handler
        for mw in reversed(self._middleware):
            def _make_next(m: Middleware, nxt: HandlerFn) -> HandlerFn:
                def _next(cmd: Command) -> CommandResult:
                    return m.handle(cmd, nxt)
                return _next
            chain = _make_next(mw, chain)

        return chain(command)
