"""Random tokens, token hashing and the keyed subject hash used for UIS identities."""

from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> bytes:
    """Tokens are stored only as SHA-256 hashes, so a database leak cannot be replayed."""
    return hashlib.sha256(token.encode("utf-8")).digest()


def normalize_subject(subject: str) -> str:
    return subject.strip().lower()


def subject_hmac(key: bytes, subject: str) -> bytes:
    """Keyed hash of a UIS identifier: detects duplicates without storing the login itself."""
    return hmac.new(key, normalize_subject(subject).encode("utf-8"), hashlib.sha256).digest()
