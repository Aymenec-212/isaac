"""Structured logging (tech spec 15, 26).

Logs carry correlation ids and never transcript text, audio, tokens, or emails.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from contextvars import ContextVar
from typing import Any

import structlog

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
meeting_id_var: ContextVar[str | None] = ContextVar("meeting_id", default=None)


def _add_correlation_ids(
    _logger: Any, _name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    if (rid := request_id_var.get()) is not None:
        event_dict.setdefault("request_id", rid)
    if (mid := meeting_id_var.get()) is not None:
        event_dict.setdefault("meeting_id", mid)
    return event_dict


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
    renderer = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_correlation_ids,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelNamesMapping()[level]),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
