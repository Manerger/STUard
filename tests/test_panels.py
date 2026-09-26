from __future__ import annotations

from stuard import texts as T
from stuard.bot.ui.panels import verify_panel_embed
from tests.fakes import namespace


def _bot(*, sso: bool = False, microsoft: bool = False, email: bool = False, manual: bool = False) -> namespace:
    return namespace(
        verification=namespace(
            sso_enabled=lambda: sso,
            microsoft_enabled=lambda: microsoft,
            manual_available=lambda: manual,
        ),
        email=namespace(enabled=lambda: email),
    )


def test_panel_lists_only_enabled_methods() -> None:
    desc = verify_panel_embed(_bot(microsoft=True, email=True)).description or ""
    assert T.VERIFY_OPTION_MICROSOFT in desc
    assert T.VERIFY_OPTION_EMAIL in desc
    assert T.VERIFY_OPTION_STU not in desc
    assert T.VERIFY_OPTION_MANUAL not in desc
    assert T.VERIFY_PANEL_FOOTER in desc


def test_panel_shows_all_four_when_all_enabled() -> None:
    desc = verify_panel_embed(_bot(sso=True, microsoft=True, email=True, manual=True)).description or ""
    for line in (T.VERIFY_OPTION_STU, T.VERIFY_OPTION_MICROSOFT, T.VERIFY_OPTION_EMAIL, T.VERIFY_OPTION_MANUAL):
        assert line in desc


def test_panel_falls_back_when_nothing_enabled() -> None:
    embed = verify_panel_embed(_bot())
    assert embed.description == T.VERIFY_PANEL_NONE
