from __future__ import annotations

import logging

from aiohttp import web

from stuard.web import routes
from stuard.web.context import CTX_KEY
from stuard.web.middleware import error_pages, security_headers

log = logging.getLogger(__name__)

MAX_BODY_BYTES = 256 * 1024  # SAML responses are a few KB


def build_app(ctx: object) -> web.Application:
    app = web.Application(middlewares=[security_headers, error_pages], client_max_size=MAX_BODY_BYTES)
    app[CTX_KEY] = ctx
    app.router.add_get("/healthz", routes.healthz)
    app.router.add_get("/privacy", routes.privacy)
    app.router.add_get("/static/style.css", routes.stylesheet)
    app.router.add_get("/v", routes.open_link)
    app.router.add_post("/v/confirm", routes.confirm)
    app.router.add_get("/oauth/discord/callback", routes.oauth_callback)
    app.router.add_get("/oauth/microsoft/callback", routes.microsoft_callback)
    app.router.add_get("/saml/metadata", routes.saml_metadata)
    app.router.add_post("/saml/acs", routes.acs)
    app.router.add_get("/verify/complete", routes.complete)
    return app


class WebServer:
    def __init__(self, ctx: object, host: str, port: int) -> None:
        self.ctx = ctx
        self.host = host
        self.port = port
        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        self._runner = web.AppRunner(build_app(self.ctx), access_log=None, handle_signals=False)
        await self._runner.setup()
        await web.TCPSite(self._runner, self.host, self.port).start()
        log.info("web server listening on %s:%s", self.host, self.port)

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
