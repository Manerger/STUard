"""Microsoft 365 sign-in: ID token validation, authorize URL, PKCE, code exchange and the Graph profile."""

from __future__ import annotations

import base64
import hashlib
import time
from typing import Any
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from cryptography.hazmat.primitives.asymmetric import rsa

from stuard.security.tokens import hash_token
from stuard.web.microsoft import (
    MicrosoftIdentity,
    MicrosoftSignIn,
    MicrosoftValidationError,
    aadsts_code,
    pkce_pair,
)

TENANT = "25733538-6b16-4aa3-8ed6-297eb79b8e06"
OTHER_TENANT = "99999999-9999-9999-9999-999999999999"
CLIENT_ID = "11111111-2222-3333-4444-555555555555"
ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"
OBJECT_ID = "00000000-0000-0000-0000-00000000abcd"
NONCE = "nonce-123"
NOW = int(time.time())


class StaticKeys:
    def __init__(self, public_key: Any) -> None:
        self.key = public_key

    def get_signing_key_from_jwt(self, token: str) -> StaticKeys:
        return self


@pytest.fixture(scope="module")
def key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_sign_in(key: rsa.RSAPrivateKey, **kwargs: Any) -> MicrosoftSignIn:
    return MicrosoftSignIn(
        client_id=CLIENT_ID,
        client_secret="secret",
        redirect_uri="https://verify.test/oauth/microsoft/callback",
        tenant_id=TENANT,
        allowed_domains=["stuba.sk"],
        signing_keys=StaticKeys(key.public_key()),
        **kwargs,
    )


def claims(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "iss": ISSUER,
        "aud": CLIENT_ID,
        "tid": TENANT,
        "iat": NOW,
        "nbf": NOW,
        "exp": NOW + 3600,
        "nonce": NONCE,
        "sub": "pairwise-subject",
        "oid": OBJECT_ID,
        "preferred_username": "XNovak@stuba.sk",
    }
    data.update(overrides)
    return {k: v for k, v in data.items() if v is not None}


def token(signing_key: rsa.RSAPrivateKey, **overrides: Any) -> str:
    return jwt.encode(claims(**overrides), signing_key, algorithm="RS256", headers={"kid": "test"})


# ---------------------------------------------------------------- ID token


def test_valid_token(key: rsa.RSAPrivateKey) -> None:
    account = make_sign_in(key).validate_id_token(token(key), hash_token(NONCE))
    assert account.login == "xnovak@stuba.sk"
    assert account.object_id == OBJECT_ID


def test_home_tenant_idp_claim_is_accepted(key: rsa.RSAPrivateKey) -> None:
    signed = token(key, idp=f"https://sts.windows.net/{TENANT}/")
    assert make_sign_in(key).validate_id_token(signed, hash_token(NONCE)).login == "xnovak@stuba.sk"


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"tid": OTHER_TENANT, "iss": f"https://login.microsoftonline.com/{OTHER_TENANT}/v2.0"}, "invalid_token"),
        ({"tid": OTHER_TENANT}, "tenant"),
        ({"aud": "another-app"}, "invalid_token"),
        ({"exp": NOW - 3600, "iat": NOW - 7200, "nbf": NOW - 7200}, "invalid_token"),
        ({"nonce": "replayed-from-another-flow"}, "nonce"),
        ({"nonce": None}, "invalid_token"),
        ({"idp": "live.com"}, "guest_account"),
        ({"preferred_username": "someone@gmail.com"}, "domain"),
        ({"preferred_username": "xnovak@notstuba.sk"}, "domain"),
        ({"preferred_username": None}, "domain"),
        ({"oid": None}, "no_object_id"),
    ],
    ids=[
        "other-tenant-issuer",
        "other-tenant-claim",
        "audience",
        "expired",
        "nonce",
        "missing-nonce",
        "guest",
        "gmail",
        "lookalike-domain",
        "no-username",
        "no-oid",
    ],
)
def test_invalid_tokens_rejected(key: rsa.RSAPrivateKey, overrides: dict[str, Any], code: str) -> None:
    with pytest.raises(MicrosoftValidationError) as info:
        make_sign_in(key).validate_id_token(token(key, **overrides), hash_token(NONCE))
    assert info.value.code == code


def test_token_signed_by_another_key_rejected(key: rsa.RSAPrivateKey) -> None:
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(MicrosoftValidationError) as info:
        make_sign_in(key).validate_id_token(token(other), hash_token(NONCE))
    assert info.value.code == "invalid_token"


def test_unsigned_token_rejected(key: rsa.RSAPrivateKey) -> None:
    unsigned = jwt.encode(claims(), None, algorithm="none")
    with pytest.raises(MicrosoftValidationError):
        make_sign_in(key).validate_id_token(unsigned, hash_token(NONCE))


# ---------------------------------------------------------------- authorize URL and PKCE


def test_authorize_url(key: rsa.RSAPrivateKey) -> None:
    url = make_sign_in(key).authorize_url(state="s", nonce="n", code_challenge="c")
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == (
        f"https://login.microsoftonline.com/{TENANT}/oauth2/v2.0/authorize"
    )
    assert query["response_type"] == ["code"]
    assert query["scope"] == ["openid profile User.Read"]
    assert query["code_challenge_method"] == ["S256"]
    assert query["domain_hint"] == ["stuba.sk"]
    assert query["redirect_uri"] == ["https://verify.test/oauth/microsoft/callback"]


def test_pkce_pair() -> None:
    verifier, challenge = pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected


def test_aadsts_code() -> None:
    assert aadsts_code("AADSTS90094: Admin consent is required. Trace ID: abc") == "AADSTS90094"
    assert aadsts_code(None) is None


# ---------------------------------------------------------------- full sign-in against fake Microsoft endpoints

PROFILE = {
    "id": OBJECT_ID,
    "userPrincipalName": "xnovak@stuba.sk",
    "employeeId": "123456",
    "employeeType": "student",
}


def fake_microsoft(
    token_response: dict[str, Any], profile: dict[str, Any] | None, seen: dict[str, Any]
) -> web.Application:
    async def token_endpoint(request: web.Request) -> web.Response:
        form = await request.post()
        seen["form"] = {k: str(v) for k, v in form.items()}
        if form["code"] != "good":
            return web.json_response(
                {"error": "invalid_grant", "error_description": "AADSTS70008: expired"}, status=400
            )
        return web.json_response(token_response)

    async def me(request: web.Request) -> web.Response:
        seen["authorization"] = request.headers.get("Authorization")
        seen["select"] = request.query.get("$select")
        if profile is None:
            return web.json_response({"error": {"code": "Authorization_RequestDenied"}}, status=403)
        return web.json_response(profile)

    app = web.Application()
    app.router.add_post(f"/{TENANT}/oauth2/v2.0/token", token_endpoint)
    app.router.add_get("/v1.0/me", me)
    return app


async def sign_in(
    key: rsa.RSAPrivateKey,
    *,
    profile: dict[str, Any] | None = PROFILE,
    token_response: dict[str, Any] | None = None,
    code: str = "good",
) -> tuple[MicrosoftIdentity, dict[str, Any]]:
    seen: dict[str, Any] = {}
    response = token_response if token_response is not None else {"id_token": token(key), "access_token": "graph-token"}
    async with TestServer(fake_microsoft(response, profile, seen)) as server:
        base = str(server.make_url("")).rstrip("/")
        identity = await make_sign_in(key, authority=base, graph=base).complete_sign_in(
            code, "the-verifier", hash_token(NONCE)
        )
    return identity, seen


async def test_sign_in_uses_the_ais_id_as_identifier(key: rsa.RSAPrivateKey) -> None:
    identity, seen = await sign_in(key)
    assert identity == MicrosoftIdentity("xnovak@stuba.sk", "123456@stuba.sk", "123456", "student")
    assert seen["form"]["code_verifier"] == "the-verifier"
    assert seen["form"]["client_secret"] == "secret"
    assert "User.Read" in seen["form"]["scope"]
    assert seen["authorization"] == "Bearer graph-token"
    assert set(seen["select"].split(",")) == {"id", "userPrincipalName", "employeeId", "employeeType"}


async def test_sign_in_without_ais_id_falls_back_to_the_login(key: rsa.RSAPrivateKey) -> None:
    identity, _ = await sign_in(key, profile={"id": OBJECT_ID, "employeeType": "employee"})
    assert identity == MicrosoftIdentity("xnovak@stuba.sk", "xnovak@stuba.sk", None, "employee")


async def test_non_numeric_employee_id_is_ignored(key: rsa.RSAPrivateKey) -> None:
    identity, _ = await sign_in(key, profile={**PROFILE, "employeeId": "E-12"})
    assert identity.employee_id is None and identity.subject == "xnovak@stuba.sk"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"profile": {**PROFILE, "id": "someone-else"}}, "profile_mismatch"),
        ({"profile": None}, "profile"),
        ({"token_response": {"id_token": "unused"}}, "no_access_token"),
        ({"token_response": {"access_token": "graph-token"}}, "no_id_token"),
        ({"code": "bad"}, "token_exchange"),
    ],
    ids=["profile-of-another-user", "profile-denied", "no-access-token", "no-id-token", "code-rejected"],
)
async def test_sign_in_failures(key: rsa.RSAPrivateKey, kwargs: dict[str, Any], code: str) -> None:
    with pytest.raises(MicrosoftValidationError) as info:
        await sign_in(key, **kwargs)
    assert info.value.code == code
