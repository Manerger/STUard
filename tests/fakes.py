"""Lightweight test doubles for services that talk to Discord."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from stuard.config import AppConfig
from stuard.db.repos import Repo
from stuard.services.members import MemberService
from stuard.settings import Settings

HMAC_KEY = "k" * 48


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "discord_token": "test-token",
        "discord_guild_id": 1,
        "subject_hmac_key": HMAC_KEY,
        "public_base_url": "https://verify.test",
        "discord_oauth_required": True,
        "discord_client_id": "123",
        "discord_client_secret": "secret",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)  # type: ignore[call-arg]


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def log(self, action: str, **kwargs: Any) -> None:
        self.events.append((action, kwargs))

    @property
    def actions(self) -> list[str]:
        return [action for action, _ in self.events]


class FakeRoles:
    def __init__(self) -> None:
        self.synced: list[int] = []

    async def sync_user(self, user_id: int, *, reason: str) -> bool:
        self.synced.append(user_id)
        return True


class FakeReviews:
    def __init__(self) -> None:
        self.opened: list[tuple[int, str, str | None]] = []
        self.logins: list[str | None] = []

    async def open_sso_review(
        self,
        user_id: int,
        source: str,
        affiliations: Any,
        *,
        suggest: str | None,
        login: str | None = None,
        via: str = "saml",
    ) -> bool:
        self.opened.append((user_id, source, suggest))
        self.logins.append(login)
        return True


class FakeBot:
    def __init__(self, repo: Repo, cfg: AppConfig) -> None:
        self.repo = repo
        self.cfg = cfg
        self.settings = make_settings()
        self.saml: object | None = object()
        self.microsoft: object | None = object()
        self.sso_override: bool | None = None
        self.microsoft_override: bool | None = None
        self.guild = None
        self.audit = FakeAudit()
        self.roles = FakeRoles()
        self.reviews: Any = FakeReviews()
        self.members = MemberService(self)  # type: ignore[arg-type]
        self.dms: list[tuple[int, str]] = []

    async def dm(self, user_id: int, text: str) -> bool:
        self.dms.append((user_id, text))
        return True

    def get_channel(self, channel_id: int) -> None:
        return None

    def resolve_channel(self, ref: int | str | None) -> None:
        return None


def namespace(**kwargs: Any) -> SimpleNamespace:
    return SimpleNamespace(**kwargs)
