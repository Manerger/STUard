"""End-to-end browser flow against the real aiohttp app with fake IdP/Discord/Microsoft/verification."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

import aiohttp
import pytest
from aiohttp.test_utils import TestClient, TestServer

from stuard.config import AppConfig
from stuard.db.repos import Repo
from stuard.security.ratelimit import RateLimiter
from stuard.security.tokens import hash_token, new_token, subject_hmac
from stuard.services.verification import Outcome
from stuard.timeutil import now_ts
from stuard.web.microsoft import MicrosoftIdentity, MicrosoftValidationError
from stuard.web.saml_sp import SamlIdentity, SamlValidationError
from stuard.web.server import build_app
from tests.fakes import FakeAudit, make_settings, namespace

USER = 111_111
COOKIE = "stuard_flow"


class FakeSaml:
    def __init__(self) -> None:
        self.identity = SamlIdentity(
            subject="123456@stuba.sk",
            scoped_affiliations=["student@stuba.sk", "member@stuba.sk"],
            affiliations=[],
            assertion_id="_a1",
            not_on_or_after=None,
        )
        self.error: str | None = None
        self.relay: str | None = None
        self.request_id: str | None = None

    def login_url(self, relay_state: str) -> tuple[str, str]:
        self.relay = relay_state
        self.request_id = f"_req{new_token()}"
        return f"https://idp.test/sso?RelayState={relay_state}", self.request_id

    def validate(self, post_data: dict[str, str], request_id: str) -> SamlIdentity:
        assert request_id == self.request_id
        if self.error:
            raise SamlValidationError(self.error)
        return self.identity

    def metadata(self) -> str:
        return "<md:EntityDescriptor/>"


class FakeOAuth:
    def __init__(self) -> None:
        self.user_id = USER
        self.state: str | None = None

    def authorize_url(self, state: str) -> str:
        self.state = state
        return f"https://discord.test/oauth2/authorize?state={state}"

    async def fetch_user_id(self, code: str) -> int:
        return self.user_id


class FakeMicrosoft:
    def __init__(self) -> None:
        self.state: str | None = None
        self.nonce: str | None = None
        self.challenge: str | None = None
        self.redeemed: list[tuple[str, str]] = []
        self.error: str | None = None
        self.identity = MicrosoftIdentity("xnovak@stuba.sk", "123456@stuba.sk", "123456", "student")

    def authorize_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        self.state, self.nonce, self.challenge = state, nonce, code_challenge
        return f"https://login.microsoftonline.test/authorize?state={state}"

    async def complete_sign_in(self, code: str, code_verifier: str, nonce_hash: bytes) -> MicrosoftIdentity:
        self.redeemed.append((code, code_verifier))
        if self.error:
            raise MicrosoftValidationError(self.error)
        assert nonce_hash == hash_token(self.nonce or "")
        return self.identity


class FakeVerification:
    def __init__(self) -> None:
        self.enabled = True
        self.microsoft = True
        self.calls: list[tuple[int, bytes, frozenset[str]]] = []
        self.microsoft_calls: list[tuple[int, bytes, str, str | None]] = []

    def sso_enabled(self) -> bool:
        return self.enabled

    def microsoft_enabled(self) -> bool:
        return self.microsoft

    async def complete_sso(self, user_id: int, subject: bytes, affiliations: frozenset[str]) -> Outcome:
        self.calls.append((user_id, subject, affiliations))
        return Outcome("verified", "student")

    async def complete_microsoft(self, user_id: int, subject: bytes, login: str, employee_type: str | None) -> Outcome:
        self.microsoft_calls.append((user_id, subject, login, employee_type))
        return Outcome("verified", "student")


@pytest.fixture
async def env(repo: Repo, cfg: AppConfig) -> AsyncIterator[tuple[TestClient, Any]]:
    ctx = namespace(
        settings=make_settings(),
        cfg=cfg,
        repo=repo,
        saml=FakeSaml(),
        microsoft=FakeMicrosoft(),
        oauth=FakeOAuth(),
        verification=FakeVerification(),
        audit=FakeAudit(),
        web_limiter=RateLimiter(1000, 60),
        describe_user=lambda user_id: ("Test User (@test)", None),
    )
    client = TestClient(TestServer(build_app(ctx)), cookie_jar=aiohttp.DummyCookieJar())
    await client.start_server()
    yield client, ctx
    await client.close()


def cookie_header(value: str) -> dict[str, str]:
    return {"Cookie": f"{COOKIE}={value}"}


async def open_link(client: TestClient, repo: Repo) -> str:
    token = new_token()
    await repo.create_flow(USER, hash_token(token), now_ts(), 600)
    resp = await client.get(f"/v?t={token}", allow_redirects=False)
    assert resp.status == 302
    morsel = resp.cookies[COOKIE]
    assert morsel["httponly"] and morsel["secure"] and morsel["samesite"] == "Lax"
    return morsel.value


async def through_oauth(client: TestClient, ctx: Any, cookie: str) -> None:
    resp = await client.get(
        f"/oauth/discord/callback?code=abc&state={ctx.oauth.state}",
        headers=cookie_header(cookie),
        allow_redirects=False,
    )
    assert resp.status == 302, await resp.text()
    assert resp.headers["Location"].startswith("https://idp.test/sso")


async def post_acs(client: TestClient, ctx: Any) -> aiohttp.ClientResponse:
    return await client.post(
        "/saml/acs", data={"SAMLResponse": "PHNhbWw+", "RelayState": ctx.saml.relay}, allow_redirects=False
    )


# ---------------------------------------------------------------- STU login (SAML)


async def test_happy_path(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    cookie = await open_link(client, repo)
    await through_oauth(client, ctx, cookie)
    resp = await post_acs(client, ctx)
    assert resp.status == 303
    location = resp.headers["Location"]
    assert location.startswith("/verify/complete?c=")

    resp = await client.get(location, headers=cookie_header(cookie), allow_redirects=False)
    assert resp.status == 200
    assert "Overenie úspešné" in await resp.text()
    [(user_id, subject, affiliations)] = ctx.verification.calls
    assert user_id == USER and affiliations == {"student", "member"}
    assert subject == subject_hmac(ctx.settings.hmac_key, "123456@stuba.sk")
    assert resp.headers["Cache-Control"] == "no-store"
    assert "frame-ancestors 'none'" in resp.headers["Content-Security-Policy"]
    assert resp.headers["Referrer-Policy"] == "no-referrer"

    again = await client.get(location, headers=cookie_header(cookie), allow_redirects=False)
    assert again.status == 410
    assert len(ctx.verification.calls) == 1


async def test_link_is_single_use(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, _ = env
    token = new_token()
    await repo.create_flow(USER, hash_token(token), now_ts(), 600)
    assert (await client.get(f"/v?t={token}", allow_redirects=False)).status == 302
    assert (await client.get(f"/v?t={token}", allow_redirects=False)).status == 410


async def test_unknown_link(env: tuple[TestClient, Any]) -> None:
    client, _ = env
    assert (await client.get("/v?t=nope", allow_redirects=False)).status == 410
    assert (await client.get("/v", allow_redirects=False)).status == 400


async def test_forwarded_link_opened_by_other_discord_account(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    cookie = await open_link(client, repo)
    ctx.oauth.user_id = 999
    resp = await client.get(
        f"/oauth/discord/callback?code=abc&state={ctx.oauth.state}",
        headers=cookie_header(cookie),
        allow_redirects=False,
    )
    assert resp.status == 403
    assert "verify_oauth_mismatch" in ctx.audit.actions
    assert ctx.saml.relay is None  # never sent to the IdP


async def test_oauth_callback_needs_the_same_browser(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    await open_link(client, repo)
    resp = await client.get(
        f"/oauth/discord/callback?code=abc&state={ctx.oauth.state}",
        headers=cookie_header(new_token()),
        allow_redirects=False,
    )
    assert resp.status == 403


async def test_forwarded_idp_url_cannot_be_completed_by_anyone(env: tuple[TestClient, Any], repo: Repo) -> None:
    """Attacker starts a flow and sends the IdP URL to a victim who logs in with their STU account."""
    client, ctx = env
    attacker_cookie = await open_link(client, repo)
    await through_oauth(client, ctx, attacker_cookie)
    resp = await post_acs(client, ctx)  # victim's browser posts the assertion
    location = resp.headers["Location"]

    # Victim's browser follows the redirect but has no (matching) flow cookie.
    assert (await client.get(location, allow_redirects=False)).status == 403
    # The attacker has the cookie but never saw the completion code; the flow is dead anyway.
    assert (await client.get(location, headers=cookie_header(attacker_cookie), allow_redirects=False)).status == 410
    assert ctx.verification.calls == []
    assert "verify_browser_mismatch" in ctx.audit.actions


async def test_assertion_replay_rejected(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    for expected in (303, 403):
        cookie = await open_link(client, repo)
        await through_oauth(client, ctx, cookie)
        assert (await post_acs(client, ctx)).status == expected
    assert "verify_saml_replay" in ctx.audit.actions


async def test_invalid_saml_response(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    cookie = await open_link(client, repo)
    await through_oauth(client, ctx, cookie)
    ctx.saml.error = "invalid"
    assert (await post_acs(client, ctx)).status == 403
    assert "verify_saml_failed" in ctx.audit.actions


async def test_foreign_affiliation_scope_rejected(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    ctx.saml.identity = replace(ctx.saml.identity, scoped_affiliations=["student@evil.sk"])
    cookie = await open_link(client, repo)
    await through_oauth(client, ctx, cookie)
    assert (await post_acs(client, ctx)).status == 403


async def test_acs_with_unknown_relay_state(env: tuple[TestClient, Any]) -> None:
    client, _ = env
    resp = await client.post("/saml/acs", data={"SAMLResponse": "x", "RelayState": "unknown"}, allow_redirects=False)
    assert resp.status == 410


async def test_sso_disabled(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    ctx.verification.enabled = False
    token = new_token()
    await repo.create_flow(USER, hash_token(token), now_ts(), 600)
    assert (await client.get(f"/v?t={token}", allow_redirects=False)).status == 503


async def test_confirm_page_when_oauth_not_required(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    ctx.settings = make_settings(discord_oauth_required=False)
    token = new_token()
    await repo.create_flow(USER, hash_token(token), now_ts(), 600)
    resp = await client.get(f"/v?t={token}", allow_redirects=False)
    assert resp.status == 200
    assert "Test User (@test)" in await resp.text()
    cookie = resp.cookies[COOKIE].value
    resp = await client.post("/v/confirm", headers=cookie_header(cookie), allow_redirects=False)
    assert resp.status == 302 and resp.headers["Location"].startswith("https://idp.test/sso")


async def test_static_pages(env: tuple[TestClient, Any]) -> None:
    client, _ = env
    assert (await client.get("/healthz")).status == 200
    privacy = await client.get("/privacy")
    assert privacy.status == 200 and "Microsoft 365" in await privacy.text()
    assert (await client.get("/saml/metadata")).status == 200
    assert (await client.get("/static/style.css")).status == 200
    missing = await client.get("/nope")
    assert missing.status == 404 and missing.headers["X-Frame-Options"] == "DENY"


# ---------------------------------------------------------------- Microsoft 365


async def open_microsoft_link(client: TestClient, ctx: Any, repo: Repo) -> str:
    token = new_token()
    await repo.create_flow(USER, hash_token(token), now_ts(), 600)
    resp = await client.get(f"/v?t={token}&m=microsoft", allow_redirects=False)
    assert resp.status == 302
    cookie = resp.cookies[COOKIE].value
    resp = await client.get(
        f"/oauth/discord/callback?code=abc&state={ctx.oauth.state}",
        headers=cookie_header(cookie),
        allow_redirects=False,
    )
    assert resp.status == 302, await resp.text()
    assert resp.headers["Location"].startswith("https://login.microsoftonline.test/authorize")
    return cookie


async def test_microsoft_happy_path(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    cookie = await open_microsoft_link(client, ctx, repo)
    assert ctx.microsoft.challenge and ctx.saml.relay is None
    callback = f"/oauth/microsoft/callback?code=ms-code&state={ctx.microsoft.state}"
    resp = await client.get(callback, headers=cookie_header(cookie), allow_redirects=False)
    assert resp.status == 200, await resp.text()
    assert "Overenie úspešné" in await resp.text()
    [(code, verifier)] = ctx.microsoft.redeemed
    assert code == "ms-code" and len(verifier) >= 43
    [(user_id, subject, login, employee_type)] = ctx.verification.microsoft_calls
    assert user_id == USER and login == "xnovak@stuba.sk" and employee_type == "student"
    # Same identifier as STU's login would produce: the AIS ID, not the login name.
    assert subject == subject_hmac(ctx.settings.hmac_key, "123456@stuba.sk")

    again = await client.get(callback, headers=cookie_header(cookie), allow_redirects=False)
    assert again.status == 410
    assert len(ctx.microsoft.redeemed) == 1


async def test_microsoft_callback_needs_the_same_browser(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    await open_microsoft_link(client, ctx, repo)
    resp = await client.get(
        f"/oauth/microsoft/callback?code=ms-code&state={ctx.microsoft.state}", allow_redirects=False
    )
    assert resp.status == 403
    assert ctx.microsoft.redeemed == []
    assert "verify_browser_mismatch" in ctx.audit.actions


async def test_microsoft_admin_consent_required(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    cookie = await open_microsoft_link(client, ctx, repo)
    resp = await client.get(
        "/oauth/microsoft/callback",
        params={
            "state": ctx.microsoft.state,
            "error": "access_denied",
            "error_description": "AADSTS90094: Admin consent is required. Trace ID: x",
        },
        headers=cookie_header(cookie),
        allow_redirects=False,
    )
    assert resp.status == 403
    assert "schválenie správcu" in await resp.text()
    assert "verify_microsoft_error" in ctx.audit.actions
    assert ctx.microsoft.redeemed == []


async def test_microsoft_sign_in_failure(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    cookie = await open_microsoft_link(client, ctx, repo)
    ctx.microsoft.error = "profile_mismatch"
    resp = await client.get(
        f"/oauth/microsoft/callback?code=ms-code&state={ctx.microsoft.state}",
        headers=cookie_header(cookie),
        allow_redirects=False,
    )
    assert resp.status == 403
    assert ctx.verification.microsoft_calls == []
    assert "verify_microsoft_failed" in ctx.audit.actions


async def test_microsoft_state_is_not_accepted_by_the_saml_endpoint(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    await open_microsoft_link(client, ctx, repo)
    resp = await client.post(
        "/saml/acs", data={"SAMLResponse": "PHNhbWw+", "RelayState": ctx.microsoft.state}, allow_redirects=False
    )
    assert resp.status == 410


async def test_microsoft_disabled_and_unknown_method(env: tuple[TestClient, Any], repo: Repo) -> None:
    client, ctx = env
    ctx.verification.microsoft = False
    token = new_token()
    await repo.create_flow(USER, hash_token(token), now_ts(), 600)
    assert (await client.get(f"/v?t={token}&m=microsoft", allow_redirects=False)).status == 503
    assert (await client.get(f"/v?t={token}&m=password", allow_redirects=False)).status == 400
