"""Minimal Discord OAuth2 (scope=identify) to prove which Discord account the browser belongs to."""

from __future__ import annotations

import logging
from urllib.parse import urlencode

import aiohttp

log = logging.getLogger(__name__)

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
TOKEN_URL = "https://discord.com/api/v10/oauth2/token"  # noqa: S105 - endpoint URL, not a secret
REVOKE_URL = "https://discord.com/api/v10/oauth2/token/revoke"
ME_URL = "https://discord.com/api/v10/users/@me"


class OAuthError(Exception):
    pass


class DiscordOAuth:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str) -> None:
        self.client_id = client_id
        self._client_secret = client_secret
        self.redirect_uri = redirect_uri

    def authorize_url(self, state: str) -> str:
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": "identify",
                "state": state,
                "prompt": "none",
            }
        )
        return f"{AUTHORIZE_URL}?{query}"

    async def fetch_user_id(self, code: str) -> int:
        auth = aiohttp.BasicAuth(self.client_id, self._client_secret)
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.post(
                    TOKEN_URL,
                    data={"grant_type": "authorization_code", "code": code, "redirect_uri": self.redirect_uri},
                    auth=auth,
                ) as resp:
                    if resp.status != 200:
                        raise OAuthError(f"token exchange failed with HTTP {resp.status}")
                    access_token = (await resp.json()).get("access_token")
                if not isinstance(access_token, str):
                    raise OAuthError("token response without access_token")
                async with session.get(ME_URL, headers={"Authorization": f"Bearer {access_token}"}) as resp:
                    if resp.status != 200:
                        raise OAuthError(f"user lookup failed with HTTP {resp.status}")
                    user_id = int((await resp.json())["id"])
            except (aiohttp.ClientError, TimeoutError, KeyError, ValueError) as exc:
                raise OAuthError(type(exc).__name__) from exc
            try:  # the token is not needed any more
                async with session.post(REVOKE_URL, data={"token": access_token}, auth=auth):
                    pass
            except (aiohttp.ClientError, TimeoutError):
                log.debug("token revocation failed", exc_info=True)
        return user_id
