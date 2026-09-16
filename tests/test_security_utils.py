from __future__ import annotations

from stuard.logsetup import redact
from stuard.security.ratelimit import RateLimiter
from stuard.security.tokens import hash_token, new_token, subject_hmac


def test_tokens_are_random_and_long() -> None:
    tokens = {new_token() for _ in range(100)}
    assert len(tokens) == 100
    assert all(len(t) >= 43 for t in tokens)


def test_hash_token() -> None:
    assert hash_token("abc") == hash_token("abc")
    assert len(hash_token("abc")) == 32


def test_subject_hmac_normalizes_and_depends_on_key() -> None:
    key = b"k" * 32
    assert subject_hmac(key, " XNovak@STUBA.sk ") == subject_hmac(key, "xnovak@stuba.sk")
    assert subject_hmac(key, "xnovak@stuba.sk") != subject_hmac(b"j" * 32, "xnovak@stuba.sk")


def test_rate_limiter() -> None:
    now = [1000.0]
    limiter = RateLimiter(3, 10, clock=lambda: now[0])
    assert [limiter.hit("u") for _ in range(4)] == [True, True, True, False]
    assert limiter.hit("other")
    assert limiter.retry_after("u") > 0
    now[0] += 10.1
    assert limiter.hit("u")
    limiter.prune()


def test_redact() -> None:
    assert redact("GET /v?t=secret123&x=1") == "GET /v?t=[redacted]&x=1"
    assert redact("GET /verify/complete?c=abc") == "GET /verify/complete?c=[redacted]"
    assert "PHNhbWw" not in redact("body SAMLResponse=PHNhbWw&RelayState=xyz")
