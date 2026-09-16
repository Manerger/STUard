"""Full round trip: real SAML SP + web routes + VerificationService, with the dev IdP signing the response."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from dev.dev_idp import create_app as create_idp_app
from dev.dev_idp import make_keypair, metadata_xml
from stuard.config import AppConfig
from stuard.db.repos import Repo
from stuard.security.ratelimit import RateLimiter
from stuard.services.verification import VerificationService
from stuard.web.saml_sp import SamlSP
from stuard.web.server import build_app
from tests.fakes import FakeBot, make_settings, namespace

USER = 222_222
SP_BASE = "https://verify.test"
IDP_BASE = "http://localhost:8081"
IDP_ENTITY = f"{IDP_BASE}/metadata"


async def test_full_sso_round_trip(repo: Repo, cfg: AppConfig) -> None:
    idp_key, idp_cert = make_keypair("dev-idp")
    sp_key, sp_cert = make_keypair("verify.test")
    sp = SamlSP(
        base_url=SP_BASE,
        sp_cert=sp_cert,
        sp_key=sp_key,
        idp_metadata_xml=metadata_xml(IDP_ENTITY, f"{IDP_BASE}/sso", idp_cert),
        idp_entity_id=IDP_ENTITY,
    )
    bot = FakeBot(repo, cfg)
    bot.settings = make_settings(discord_oauth_required=False, public_base_url=SP_BASE)
    bot.saml = sp
    bot.sso_override = True
    verification = VerificationService(bot)  # type: ignore[arg-type]
    ctx = namespace(
        settings=bot.settings,
        cfg=cfg,
        repo=repo,
        saml=sp,
        oauth=None,
        verification=verification,
        audit=bot.audit,
        web_limiter=RateLimiter(100, 60),
        describe_user=lambda _user_id: ("Študent (@student)", None),
    )
    idp_app = create_idp_app(
        entity_id=IDP_ENTITY, base_url=IDP_BASE, key_pem=idp_key, cert_pem=idp_cert, allowed_acs_prefix=SP_BASE
    )

    async with (
        TestClient(TestServer(build_app(ctx)), cookie_jar=aiohttp.DummyCookieJar()) as browser,
        TestClient(TestServer(idp_app)) as idp,
    ):
        link = urlsplit(await verification.create_link(USER))
        resp = await browser.get(f"{link.path}?{link.query}", allow_redirects=False)
        assert resp.status == 200  # "is this you?" page
        cookie = {"Cookie": f"stuard_flow={resp.cookies['stuard_flow'].value}"}

        resp = await browser.post("/v/confirm", headers=cookie, allow_redirects=False)
        assert resp.status == 302
        to_idp = urlsplit(resp.headers["Location"])
        assert f"{to_idp.scheme}://{to_idp.netloc}{to_idp.path}" == f"{IDP_BASE}/sso"
        query = {k: v[0] for k, v in parse_qs(to_idp.query).items()}
        assert "Signature" in query

        assert (await idp.get("/sso", params={"SAMLRequest": query["SAMLRequest"]})).status == 200
        resp = await idp.post(
            "/sso/login",
            data={"SAMLRequest": query["SAMLRequest"], "RelayState": query["RelayState"], "user": "phd-employee"},
        )
        page = await resp.text()
        saml_response = re.search(r'name="SAMLResponse" value="([^"]+)"', page)
        relay_state = re.search(r'name="RelayState" value="([^"]+)"', page)
        assert saml_response and relay_state

        resp = await browser.post(
            "/saml/acs",
            data={"SAMLResponse": saml_response.group(1), "RelayState": relay_state.group(1)},
            allow_redirects=False,
        )
        assert resp.status == 303, await resp.text()
        resp = await browser.get(resp.headers["Location"], headers=cookie, allow_redirects=False)
        assert resp.status == 200
        assert "Overenie úspešné" in await resp.text()

    member = await repo.get_member(USER)
    assert member is not None and (member.status, member.method) == ("student", "sso")
    identity = await repo.get_identity_by_user(USER)
    assert identity is not None and identity.affiliations == ["employee", "member", "student"]
    assert bot.reviews.opened == [(USER, "sso_teacher", "teacher")]
