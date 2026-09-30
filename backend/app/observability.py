"""Lightweight timing instrumentation and secret-safe logging."""

import logging
import time
from collections.abc import Awaitable, Iterator
from contextlib import contextmanager
from typing import TypeVar

from app.config import get_settings
from app.redaction import redact, redact_values

T = TypeVar("T")


class StageTimer:
    """Collects wall-clock durations (ms) of named stages of one request."""

    def __init__(self) -> None:
        self._start = time.perf_counter()
        self.ms: dict[str, float] = {}

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        t = time.perf_counter()
        try:
            yield
        finally:
            self.ms[name] = round((time.perf_counter() - t) * 1000, 1)

    async def run(self, name: str, awaitable: Awaitable[T]) -> T:
        """Await and time one stage; usable inside asyncio.gather."""
        with self.stage(name):
            return await awaitable

    def total_ms(self) -> float:
        return round((time.perf_counter() - self._start) * 1000, 1)


class SecretRedactingFilter(logging.Filter):
    """Defense in depth: scrub configured secrets and secret-looking strings from every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        clean = redact_values(redact(message), get_settings().secret_values())
        if clean != message:
            record.msg, record.args = clean, None
        return True


def configure_logging() -> None:
    root = logging.getLogger()
    if not any(isinstance(f, SecretRedactingFilter) for h in root.handlers for f in h.filters):
        logging.basicConfig(
            level=get_settings().log_level.upper(),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        for handler in root.handlers:
            handler.addFilter(SecretRedactingFilter())
