from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import sys

import yaml
from pydantic import ValidationError

from stuard.config import AppConfig, load_config
from stuard.logsetup import setup_logging
from stuard.settings import Settings

log = logging.getLogger("stuard")


async def run(settings: Settings, cfg: AppConfig) -> None:
    from stuard.bot.app import StuardBot

    bot = StuardBot(settings, cfg)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop.set)

    async with bot:
        bot_task = asyncio.create_task(bot.start(settings.discord_token.get_secret_value()))
        stop_task = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait({bot_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if stop_task in done:
            log.info("shutting down")
            await bot.close()
        else:
            stop_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await bot_task


def main() -> None:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except ValidationError as exc:
        print(f"Invalid environment / .env:\n{exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    setup_logging(settings.log_level)
    try:
        cfg = load_config(settings.config_path)
    except FileNotFoundError:
        log.error("config file %s not found — copy config.example.yaml to config.yaml", settings.config_path)
        raise SystemExit(2) from None
    except (ValidationError, yaml.YAMLError) as exc:
        log.error("invalid %s:\n%s", settings.config_path, exc)
        raise SystemExit(2) from exc
    asyncio.run(run(settings, cfg))


if __name__ == "__main__":
    main()
