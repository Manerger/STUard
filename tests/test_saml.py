"""SAML validation against responses signed by a throw-away test IdP key."""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from onelogin.saml2.constants import OneLogin_Saml2_Constants as C
from onelogin.saml2.utils import OneLogin_Saml2_Utils

from stuard.web.saml_sp import SamlSP, SamlValidationError

IDP_ENTITY = "https://idp.test/idp/shibboleth"
BASE = "https://verify.test"
REQUEST_ID = "_req1"
KeyPair = tuple[str, str]  # (private key PEM, certificate PEM)


def make_keypair(common_name: str) -> KeyPair:
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
        .not_valid_after(now + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ).decode()
    return key_pem, cert.public_bytes(serialization.Encoding.PEM).decode()


@pytest.fixture(scope="module")
def idp_keys() -> KeyPair:
    return make_keypair("idp.test")


@pytest.fixture(scope="module")
def sp_keys() -> KeyPair:
    return make_keypair("verify.test")


def idp_metadata(cert_pem: str) -> str:
    body = "".join(line for line in cert_pem.splitlines() if "CERTIFICATE" not in line)
    return f"""<?xml version="1.0"?>
<md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata" xmlns:ds="http://www.w3.org/2000/09/xmldsig#"
    entityID="{IDP_ENTITY}">
  <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
    <md:KeyDescriptor use="signing">
      <ds:KeyInfo><ds:X509Data><ds:X509Certificate>{body}</ds:X509Certificate></ds:X509Data></ds:KeyInfo>
    </md:KeyDescriptor>
    <md:SingleSignOnService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
        Location="https://idp.test/idp/profile/SAML2/Redirect/SSO"/>
  </md:IDPSSODescriptor>
</md:EntityDescriptor>"""


def make_sp(sp_keys: KeyPair, idp_keys: KeyPair, base: str = BASE) -> SamlSP:
    return SamlSP(
        base_url=base,
        sp_cert=sp_keys[1],
        sp_key=sp_keys[0],
        idp_metadata_xml=idp_metadata(idp_keys[1]),
        idp_entity_id=IDP_ENTITY,
    )


def _ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_response(
    *,
    base: str = BASE,
    eppn: str | None = "xnovak@stuba.sk",
    scoped: tuple[str, ...] = ("student@stuba.sk", "member@stuba.sk"),
    audience: str | None = None,
    destination: str | None = None,
    issuer: str = IDP_ENTITY,
    not_before: datetime | None = None,
    not_on_or_after: datetime | None = None,
    in_response_to: bool = True,
) -> str:
    now = datetime.now(UTC)
    later = _ts(not_on_or_after or now + timedelta(minutes=5))
    before = _ts(not_before or now - timedelta(minutes=1))
    audience = audience or f"{base}/saml/metadata"
    destination = destination or f"{base}/saml/acs"
    irt = f' InResponseTo="{REQUEST_ID}"' if in_response_to else ""
    uri = "urn:oasis:names:tc:SAML:2.0:attrname-format:uri"
    attributes = ""
    if eppn is not None:
        attributes += (
            f'<saml:Attribute Name="urn:oid:1.3.6.1.4.1.5923.1.1.1.6" NameFormat="{uri}" '
            f'FriendlyName="eduPersonPrincipalName"><saml:AttributeValue>{eppn}</saml:AttributeValue></saml:Attribute>'
        )
    values = "".join(f"<saml:AttributeValue>{v}</saml:AttributeValue>" for v in scoped)
    attributes += (
        f'<saml:Attribute Name="urn:oid:1.3.6.1.4.1.5923.1.1.1.9" NameFormat="{uri}" '
        f'FriendlyName="eduPersonScopedAffiliation">{values}</saml:Attribute>'
    )
    return (
        f'<samlp:Response xmlns:samlp="urn:oasis:names:tc:SAML:2.0:protocol" '
        f'xmlns:saml="urn:oasis:names:tc:SAML:2.0:assertion" ID="_{uuid.uuid4().hex}" Version="2.0" '
        f'IssueInstant="{_ts(now)}" Destination="{destination}"{irt}>'
        f"<saml:Issuer>{issuer}</saml:Issuer>"
        '<samlp:Status><samlp:StatusCode Value="urn:oasis:names:tc:SAML:2.0:status:Success"/></samlp:Status>'
        f'<saml:Assertion ID="_{uuid.uuid4().hex}" Version="2.0" IssueInstant="{_ts(now)}">'
        f"<saml:Issuer>{issuer}</saml:Issuer>"
        "<saml:Subject>"
        f'<saml:NameID Format="urn:oasis:names:tc:SAML:2.0:nameid-format:transient">_t{uuid.uuid4().hex}</saml:NameID>'
        '<saml:SubjectConfirmation Method="urn:oasis:names:tc:SAML:2.0:cm:bearer">'
        f'<saml:SubjectConfirmationData NotOnOrAfter="{later}" Recipient="{destination}"{irt}/>'
        "</saml:SubjectConfirmation></saml:Subject>"
        f'<saml:Conditions NotBefore="{before}" NotOnOrAfter="{later}">'
        f"<saml:AudienceRestriction><saml:Audience>{audience}</saml:Audience></saml:AudienceRestriction>"
        "</saml:Conditions>"
        f'<saml:AuthnStatement AuthnInstant="{_ts(now)}" SessionIndex="_s1"><saml:AuthnContext>'
        "<saml:AuthnContextClassRef>urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"
        "</saml:AuthnContextClassRef></saml:AuthnContext></saml:AuthnStatement>"
        f"<saml:AttributeStatement>{attributes}</saml:AttributeStatement>"
        "</saml:Assertion></samlp:Response>"
    )


def sign(xml: str, keys: KeyPair, algorithm: str = C.RSA_SHA256, digest: str = C.SHA256) -> str:
    signed = OneLogin_Saml2_Utils.add_sign(xml, keys[0], keys[1], sign_algorithm=algorithm, digest_algorithm=digest)
    return signed.decode() if isinstance(signed, bytes) else signed


def post(xml: str) -> dict[str, str]:
    return {"SAMLResponse": base64.b64encode(xml.encode()).decode(), "RelayState": "relay"}


def test_valid_signed_response(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    identity = make_sp(sp_keys, idp_keys).validate(post(sign(build_response(), idp_keys)), REQUEST_ID)
    assert identity.subject == "xnovak@stuba.sk"
    assert identity.scoped_affiliations == ["student@stuba.sk", "member@stuba.sk"]
    assert identity.assertion_id.startswith("_")
    assert identity.not_on_or_after is not None


def test_valid_on_localhost_with_port(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    base = "http://localhost:8080"
    identity = make_sp(sp_keys, idp_keys, base).validate(post(sign(build_response(base=base), idp_keys)), REQUEST_ID)
    assert identity.subject == "xnovak@stuba.sk"


def _rejects(sp: SamlSP, xml: str, request_id: str = REQUEST_ID) -> str:
    with pytest.raises(SamlValidationError) as info:
        sp.validate(post(xml), request_id)
    return info.value.code


def test_unsigned_response_rejected(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    _rejects(make_sp(sp_keys, idp_keys), build_response())


def test_response_signed_by_unknown_key_rejected(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    _rejects(make_sp(sp_keys, idp_keys), sign(build_response(), make_keypair("evil.test")))


def test_attribute_tampered_after_signing_rejected(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    tampered = sign(build_response(), idp_keys).replace("xnovak@stuba.sk", "xadmin@stuba.sk")
    _rejects(make_sp(sp_keys, idp_keys), tampered)


def test_injected_second_assertion_rejected(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    signed = sign(build_response(), idp_keys)
    start, end = signed.index("<saml:Assertion"), signed.index("</saml:Assertion>") + len("</saml:Assertion>")
    evil = signed[start:end].replace("xnovak@stuba.sk", "xadmin@stuba.sk")
    _rejects(make_sp(sp_keys, idp_keys), signed[:end] + evil + signed[end:])


def test_sha1_signature_rejected(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    _rejects(make_sp(sp_keys, idp_keys), sign(build_response(), idp_keys, C.RSA_SHA1, C.SHA1))


NOW = datetime.now(UTC)


@pytest.mark.parametrize(
    "overrides",
    [
        {"audience": "https://other.test/saml/metadata"},
        {"destination": "https://other.test/saml/acs"},
        {"issuer": "https://evil.test/idp"},
        {"not_before": NOW - timedelta(hours=2), "not_on_or_after": NOW - timedelta(hours=1)},
        {"not_before": NOW + timedelta(hours=1), "not_on_or_after": NOW + timedelta(hours=2)},
    ],
    ids=["audience", "destination", "issuer", "expired", "not-yet-valid"],
)
def test_condition_violations_rejected(sp_keys: KeyPair, idp_keys: KeyPair, overrides: dict) -> None:
    _rejects(make_sp(sp_keys, idp_keys), sign(build_response(**overrides), idp_keys))


def test_in_response_to_mismatch_rejected(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    _rejects(make_sp(sp_keys, idp_keys), sign(build_response(), idp_keys), request_id="_other")


def test_unsolicited_response_rejected(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    code = _rejects(make_sp(sp_keys, idp_keys), sign(build_response(in_response_to=False), idp_keys))
    assert code == "in_response_to"


def test_foreign_eppn_scope_rejected(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    code = _rejects(make_sp(sp_keys, idp_keys), sign(build_response(eppn="xnovak@evil.sk"), idp_keys))
    assert code == "subject_scope"


def test_missing_eppn_rejected(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    code = _rejects(make_sp(sp_keys, idp_keys), sign(build_response(eppn=None), idp_keys))
    assert code == "missing_subject"


def test_garbage_rejected(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    sp = make_sp(sp_keys, idp_keys)
    with pytest.raises(SamlValidationError):
        sp.validate({"SAMLResponse": "bm90IHhtbA==", "RelayState": "relay"}, REQUEST_ID)


def test_login_url_is_signed_and_forces_authentication(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    url, request_id = make_sp(sp_keys, idp_keys).login_url("relay123")
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == "https://idp.test/idp/profile/SAML2/Redirect/SSO"
    assert query["RelayState"] == ["relay123"]
    assert query["SigAlg"] == [C.RSA_SHA256]
    assert "Signature" in query
    assert request_id


PAIRWISE_VALUE = "MSPIFSGUMDNORF3HXPY6DVTLQHS2SR54@stuba.sk"


def pairwise_sp(sp_keys: KeyPair, idp_keys: KeyPair) -> SamlSP:
    """Pseudonymous safeID mode: STU sends a per-service random ID instead of the login."""
    return SamlSP(
        base_url=BASE,
        sp_cert=sp_keys[1],
        sp_key=sp_keys[0],
        idp_metadata_xml=idp_metadata(idp_keys[1]),
        idp_entity_id=IDP_ENTITY,
        identity_attribute="pairwise_id",
        entity_categories=["https://refeds.org/category/pseudonymous"],
        display_name="STUard – overenie MTF STU",
        description="Overenie členov Discord servera študentov MTF STU.",
    )


def as_pairwise(xml: str, value: str = PAIRWISE_VALUE) -> str:
    """Swap the eduPersonPrincipalName attribute for a pairwise-id one."""
    return xml.replace(
        'Name="urn:oid:1.3.6.1.4.1.5923.1.1.1.6" NameFormat="urn:oasis:names:tc:SAML:2.0:attrname-format:uri" '
        'FriendlyName="eduPersonPrincipalName"',
        'Name="urn:oasis:names:tc:SAML:attribute:pairwise-id" '
        'NameFormat="urn:oasis:names:tc:SAML:2.0:attrname-format:uri" FriendlyName="pairwise-id"',
    ).replace("xnovak@stuba.sk", value)


def test_pairwise_id_is_accepted_as_the_subject(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    identity = pairwise_sp(sp_keys, idp_keys).validate(post(sign(as_pairwise(build_response()), idp_keys)), REQUEST_ID)
    assert identity.subject == PAIRWISE_VALUE
    assert identity.scoped_affiliations == ["student@stuba.sk", "member@stuba.sk"]


def test_pairwise_id_from_a_foreign_scope_is_rejected(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    response = as_pairwise(build_response(), "MSPIFSGUMDNORF3HXPY6DVTLQHS2SR54@evil.sk")
    with pytest.raises(SamlValidationError) as info:
        pairwise_sp(sp_keys, idp_keys).validate(post(sign(response, idp_keys)), REQUEST_ID)
    assert info.value.code == "subject_scope"


def test_pairwise_mode_rejects_a_response_without_pairwise_id(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    with pytest.raises(SamlValidationError) as info:
        pairwise_sp(sp_keys, idp_keys).validate(post(sign(build_response(), idp_keys)), REQUEST_ID)
    assert info.value.code == "missing_subject"


def test_metadata_publishes_the_entity_category_and_service_info(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    metadata = pairwise_sp(sp_keys, idp_keys).metadata()
    assert "http://macedir.org/entity-category" in metadata
    assert "https://refeds.org/category/pseudonymous" in metadata
    assert "urn:oasis:names:tc:SAML:attribute:pairwise-id" in metadata  # requested attribute
    assert "STUard – overenie MTF STU" in metadata
    assert f"{BASE}/privacy" in metadata
    assert "BEGIN" not in metadata and "PRIVATE" not in metadata


def test_metadata(sp_keys: KeyPair, idp_keys: KeyPair) -> None:
    metadata = make_sp(sp_keys, idp_keys).metadata()
    assert 'entityID="https://verify.test/saml/metadata"' in metadata
    assert 'Location="https://verify.test/saml/acs"' in metadata
    assert 'AuthnRequestsSigned="true"' in metadata
    assert 'use="signing"' in metadata and 'use="encryption"' in metadata
    assert "urn:oid:1.3.6.1.4.1.5923.1.1.1.6" in metadata
    assert "BEGIN" not in metadata and "PRIVATE" not in metadata
