"""Local SAML IdP for development and tests — NEVER expose it to a network.

It signs whatever test identity you click, so use it only with PUBLIC_BASE_URL=http://localhost:8080.

    .venv/bin/python dev/dev_idp.py
    # then in .env:
    #   SAML_IDP_METADATA_FILE=dev/idp_metadata.xml
    #   SAML_IDP_ENTITY_ID=http://localhost:8081/metadata
"""

from __future__ import annotations

import argparse
import base64
import html
import uuid
import zlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from onelogin.saml2.constants import OneLogin_Saml2_Constants as C
from onelogin.saml2.utils import OneLogin_Saml2_Utils
from onelogin.saml2.xml_utils import OneLogin_Saml2_XML

HERE = Path(__file__).resolve().parent
SAML_NS = "urn:oasis:names:tc:SAML:2.0:assertion"
ATTRNAME_URI = "urn:oasis:names:tc:SAML:2.0:attrname-format:uri"

# name → (eduPersonPrincipalName, eduPersonScopedAffiliation values)
TEST_USERS: dict[str, tuple[str, list[str]]] = {
    "student": ("xstudent@stuba.sk", ["student@stuba.sk", "member@stuba.sk"]),
    "teacher": ("xucitel@stuba.sk", ["faculty@stuba.sk", "employee@stuba.sk", "member@stuba.sk"]),
    "phd-employee": ("xdoktorand@stuba.sk", ["student@stuba.sk", "employee@stuba.sk", "member@stuba.sk"]),
    "alum": ("xabsolvent@stuba.sk", ["alum@stuba.sk"]),
    "applicant": ("xuchadzac@stuba.sk", ["affiliate@stuba.sk"]),
    "no-affiliation": ("xnikto@stuba.sk", ["member@stuba.sk"]),
    "wrong-scope": ("xcudzi@evil.sk", ["student@evil.sk"]),
}


def make_keypair(common_name: str) -> tuple[str, str]:
    """(private key PEM, self-signed certificate PEM)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ).decode()
    return key_pem, cert.public_bytes(serialization.Encoding.PEM).decode()


@dataclass(frozen=True)
class AuthnRequestInfo:
    id: str
    issuer: str
    acs_url: str | None


def parse_redirect_request(saml_request: str) -> AuthnRequestInfo:
    xml = zlib.decompress(base64.b64decode(saml_request), -15)
    root = OneLogin_Saml2_XML.to_etree(xml)
    issuer = root.find(f"{{{SAML_NS}}}Issuer")
    request_id = root.get("ID")
    if request_id is None or issuer is None or not issuer.text:
        raise ValueError("not a SAML AuthnRequest")
    return AuthnRequestInfo(request_id, issuer.text.strip(), root.get("AssertionConsumerServiceURL"))


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_response(
    *, idp_entity_id: str, request: AuthnRequestInfo, acs_url: str, eppn: str, scoped_affiliations: list[str]
) -> str:
    now = datetime.now(UTC)
    later = _ts(now + timedelta(minutes=5))
    esc = html.escape
    values = "".join(f"<saml:AttributeValue>{esc(v)}</saml:AttributeValue>" for v in scoped_affiliations)
    return (
        f'<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" xmlns:saml="{SAML_NS}" '
        f'ID="_{uuid.uuid4().hex}" Version="2.0" IssueInstant="{_ts(now)}" Destination="{esc(acs_url)}" '
        f'InResponseTo="{esc(request.id)}">'
        f"<saml:Issuer>{esc(idp_entity_id)}</saml:Issuer>"
        '<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
        f'<saml:Assertion ID="_{uuid.uuid4().hex}" Version="2.0" IssueInstant="{_ts(now)}">'
        f"<saml:Issuer>{esc(idp_entity_id)}</saml:Issuer>"
        f'<saml:Subject><saml:NameID Format="{C.NAMEID_TRANSIENT}">_{uuid.uuid4().hex}</saml:NameID>'
        '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData NotOnOrAfter="{later}" Recipient="{esc(acs_url)}" '
        f'InResponseTo="{esc(request.id)}"/></saml:SubjectConfirmation></saml:Subject>'
        f'<saml:Conditions NotBefore="{_ts(now - timedelta(minutes=1))}" NotOnOrAfter="{later}">'
        f"<saml:AudienceRestriction><saml:Audience>{esc(request.issuer)}</saml:Audience></saml:AudienceRestriction>"
        "</saml:Conditions>"
        f'<saml:AuthnStatement AuthnInstant="{_ts(now)}" SessionIndex="_{uuid.uuid4().hex}"><saml:AuthnContext>'
        f"<saml:AuthnContextClassRef>{C.AC_PASSWORD_PROTECTED}</saml:AuthnContextClassRef>"
        "</saml:AuthnContext></saml:AuthnStatement>"
        "<saml:AttributeStatement>"
        f'<saml:Attribute Name="urn:oid:1.3.6.1.4.1.5923.1.1.1.6" NameFormat="{ATTRNAME_URI}" '
        f'FriendlyName="eduPersonPrincipalName"><saml:AttributeValue>{esc(eppn)}</saml:AttributeValue></saml:Attribute>'
        f'<saml:Attribute Name="urn:oid:1.3.6.1.4.1.5923.1.1.1.9" NameFormat="{ATTRNAME_URI}" '
        f'FriendlyName="eduPersonScopedAffiliation">{values}</saml:Attribute>'
        "</saml:AttributeStatement></saml:Assertion></samlp:Response>"
    )


def signed_response_b64(*, key_pem: str, cert_pem: str, **kwargs: object) -> str:
    xml = build_response(**kwargs)  # type: ignore[arg-type]
    signed = OneLogin_Saml2_Utils.add_sign(
        xml, key_pem, cert_pem, sign_algorithm=C.RSA_SHA256, digest_algorithm=C.SHA256
    )
    return base64.b64encode(signed if isinstance(signed, bytes) else signed.encode()).decode()


def metadata_xml(entity_id: str, sso_url: str, cert_pem: str) -> str:
    body = "".join(line for line in cert_pem.splitlines() if "CERTIFICATE" not in line)
    return (
        '<?xml version="1.0"?>\n'
        '<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" '
        f'xmlns:ds="http://www.w3.org/2000/09/xmldsig#" entityID="{entity_id}">'
        '<md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
        '<md:KeyDescriptor use="signing"><ds:KeyInfo><ds:X509Data>'
        f"<ds:X509Certificate>{body}</ds:X509Certificate></ds:X509Data></ds:KeyInfo></md:KeyDescriptor>"
        f'<md:SingleSignOnService Binding="{C.BINDING_HTTP_REDIRECT}" Location="{sso_url}"/>'
        "</md:IDPSSODescriptor></md:EntityDescriptor>\n"
    )


PAGE = (
    '<!doctype html><meta charset="utf-8"><title>STUard dev IdP</title><body style="font-family:sans-serif">{}</body>'
)


def create_app(
    *, entity_id: str, base_url: str, key_pem: str, cert_pem: str, allowed_acs_prefix: str
) -> web.Application:
    async def metadata(request: web.Request) -> web.Response:
        return web.Response(text=metadata_xml(entity_id, f"{base_url}/sso", cert_pem), content_type="application/xml")

    async def sso(request: web.Request) -> web.Response:
        saml_request = request.query.get("SAMLRequest", "")
        relay_state = request.query.get("RelayState", "")
        info = parse_redirect_request(saml_request)
        buttons = "".join(
            f'<p><button name="user" value="{html.escape(name)}">{html.escape(name)}</button> '
            f"{html.escape(eppn)} — {html.escape(', '.join(affs))}</p>"
            for name, (eppn, affs) in TEST_USERS.items()
        )
        body = (
            "<h1>STUard dev IdP</h1><p><b>Only for local development.</b> "
            f"Service provider: {html.escape(info.issuer)}</p>"
            '<form method="post" action="/sso/login">'
            f'<input type="hidden" name="SAMLRequest" value="{html.escape(saml_request)}">'
            f'<input type="hidden" name="RelayState" value="{html.escape(relay_state)}">{buttons}</form>'
        )
        return web.Response(text=PAGE.format(body), content_type="text/html")

    async def login(request: web.Request) -> web.Response:
        form = await request.post()
        info = parse_redirect_request(str(form["SAMLRequest"]))
        acs_url = info.acs_url
        if not acs_url or not acs_url.startswith(allowed_acs_prefix):
            raise web.HTTPBadRequest(text="unexpected AssertionConsumerServiceURL")
        eppn, affiliations = TEST_USERS[str(form["user"])]
        response = signed_response_b64(
            key_pem=key_pem,
            cert_pem=cert_pem,
            idp_entity_id=entity_id,
            request=info,
            acs_url=acs_url,
            eppn=eppn,
            scoped_affiliations=affiliations,
        )
        body = (
            f'<form method="post" action="{html.escape(acs_url)}">'
            f'<input type="hidden" name="SAMLResponse" value="{response}">'
            f'<input type="hidden" name="RelayState" value="{html.escape(str(form["RelayState"]))}">'
            f"<p>Signed in as {html.escape(eppn)}.</p><button>Continue to STUard</button></form>"
        )
        return web.Response(text=PAGE.format(body), content_type="text/html")

    app = web.Application()
    app.router.add_get("/metadata", metadata)
    app.router.add_get("/sso", sso)
    app.router.add_post("/sso/login", login)
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Local SAML IdP for STUard development")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--sp-base-url", default="http://localhost:8080")
    args = parser.parse_args()
    if not args.sp_base_url.startswith(("http://localhost", "http://127.0.0.1")):
        raise SystemExit("the dev IdP only works with a localhost service provider")

    base_url = f"http://localhost:{args.port}"
    entity_id = f"{base_url}/metadata"
    key_path, cert_path = HERE / "idp-key.pem", HERE / "idp-cert.pem"
    if not key_path.exists():
        key_pem, cert_pem = make_keypair("stuard-dev-idp")
        key_path.write_text(key_pem, encoding="utf-8")
        key_path.chmod(0o600)
        cert_path.write_text(cert_pem, encoding="utf-8")
    key_pem, cert_pem = key_path.read_text(encoding="utf-8"), cert_path.read_text(encoding="utf-8")
    (HERE / "idp_metadata.xml").write_text(metadata_xml(entity_id, f"{base_url}/sso", cert_pem), encoding="utf-8")
    print(f"STUard dev IdP on {base_url}")
    print("  SAML_IDP_METADATA_FILE=dev/idp_metadata.xml")
    print(f"  SAML_IDP_ENTITY_ID={entity_id}")
    app = create_app(
        entity_id=entity_id, base_url=base_url, key_pem=key_pem, cert_pem=cert_pem, allowed_acs_prefix=args.sp_base_url
    )
    web.run_app(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
