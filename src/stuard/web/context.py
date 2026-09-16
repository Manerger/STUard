from __future__ import annotations

from aiohttp import web

# The running StuardBot (or a test double exposing the same attributes):
# settings, cfg, repo, saml, oauth, verification, audit, web_limiter, describe_user().
CTX_KEY: web.AppKey[object] = web.AppKey("stuard_ctx", object)
