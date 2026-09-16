"""Logging with redaction of tokens and SAML payloads."""

from __future__ import annotations

import logging
import re

_PATTERNS = [
    re.compile(r"(SAMLResponse=)[^&\s\"']+"),
    re.compile(r"(SAMLRequest=)[^&\s\"']+"),
    re.compile(r"(RelayState=)[^&\s\"']+"),
    re.compile(r"([?&]t=)[^&\s\"']+"),
    re.compile(r"([?&]c=)[^&\s\"']+"),
    re.compile(r"([?&]code=)[^&\s\"']+"),
    re.compile(r"([?&]state=)[^&\s\"']+"),
]


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(r"\1[redacted]", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        return True


def setup_logging(level: str) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Access logs contain query strings; the reverse proxy keeps its own (filtered) access log.
    logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
    logging.getLogger("discord.http").setLevel(logging.WARNING)
