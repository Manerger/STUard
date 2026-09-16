"""Secrets and deployment settings, read from the environment / .env."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_HMAC_KEY_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    discord_token: SecretStr
    discord_guild_id: int
    discord_client_id: str = ""
    discord_client_secret: SecretStr = SecretStr("")
    sync_commands: bool = False
    microsoft_client_id: str = ""
    microsoft_client_secret: SecretStr = SecretStr("")

    public_base_url: str = "http://localhost:8080"
    web_host: str = "0.0.0.0"  # noqa: S104 - inside a container, published only via the reverse proxy
    web_port: int = 8080
    discord_oauth_required: bool = True
    dev_allow_http: bool = False
    # Only enable behind a reverse proxy that overwrites X-Forwarded-For (Caddy does by default).
    trust_forwarded_for: bool = False

    subject_hmac_key: SecretStr

    saml_sp_key_file: Path = Path("secrets/sp.key")
    saml_sp_cert_file: Path = Path("secrets/sp.crt")
    saml_idp_metadata_file: Path = Path("saml/idp_metadata.xml")
    saml_idp_entity_id: str = "https://idp.stuba.sk/idp/shibboleth"

    database_path: Path = Path("data/stuard.sqlite3")
    config_path: Path = Path("config.yaml")
    log_level: str = "INFO"

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @model_validator(mode="after")
    def _check_security(self) -> Settings:
        if not self.public_base_url.startswith("https://") and not self.dev_allow_http:
            raise ValueError(
                "PUBLIC_BASE_URL must start with https:// (set DEV_ALLOW_HTTP=true only for local development)"
            )
        if len(self.subject_hmac_key.get_secret_value()) < MIN_HMAC_KEY_LENGTH:
            raise ValueError(f"SUBJECT_HMAC_KEY must be at least {MIN_HMAC_KEY_LENGTH} characters")
        if self.discord_oauth_required and not (
            self.discord_client_id and self.discord_client_secret.get_secret_value()
        ):
            raise ValueError(
                "DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET are required when DISCORD_OAUTH_REQUIRED=true"
            )
        return self

    @property
    def secure_cookies(self) -> bool:
        return self.public_base_url.startswith("https://")

    @property
    def hmac_key(self) -> bytes:
        return self.subject_hmac_key.get_secret_value().encode("utf-8")
