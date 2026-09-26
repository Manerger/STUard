from __future__ import annotations

import importlib
import pkgutil
import re
from pathlib import Path

import stuard
from stuard import texts as T
from stuard.bot.app import EXTENSIONS, StuardBot
from stuard.config import AppConfig
from tests.fakes import make_settings

SRC = Path(stuard.__file__).resolve().parent


def test_all_modules_import() -> None:
    for module in pkgutil.walk_packages(stuard.__path__, "stuard."):
        importlib.import_module(module.name)


def test_every_referenced_text_exists() -> None:
    pattern = re.compile(r"\bT\.([A-Za-z_][A-Za-z0-9_]*)")
    missing = sorted(
        f"{path.relative_to(SRC)}: {name}"
        for path in SRC.rglob("*.py")
        for name in pattern.findall(path.read_text(encoding="utf-8"))
        if not hasattr(T, name)
    )
    assert missing == []


def test_web_messages_format() -> None:
    for title, body in T.WEB_MESSAGES.values():
        assert title
        body.format(status="Študent", ref="abcd")


def test_privacy_notice_fits_an_embed(cfg: AppConfig) -> None:
    text = "\n\n".join(T.privacy_notice(cfg))
    assert "idp.stuba.sk" in text and "/forget-me" in text
    assert len(text) < 4000


async def test_slash_commands_register(cfg: AppConfig) -> None:
    async with StuardBot(make_settings(), cfg) as bot:
        for extension in EXTENSIONS:
            if not extension.endswith(".events"):  # events starts background loops
                await bot.load_extension(extension)
        commands = {command.name: command for command in bot.tree.get_commands()}
        assert set(commands) == {
            "verify", "verify-manual", "verify-email", "verify-code",
            "profile", "privacy", "forget-me", "mod", "setup", "admin",
        }
        for command in commands.values():
            payload = command.to_dict(bot.tree)
            assert 1 <= len(payload["description"]) <= 100
            for option in payload.get("options", []):
                assert len(option["description"]) <= 100
        mod = commands["mod"]
        assert {c.name for c in mod.commands} == {  # type: ignore[union-attr]
            "status",
            "teacher",
            "info",
            "unlink",
            "readmit",
            "reverify",
            "requests",
            "lookup",
        }
