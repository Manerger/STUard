"""Look a login up in STU's directory (anonymous LDAPS bind). Blocking; call from a thread.

Reachable only inside STU's network, so the bot must run behind the STU VPN. Only the record of the exact
login being verified is read; ownership is proved by the e-mail code, not by this lookup. `ldap3` is imported
lazily so the rest of the bot (and the tests, which inject a fake lookup) do not require it.
"""

from __future__ import annotations

import logging

from stuard.config import LdapCfg

log = logging.getLogger(__name__)

# Attributes we read; faculty is inferred from host/accountStatus (see domain/ldap_map).
ATTRIBUTES = ("uid", "uisId", "cn", "sn", "givenName", "mail", "employeeType", "host", "accountStatus")


class LdapDirectory:
    def __init__(self, cfg: LdapCfg) -> None:
        self.cfg = cfg

    def lookup(self, login: str) -> dict[str, object] | None:
        """Return the person's attributes, or None if not found / unreachable."""
        try:
            import ldap3  # noqa: PLC0415 - lazy: only the real lookup needs the dependency
        except ImportError:
            log.warning("ldap3 is not installed; LDAP enrichment unavailable")
            return None
        safe = login.replace("\\", "\\5c").replace("*", "\\2a").replace("(", "\\28").replace(")", "\\29")
        try:
            server = ldap3.Server(self.cfg.url, connect_timeout=self.cfg.timeout_seconds, get_info=None)
            conn = ldap3.Connection(server, auto_bind=True, receive_timeout=self.cfg.timeout_seconds)
            try:
                conn.search(
                    self.cfg.base_dn,
                    f"({self.cfg.login_attribute}={safe})",
                    attributes=list(ATTRIBUTES),
                    size_limit=2,
                )
                entries = conn.entries
            finally:
                conn.unbind()
        except Exception as exc:  # noqa: BLE001 - any ldap3 error → no enrichment, fall through
            log.warning("LDAP lookup failed: %r", exc)
            return None
        if len(entries) != 1:
            return None
        return {attr: entries[0][attr].values for attr in entries[0].entry_attributes}
