from __future__ import annotations

import logging
import secrets
from collections.abc import Awaitable, Callable

from aiohttp import web

from stuard.web.render import message_page

log = logging.getLogger(__name__)

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; img-src 'self' https://cdn.discordapp.com; "
        "frame-ancestors 'none'; base-uri 'none'"
    ),
    "Referrer-Policy": "no-referrer",  # verification tokens are in URLs
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Cache-Control": "no-store",
}


@web.middleware
async def security_headers(request: web.Request, handler: Handler) -> web.StreamResponse:
    try:
        response = await handler(request)
    except web.HTTPException as exc:
        exc.headers.update(SECURITY_HEADERS)
        raise
    response.headers.update(SECURITY_HEADERS)
    return response


@web.middleware
async def error_pages(request: web.Request, handler: Handler) -> web.StreamResponse:
    try:
        return await handler(request)
    except web.HTTPNotFound:
        return message_page("not_found", 404)
    except web.HTTPException:
        raise
    except Exception:
        ref = secrets.token_hex(4)
        log.exception("unhandled error in %s %s (ref %s)", request.method, request.path, ref)
        return message_page("error", 500, ref=ref)
