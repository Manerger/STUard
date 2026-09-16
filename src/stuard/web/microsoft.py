"""Sign in with Microsoft 365 (Entra ID, OpenID Connect), restricted to the STU tenant.

STU's Microsoft 365 logins are federated to idp.stuba.sk, so the password is still typed only on STU's page.
After sign-in the bot reads the AIS ID (`employeeId`) and account type (`employeeType`) from Microsoft Graph
with the basic User.Read permission. The AIS ID is the same number STU's own login (idp.stuba.sk) uses in
eduPersonPrincipalName, so both logins lead to the same identity.

Whether students may approve the app themselves depends on STU's tenant consent settings; if not, Microsoft
shows "Need admin approval" and manual review remains the fallback.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import logging
import re
import secrets
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from urllib.parse import urlencode

import aiohttp
import jwt

from stuard.domain.mapping import scope_allowed
from stuard.security.tokens import hash_token

if TYPE_CHECKING:
    from stuard.config import AppConfig
    from stuard.settings import Settings

log = logging.getLogger(__name__)

AUTHORITY = "https://login.microsoftonline.com"
GRAPH = "https://graph.microsoft.com"
SCOPES = "openid profile User.Read"
PROFILE_FIELDS = "id,userPrincipalName,employeeId,employeeType"
# Authorization errors that mean STU's tenant requires administrator consent before this app can be used.
ADMIN_CONSENT_CODES = frozenset({"AADSTS65001", "AADSTS90094", "AADSTS90095"})
_AADSTS = re.compile(r"\bAADSTS\d+\b")
_AIS_ID = re.compile(r"^[0-9]{1,12}$")


def aadsts_code(description: str | None) -> str | None:
    match = _AADSTS.search(description or "")
    return match.group(0) if match else None


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, S256 code_challenge) for PKCE."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class MicrosoftValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class TokenSet:
    id_token: str
    access_token: str


@dataclass(frozen=True, slots=True)
class MicrosoftAccount:
    """Claims from a validated ID token."""

    login: str  # preferred_username (UPN), lowercase, e.g. xnovak@stuba.sk
    object_id: str


@dataclass(frozen=True, slots=True)
class MicrosoftProfile:
    object_id: str | None
    user_principal_name: str | None
    employee_id: str | None
    employee_type: str | None


@dataclass(frozen=True, slots=True)
class MicrosoftIdentity:
    login: str
    # Identifier for duplicate detection: "<AIS ID>@stuba.sk" (same as STU's eduPersonPrincipalName) or the login.
    subject: str
    employee_id: str | None
    employee_type: str | None


class SigningKeySource(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class MicrosoftSignIn:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        tenant_id: str,
        allowed_domains: Iterable[str],
        authority: str = AUTHORITY,
        graph: str = GRAPH,
        signing_keys: SigningKeySource | None = None,
    ) -> None:
        self.client_id = client_id
        self._client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.tenant_id = tenant_id.lower()
        self.allowed_domains = [d.lower() for d in allowed_domains]
        self.id_scope = self.allowed_domains[0]
        base = f"{authority.rstrip('/')}/{self.tenant_id}"
        self.authorize_endpoint = f"{base}/oauth2/v2.0/authorize"
        self.token_endpoint = f"{base}/oauth2/v2.0/token"
        self.profile_endpoint = f"{graph.rstrip('/')}/v1.0/me"
        self.issuer = f"{AUTHORITY}/{self.tenant_id}/v2.0"
        self._signing_keys = signing_keys or jwt.PyJWKClient(
            f"{base}/discovery/v2.0/keys", cache_keys=True, lifespan=3600, timeout=10
        )

    def authorize_url(self, *, state: str, nonce: str, code_challenge: str) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "response_type": "code",
                "response_mode": "query",
                "redirect_uri": self.redirect_uri,
                "scope": SCOPES,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                "prompt": "login",  # always ask for credentials (shared lab PCs)
                "domain_hint": self.id_scope,
            }
        )
        return f"{self.authorize_endpoint}?{query}"

    async def complete_sign_in(self, code: str, code_verifier: str, nonce_hash: bytes) -> MicrosoftIdentity:
        """Redeem the code, validate the ID token and read the AIS ID and account type from Microsoft Graph."""
        tokens = await self.exchange_code(code, code_verifier)
        account = await asyncio.to_thread(self.validate_id_token, tokens.id_token, nonce_hash)
        profile = await self.fetch_profile(tokens.access_token)
        if profile.object_id != account.object_id:
            raise MicrosoftValidationError("profile_mismatch")
        employee_id = profile.employee_id
        if employee_id is not None and not _AIS_ID.match(employee_id):
            log.warning("Microsoft profile has an employeeId that is not a numeric AIS ID; using the login instead")
            employee_id = None
        subject = f"{employee_id}@{self.id_scope}" if employee_id else account.login
        return MicrosoftIdentity(account.login, subject, employee_id, profile.employee_type)

    async def exchange_code(self, code: str, code_verifier: str) -> TokenSet:
        """Redeem the authorization code (with the PKCE verifier) for an ID token and a Graph access token."""
        data = {
            "client_id": self.client_id,
            "client_secret": self._client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.redirect_uri,
            "code_verifier": code_verifier,
            "scope": SCOPES,
        }
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.post(self.token_endpoint, data=data) as resp:
                    status = resp.status
                    body = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise MicrosoftValidationError("token_request") from exc
        if status != 200 or not isinstance(body, dict):
            detail = aadsts_code(str(body.get("error_description"))) if isinstance(body, dict) else None
            log.warning("Microsoft token exchange failed: HTTP %s %s", status, detail or "")
            raise MicrosoftValidationError("token_exchange")
        id_token, access_token = body.get("id_token"), body.get("access_token")
        if not isinstance(id_token, str):
            raise MicrosoftValidationError("no_id_token")
        if not isinstance(access_token, str):
            raise MicrosoftValidationError("no_access_token")
        return TokenSet(id_token, access_token)

    def validate_id_token(self, id_token: str, nonce_hash: bytes) -> MicrosoftAccount:
        """Blocking (may fetch Microsoft's signing keys) — call via asyncio.to_thread."""
        try:
            key = self._signing_keys.get_signing_key_from_jwt(id_token).key
            claims = jwt.decode(
                id_token,
                key,
                algorithms=["RS256"],
                audience=self.client_id,
                issuer=self.issuer,
                leeway=120,
                options={"require": ["exp", "iat", "iss", "aud", "tid", "nonce"]},
            )
        except jwt.PyJWKClientError as exc:
            log.warning("could not get Microsoft signing keys: %s", type(exc).__name__)
            raise MicrosoftValidationError("signing_keys") from exc
        except jwt.InvalidTokenError as exc:
            log.warning("Microsoft ID token rejected: %s", type(exc).__name__)
            raise MicrosoftValidationError("invalid_token") from exc

        if str(claims["tid"]).lower() != self.tenant_id:
            raise MicrosoftValidationError("tenant")
        if not hmac.compare_digest(hash_token(str(claims["nonce"])), nonce_hash):
            raise MicrosoftValidationError("nonce")
        # Guests invited into the STU tenant authenticate elsewhere; the idp claim reveals that.
        idp = claims.get("idp")
        if idp is not None and idp not in (self.issuer, f"https://sts.windows.net/{self.tenant_id}/"):
            raise MicrosoftValidationError("guest_account")
        login = str(claims.get("preferred_username") or "").strip().lower()
        local, sep, domain = login.rpartition("@")
        if not sep or not local or not scope_allowed(domain, self.allowed_domains):
            raise MicrosoftValidationError("domain")
        object_id = claims.get("oid")
        if not isinstance(object_id, str) or not object_id:
            raise MicrosoftValidationError("no_object_id")
        return MicrosoftAccount(login, object_id)

    async def fetch_profile(self, access_token: str) -> MicrosoftProfile:
        """Read only the fields the bot needs from the signed-in user's profile (User.Read)."""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                async with session.get(
                    self.profile_endpoint,
                    params={"$select": PROFILE_FIELDS},
                    headers={"Authorization": f"Bearer {access_token}"},
                ) as resp:
                    status = resp.status
                    body = await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
            raise MicrosoftValidationError("profile_request") from exc
        if status != 200 or not isinstance(body, dict):
            log.warning("Microsoft Graph profile request failed: HTTP %s", status)
            raise MicrosoftValidationError("profile")

        def text(field: str) -> str | None:
            value = body.get(field)
            return value.strip() if isinstance(value, str) and value.strip() else None

        return MicrosoftProfile(text("id"), text("userPrincipalName"), text("employeeId"), text("employeeType"))


def load_microsoft(settings: Settings, cfg: AppConfig) -> MicrosoftSignIn | None:
    secret = settings.microsoft_client_secret.get_secret_value()
    if not (settings.microsoft_client_id and secret):
        if cfg.microsoft.enabled:
            log.warning("microsoft.enabled is true but MICROSOFT_CLIENT_ID / MICROSOFT_CLIENT_SECRET are missing")
        return None
    return MicrosoftSignIn(
        client_id=settings.microsoft_client_id,
        client_secret=secret,
        redirect_uri=f"{settings.public_base_url}/oauth/microsoft/callback",
        tenant_id=cfg.microsoft.tenant_id,
        allowed_domains=cfg.microsoft.allowed_domains,
    )
