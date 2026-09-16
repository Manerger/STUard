from __future__ import annotations

from functools import cache
from importlib import resources
from typing import Any

import jinja2
from aiohttp import web

from stuard import texts as T

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("stuard", "web/templates"),
    autoescape=jinja2.select_autoescape(default=True, default_for_string=True),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render(template: str, *, status: int = 200, **context: Any) -> web.Response:
    html = _env.get_template(template).render(site_title=T.WEB_SITE_TITLE, **context)
    return web.Response(text=html, status=status, content_type="text/html", charset="utf-8")


def message_page(key: str, http_status: int, /, *, extra: str | None = None, **fmt: Any) -> web.Response:
    """Positional-only arguments, so message placeholders such as {status} can be passed as keywords."""
    title, body = T.WEB_MESSAGES[key]
    return render(
        "message.html",
        status=http_status,
        title=title,
        body=body.format(**fmt),
        extra=extra,
        success=200 <= http_status < 300,
    )


@cache
def stylesheet() -> str:
    return (resources.files("stuard") / "web" / "static" / "style.css").read_text(encoding="utf-8")
