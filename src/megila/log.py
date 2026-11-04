"""JSON logs with secret masking.

Megila logs through structlog. A processor redacts values that were stored
or read as provider keys, and it redacts common credential patterns, before
the event is rendered as one JSON object per line.
"""

from __future__ import annotations

import logging
import re
import sys
import threading
from collections.abc import Callable, Mapping
from typing import Any, TextIO, cast

import structlog
from structlog.typing import EventDict, WrappedLogger

from megila.config.secret_names import is_secret_name

_REDACTED = "***"
_MIN_SUBSTRING = 8

# Assignment-shaped credentials: api_key=..., "token": "...", password: ...
_ASSIGN_NAME = (
    r"api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|id[_-]?token|"
    r"client[_-]?secret|secret[_-]?key|private[_-]?key|auth[_-]?token|"
    r"password|passwd|authorization|credential|credentials|bearer|token|secret"
)
_AUTH = re.compile(
    r"(?i)\b(authorization\s*[:=]\s*(?:bearer\s+)?)(\S+)",
)
_BEARER = re.compile(r"(?i)\b(bearer\s+)(\S+)")
_QUOTED_ASSIGN = re.compile(
    rf"""(?ix)
    (
        ["']?(?:{_ASSIGN_NAME})["']?
        \s*[:=]\s*
        ["']
    )
    ([^"']*)
    (["'])
    """
)
_BARE_ASSIGN = re.compile(
    rf"(?ix)\b({_ASSIGN_NAME})(\s*[:=]\s*)(\S+)",
)
_QUERY = re.compile(
    r"(?i)([?&](?:"
    r"api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|"
    r"id[_-]?token|token|secret|password|passwd|key"
    r")=)([^&#\s\"']+)"
)
_SK = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_GHP = re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")
_AWS = re.compile(r"\bAKIA[0-9A-Z]{16}\b")

_lock = threading.Lock()
_known: set[str] = set()
_configured = False
_original_factory: Callable[..., logging.LogRecord] | None = None


def clear_registered_secrets() -> None:
    """Forget registered secret values. Tests use this."""
    with _lock:
        _known.clear()


def register_secret(value: str) -> None:
    """Remember ``value`` so later log lines redact it.

    Empty strings and the redaction placeholder are ignored. A value stays
    registered after the key is deleted: a later log line must still hide it.
    """
    if value == "" or value == _REDACTED:
        return
    with _lock:
        _known.add(value)


def mask_text(text: str) -> str:
    """Return ``text`` with known secrets and credential patterns redacted."""
    if text == "":
        return text
    for secret in _snapshot():
        if len(secret) >= _MIN_SUBSTRING:
            if secret in text:
                text = text.replace(secret, _REDACTED)
        elif text == secret:
            return _REDACTED
    text = _AUTH.sub(rf"\1{_REDACTED}", text)
    text = _BEARER.sub(rf"\1{_REDACTED}", text)
    text = _QUOTED_ASSIGN.sub(rf"\1{_REDACTED}\3", text)
    text = _BARE_ASSIGN.sub(rf"\1\2{_REDACTED}", text)
    text = _QUERY.sub(rf"\1{_REDACTED}", text)
    text = _SK.sub(_REDACTED, text)
    text = _GHP.sub(_REDACTED, text)
    text = _AWS.sub(_REDACTED, text)
    return text


def mask_event(
    logger: WrappedLogger,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    """Structlog processor: redact secrets before JSON rendering."""
    del logger, method_name
    masked = _mask_object(event_dict)
    if isinstance(masked, dict):
        return masked
    return {"event": _REDACTED}


class _CurrentStream:
    """Write to whatever ``sys.stderr`` is at the moment of the write.

    A file object captured during one CLI invocation is closed when that
    invocation ends. Resolving stderr on each write keeps the next command
    able to log.
    """

    def write(self, data: str) -> int:
        return sys.stderr.write(data)

    def flush(self) -> None:
        sys.stderr.flush()


def configure_logging(stream: TextIO | None = None, *, force: bool = False) -> None:
    """Send Megila logs to ``stream`` as JSON, with secrets masked.

    The default stream is the process stderr, resolved on each line. Repeated
    calls keep the first configuration unless ``force`` is set.
    """
    global _configured
    if _configured and not force:
        return
    output = stream if stream is not None else cast(TextIO, _CurrentStream())
    structlog.reset_defaults()
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            mask_event,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        logger_factory=structlog.PrintLoggerFactory(file=output),
        cache_logger_on_first_use=False,
    )
    _install_record_factory()
    _configured = True


def reset_logging() -> None:
    """Drop the process logging configuration. Tests use this."""
    global _configured, _original_factory
    _configured = False
    structlog.reset_defaults()
    if _original_factory is not None:
        logging.setLogRecordFactory(_original_factory)
        _original_factory = None


def get_logger() -> structlog.stdlib.BoundLogger:
    """Return a logger that writes masked JSON once logging is configured."""
    configure_logging()
    return cast(structlog.stdlib.BoundLogger, structlog.get_logger())


def _snapshot() -> tuple[str, ...]:
    with _lock:
        values = tuple(_known)
    return tuple(sorted(values, key=len, reverse=True))


def _mask_object(value: object) -> object:
    if isinstance(value, str):
        return mask_text(value)
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, int | float):
        return value
    if isinstance(value, Mapping):
        return _mask_mapping(value)
    if isinstance(value, list | tuple):
        masked = [_mask_object(item) for item in value]
        if isinstance(value, tuple):
            return tuple(masked)
        return masked
    if isinstance(value, bytes | bytearray):
        return mask_text(repr(bytes(value)))
    return mask_text(str(value))


def _mask_mapping(value: Mapping[object, object]) -> dict[str, object]:
    rendered: dict[str, object] = {}
    for key, item in value.items():
        raw_name = str(key)
        name = mask_text(raw_name)
        if is_secret_name(raw_name):
            rendered[name] = _REDACTED
            continue
        rendered[name] = _mask_object(item)
    return rendered


def _install_record_factory() -> None:
    global _original_factory
    current = logging.getLogRecordFactory()
    if current is _masking_factory:
        return
    _original_factory = current
    logging.setLogRecordFactory(_masking_factory)


def _masking_factory(*args: Any, **kwargs: Any) -> logging.LogRecord:
    factory = _original_factory or logging.LogRecord
    record = factory(*args, **kwargs)
    try:
        rendered = record.getMessage()
    except Exception:
        rendered = str(record.msg)
    record.msg = mask_text(rendered)
    record.args = None
    exc_text = getattr(record, "exc_text", None)
    if isinstance(exc_text, str):
        record.exc_text = mask_text(exc_text)
    return record
