"""Browser side of verification.

Every flow starts with /v?t=…&m=saml|microsoft (link from /verify) → Discord OAuth (same Discord user) → login:
- STU (SAML): idp.stuba.sk → POST /saml/acs → 303 /verify/complete?c=
  (needs BOTH the completion code from the ACS redirect AND the flow cookie; the ACS POST is cross-site).
- Microsoft 365 (OpenID Connect): login.microsoftonline.com → GET /oauth/microsoft/callback
  (a top-level GET, so the SameSite=Lax flow cookie is checked right there).
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from typing import Any

from aiohttp import web

from stuard import texts as T
from stuard.db.repos import FlowRow
from stuard.domain.mapping import ScopeError, normalize_affiliations
from stuard.security.tokens import hash_token, new_token, subject_hmac
from stuard.services.verification import FLOW_TTL_SECONDS, Outcome
from stuard.timeutil import now_ts
from stuard.web.context import CTX_KEY
from stuard.web.discord_oauth import OAuthError
from stuard.web.microsoft import ADMIN_CONSENT_CODES, MicrosoftValidationError, aadsts_code, pkce_pair
from stuard.web.render import message_page, render
from stuard.web.render import stylesheet as stylesheet_text
from stuard.web.saml_sp import SamlValidationError

log = logging.getLogger(__name__)

FLOW_COOKIE = "stuard_flow"
MAX_TOKEN_LENGTH = 128
MAX_CODE_LENGTH = 4096
METHODS = ("saml", "microsoft")


def _ctx(request: web.Request) -> Any:
    return request.app[CTX_KEY]


def _client_ip(request: web.Request) -> str:
    if _ctx(request).settings.trust_forwarded_for:
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return request.remote or "unknown"


def _rate_limited(request: web.Request, bucket: str) -> bool:
    return not _ctx(request).web_limiter.hit(f"{bucket}:{_client_ip(request)}")


def _redirect(location: str, status: int = 302) -> web.Response:
    return web.Response(status=status, headers={"Location": location})


def _cookie_matches(flow_hash: bytes | None, cookie: str) -> bool:
    return bool(cookie) and flow_hash is not None and hmac.compare_digest(flow_hash, hash_token(cookie))


def _method_enabled(ctx: Any, method: str) -> bool:
    return ctx.verification.microsoft_enabled() if method == "microsoft" else ctx.verification.sso_enabled()


def _method_disabled_page(method: str) -> web.Response:
    return message_page("microsoft_disabled" if method == "microsoft" else "sso_disabled", 503)


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def privacy(request: web.Request) -> web.Response:
    return render("privacy.html", title=T.PRIVACY_TITLE, notice=T.privacy_notice(_ctx(request).cfg))


async def stylesheet(request: web.Request) -> web.Response:
    return web.Response(text=stylesheet_text(), content_type="text/css", charset="utf-8")


async def open_link(request: web.Request) -> web.Response:
    ctx = _ctx(request)
    if _rate_limited(request, "v"):
        return message_page("rate_limited", 429)
    token = request.query.get("t", "")
    method = request.query.get("m", "saml")
    if not token or len(token) > MAX_TOKEN_LENGTH or method not in METHODS:
        return message_page("link_invalid", 400)
    if not _method_enabled(ctx, method):
        return _method_disabled_page(method)

    now = now_ts()
    browser_token = new_token()
    flow = await ctx.repo.open_flow(hash_token(token), hash_token(browser_token), now, FLOW_TTL_SECONDS, method)
    if flow is None:
        return message_page("link_expired", 410)

    if ctx.settings.discord_oauth_required:
        state = new_token()
        if not await ctx.repo.transition_flow(flow.id, "opened", "opened", now, oauth_state_hash=hash_token(state)):
            return message_page("link_expired", 410)
        response = _redirect(ctx.oauth.authorize_url(state))
    else:
        name, avatar = ctx.describe_user(flow.user_id)
        response = render(
            "confirm.html",
            title=T.CONFIRM_TITLE,
            text=T.CONFIRM_TEXT,
            name=name,
            avatar=avatar,
            warning=T.CONFIRM_WARNING,
            button=T.CONFIRM_BUTTON,
        )
    response.set_cookie(
        FLOW_COOKIE,
        browser_token,
        max_age=FLOW_TTL_SECONDS,
        httponly=True,
        secure=ctx.settings.secure_cookies,
        samesite="Lax",
        path="/",
    )
    return response


async def confirm(request: web.Request) -> web.Response:
    """Weaker alternative to Discord OAuth (DISCORD_OAUTH_REQUIRED=false): the user confirms their username."""
    ctx = _ctx(request)
    if ctx.settings.discord_oauth_required:
        raise web.HTTPNotFound()
    cookie = request.cookies.get(FLOW_COOKIE, "")
    flow = await ctx.repo.get_flow_by("browser_token_hash", hash_token(cookie)) if cookie else None
    if flow is None or flow.status != "opened":
        return message_page("session_missing", 400)
    if not await ctx.repo.transition_flow(flow.id, "opened", "oauth_ok", now_ts()):
        return message_page("link_expired", 410)
    return await _start_login(ctx, flow)


async def oauth_callback(request: web.Request) -> web.Response:
    ctx = _ctx(request)
    if _rate_limited(request, "oauth"):
        return message_page("rate_limited", 429)
    if request.query.get("error"):
        return message_page("oauth_denied", 400)
    state = request.query.get("state", "")
    code = request.query.get("code", "")
    cookie = request.cookies.get(FLOW_COOKIE, "")
    if not (state and code and cookie) or len(state) > MAX_TOKEN_LENGTH or len(code) > 256:
        return message_page("session_missing", 400)

    now = now_ts()
    flow = await ctx.repo.get_flow_by("oauth_state_hash", hash_token(state))
    if flow is None or flow.status != "opened" or flow.expires_at <= now:
        return message_page("link_expired", 410)
    if not _cookie_matches(flow.browser_token_hash, cookie):
        return message_page("session_mismatch", 403)
    try:
        discord_user_id = await ctx.oauth.fetch_user_id(code)
    except OAuthError as exc:
        log.warning("Discord OAuth failed: %s", exc)
        await ctx.repo.fail_flow(flow.id, "oauth_error")
        return message_page("oauth_failed", 502)
    if discord_user_id != flow.user_id:
        # A verification link was forwarded to (or opened by) a different Discord account.
        await ctx.repo.fail_flow(flow.id, "oauth_user_mismatch")
        await ctx.audit.log(
            "verify_oauth_mismatch", target_id=flow.user_id, detail={"browser_discord_user": f"<@{discord_user_id}>"}
        )
        return message_page("oauth_mismatch", 403)
    if not await ctx.repo.transition_flow(flow.id, "opened", "oauth_ok", now_ts()):
        return message_page("link_expired", 410)
    return await _start_login(ctx, flow)


async def _start_login(ctx: Any, flow: FlowRow) -> web.Response:
    if not _method_enabled(ctx, flow.method):
        return _method_disabled_page(flow.method)
    now = now_ts()
    if flow.method == "microsoft":
        state, nonce = new_token(), new_token()
        verifier, challenge = pkce_pair()
        if not await ctx.repo.transition_flow(
            flow.id,
            "oauth_ok",
            "idp_sent",
            now,
            relay_state=state,
            nonce_hash=hash_token(nonce),
            pkce_verifier=verifier,
        ):
            return message_page("link_expired", 410)
        return _redirect(ctx.microsoft.authorize_url(state=state, nonce=nonce, code_challenge=challenge))

    relay_state = new_token()
    url, request_id = ctx.saml.login_url(relay_state)
    if not await ctx.repo.transition_flow(
        flow.id, "oauth_ok", "idp_sent", now, relay_state=relay_state, saml_request_id=request_id
    ):
        return message_page("link_expired", 410)
    return _redirect(url)


async def saml_metadata(request: web.Request) -> web.Response:
    ctx = _ctx(request)
    if ctx.saml is None:
        raise web.HTTPNotFound()
    return web.Response(text=ctx.saml.metadata(), content_type="application/samlmetadata+xml", charset="utf-8")


async def acs(request: web.Request) -> web.Response:
    """Assertion Consumer Service. Cross-site POST from the IdP, so the SameSite=Lax cookie is not sent here."""
    ctx = _ctx(request)
    if _rate_limited(request, "acs"):
        return message_page("rate_limited", 429)
    if ctx.saml is None:
        return message_page("sso_disabled", 503)
    form = await request.post()
    saml_response = form.get("SAMLResponse")
    relay_state = form.get("RelayState")
    if not isinstance(saml_response, str) or not isinstance(relay_state, str) or len(relay_state) > MAX_TOKEN_LENGTH:
        return message_page("saml_invalid", 400)

    now = now_ts()
    flow = await ctx.repo.get_flow_by("relay_state", relay_state)
    if (
        flow is None
        or flow.method != "saml"
        or flow.status != "idp_sent"
        or flow.expires_at <= now
        or not flow.saml_request_id
    ):
        return message_page("link_expired", 410)

    try:
        identity = await asyncio.to_thread(
            ctx.saml.validate, {"SAMLResponse": saml_response, "RelayState": relay_state}, flow.saml_request_id
        )
    except SamlValidationError as exc:
        await ctx.repo.fail_flow(flow.id, f"saml_{exc.code}")
        await ctx.audit.log("verify_saml_failed", target_id=flow.user_id, detail={"code": exc.code})
        return message_page("saml_invalid", 403)

    if not await ctx.repo.record_assertion(identity.assertion_id, max(identity.not_on_or_after or 0, now) + 600):
        await ctx.repo.fail_flow(flow.id, "saml_replay")
        await ctx.audit.log("verify_saml_replay", target_id=flow.user_id)
        return message_page("saml_invalid", 403)
    try:
        affiliations = normalize_affiliations(
            identity.scoped_affiliations, identity.affiliations, ctx.cfg.sso.allowed_scopes
        )
    except ScopeError:
        await ctx.repo.fail_flow(flow.id, "saml_scope")
        await ctx.audit.log("verify_saml_failed", target_id=flow.user_id, detail={"code": "affiliation_scope"})
        return message_page("scope_invalid", 403)

    completion_code = new_token()
    result = json.dumps(
        {"subject": subject_hmac(ctx.settings.hmac_key, identity.subject).hex(), "affiliations": sorted(affiliations)}
    )
    if not await ctx.repo.transition_flow(
        flow.id, "idp_sent", "idp_ok", now_ts(), result=result, complete_token_hash=hash_token(completion_code)
    ):
        return message_page("link_expired", 410)
    return _redirect(f"/verify/complete?c={completion_code}", status=303)


async def complete(request: web.Request) -> web.Response:
    ctx = _ctx(request)
    code = request.query.get("c", "")
    cookie = request.cookies.get(FLOW_COOKIE, "")
    if not code or len(code) > MAX_TOKEN_LENGTH:
        return message_page("link_invalid", 400)
    now = now_ts()
    flow = await ctx.repo.get_flow_by("complete_token_hash", hash_token(code))
    if flow is None or flow.method != "saml" or flow.status != "idp_ok" or flow.expires_at <= now or not flow.result:
        return message_page("link_expired", 410)
    if not _cookie_matches(flow.browser_token_hash, cookie):
        # The STU login finished in a browser that did not start this verification (forwarded IdP URL).
        await ctx.repo.fail_flow(flow.id, "browser_mismatch")
        await ctx.audit.log("verify_browser_mismatch", target_id=flow.user_id)
        return message_page("session_mismatch", 403)
    if not await ctx.repo.transition_flow(flow.id, "idp_ok", "completed", now):
        return message_page("link_expired", 410)

    data = json.loads(flow.result)
    outcome = await ctx.verification.complete_sso(
        flow.user_id, bytes.fromhex(data["subject"]), frozenset(data["affiliations"])
    )
    response = outcome_page(outcome)
    response.del_cookie(FLOW_COOKIE, path="/")
    return response


async def microsoft_callback(request: web.Request) -> web.Response:
    ctx = _ctx(request)
    if _rate_limited(request, "microsoft"):
        return message_page("rate_limited", 429)
    state = request.query.get("state", "")
    if not state or len(state) > MAX_TOKEN_LENGTH:
        return message_page("session_missing", 400)
    now = now_ts()
    flow = await ctx.repo.get_flow_by("relay_state", state)
    if (
        flow is None
        or flow.method != "microsoft"
        or flow.status != "idp_sent"
        or flow.expires_at <= now
        or not flow.pkce_verifier
        or not flow.nonce_hash
    ):
        return message_page("link_expired", 410)
    if not _cookie_matches(flow.browser_token_hash, request.cookies.get(FLOW_COOKIE, "")):
        # The Microsoft login finished in a browser that did not start this verification.
        await ctx.repo.fail_flow(flow.id, "browser_mismatch")
        await ctx.audit.log("verify_browser_mismatch", target_id=flow.user_id)
        return message_page("session_mismatch", 403)

    error = request.query.get("error")
    if error:
        error_code = aadsts_code(request.query.get("error_description"))
        await ctx.repo.fail_flow(flow.id, "microsoft_error")
        await ctx.audit.log(
            "verify_microsoft_error", target_id=flow.user_id, detail={"error": error[:64], "code": error_code}
        )
        if error_code in ADMIN_CONSENT_CODES or error == "consent_required":
            return message_page("microsoft_consent", 403)
        if error == "access_denied":
            return message_page("oauth_denied", 400)
        return message_page("microsoft_failed", 502)

    code = request.query.get("code", "")
    if not code or len(code) > MAX_CODE_LENGTH:
        return message_page("session_missing", 400)
    if ctx.microsoft is None or not ctx.verification.microsoft_enabled():
        return message_page("microsoft_disabled", 503)
    # Claim the flow before redeeming the code, so one Microsoft login can complete at most one flow.
    if not await ctx.repo.transition_flow(flow.id, "idp_sent", "idp_ok", now, pkce_verifier=None):
        return message_page("link_expired", 410)
    try:
        identity = await ctx.microsoft.complete_sign_in(code, flow.pkce_verifier, flow.nonce_hash)
    except MicrosoftValidationError as exc:
        await ctx.repo.fail_flow(flow.id, f"microsoft_{exc.code}")
        await ctx.audit.log("verify_microsoft_failed", target_id=flow.user_id, detail={"code": exc.code})
        return message_page("microsoft_failed", 403)
    if not await ctx.repo.transition_flow(flow.id, "idp_ok", "completed", now_ts()):
        return message_page("link_expired", 410)

    outcome = await ctx.verification.complete_microsoft(
        flow.user_id,
        subject_hmac(ctx.settings.hmac_key, identity.subject),
        identity.login,
        identity.employee_type,
    )
    response = outcome_page(outcome)
    response.del_cookie(FLOW_COOKIE, path="/")
    return response


def outcome_page(outcome: Outcome) -> web.Response:
    extra = T.WEB_TEACHER_PENDING if outcome.teacher_review else None
    if outcome.code == "verified":
        return message_page("verified", 200, extra=extra, status=T.LABELS.get(outcome.status or "", ""))
    if outcome.code in ("former", "pending"):
        return message_page(outcome.code, 200, extra=extra)
    return message_page(outcome.code, 403)
