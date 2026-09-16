"""SAML 2.0 Service Provider for idp.stuba.sk (python3-saml in strict mode, plus extra checks)."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from lxml import etree
from onelogin.saml2.auth import OneLogin_Saml2_Auth
from onelogin.saml2.constants import OneLogin_Saml2_Constants as C
from onelogin.saml2.idp_metadata_parser import OneLogin_Saml2_IdPMetadataParser
from onelogin.saml2.metadata import OneLogin_Saml2_Metadata
from onelogin.saml2.settings import OneLogin_Saml2_Settings
from onelogin.saml2.xml_utils import OneLogin_Saml2_XML

from stuard.domain.mapping import scope_allowed

if TYPE_CHECKING:
    from stuard.config import AppConfig
    from stuard.settings import Settings

log = logging.getLogger(__name__)

ATTRNAME_URI = "urn:oasis:names:tc:SAML:2.0:attrname-format:uri"
OID_EPPN = "urn:oid:1.3.6.1.4.1.5923.1.1.1.6"
OID_SCOPED_AFFILIATION = "urn:oid:1.3.6.1.4.1.5923.1.1.1.9"
OID_AFFILIATION = "urn:oid:1.3.6.1.4.1.5923.1.1.1.1"
PAIRWISE_ID = "urn:oasis:names:tc:SAML:attribute:pairwise-id"
# Metadata namespaces used for entity categories (what federations register) and the service description.
NS_MD = "urn:oasis:names:tc:SAML:2.0:metadata"
NS_MDATTR = "urn:oasis:names:tc:SAML:metadata:attribute"
NS_MDUI = "urn:oasis:names:tc:SAML:metadata:ui"
NS_SAML = "urn:oasis:names:tc:SAML:2.0:assertion"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
ENTITY_CATEGORY = "http://macedir.org/entity-category"


class SamlValidationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SamlIdentity:
    subject: str
    scoped_affiliations: list[str]
    affiliations: list[str]
    assertion_id: str
    not_on_or_after: int | None


def _values(attributes: dict[str, Any], friendly: dict[str, Any], name: str, friendly_name: str) -> list[str]:
    raw = attributes.get(name) or friendly.get(friendly_name) or []
    return [v for v in raw if isinstance(v, str) and v.strip()]


class SamlSP:
    def __init__(
        self,
        *,
        base_url: str,
        sp_cert: str,
        sp_key: str,
        idp_metadata_xml: str,
        idp_entity_id: str,
        identity_attribute: str = "eppn",
        allowed_scopes: Iterable[str] = ("stuba.sk",),
        force_authn: bool = True,
        contact_email: str | None = None,
        entity_categories: Iterable[str] = (),
        display_name: str = "STUard",
        description: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.idp_entity_id = idp_entity_id
        self.identity_attribute = identity_attribute
        self.allowed_scopes = list(allowed_scopes)
        self.force_authn = force_authn
        self.entity_categories = list(entity_categories)
        self.display_name = display_name
        self.description = description

        parsed = OneLogin_Saml2_IdPMetadataParser.parse(
            idp_metadata_xml, required_sso_binding=C.BINDING_HTTP_REDIRECT, entity_id=idp_entity_id
        )
        idp = parsed.get("idp") or {}
        if not idp.get("singleSignOnService", {}).get("url"):
            raise ValueError(f"IdP {idp_entity_id!r} not found in metadata or it has no HTTP-Redirect SSO endpoint")
        if not idp.get("x509cert") and not idp.get("x509certMulti"):
            raise ValueError("IdP metadata contains no signing certificate")

        subject_attr = (
            (PAIRWISE_ID, "pairwise-id")
            if identity_attribute == "pairwise_id"
            else (OID_EPPN, "eduPersonPrincipalName")
        )
        requested = [
            {
                "name": OID_SCOPED_AFFILIATION,
                "friendlyName": "eduPersonScopedAffiliation",
                "nameFormat": ATTRNAME_URI,
                "isRequired": True,
            },
        ]
        if identity_attribute != "persistent_nameid":
            requested.insert(
                0,
                {
                    "name": subject_attr[0],
                    "friendlyName": subject_attr[1],
                    "nameFormat": ATTRNAME_URI,
                    "isRequired": True,
                },
            )

        settings: dict[str, Any] = {
            "strict": True,
            "debug": False,
            "sp": {
                "entityId": self.entity_id,
                "assertionConsumerService": {"url": self.acs_url, "binding": C.BINDING_HTTP_POST},
                "NameIDFormat": (
                    C.NAMEID_PERSISTENT if identity_attribute == "persistent_nameid" else C.NAMEID_UNSPECIFIED
                ),
                "x509cert": sp_cert,
                "privateKey": sp_key,
                "attributeConsumingService": {
                    "serviceName": display_name,
                    "serviceDescription": description or display_name,
                    "requestedAttributes": requested,
                },
            },
            "idp": idp,
            "security": {
                "authnRequestsSigned": True,
                "logoutRequestSigned": False,
                "logoutResponseSigned": False,
                "signMetadata": False,
                # python3-saml always rejects responses with no signature at all; either level may be signed.
                "wantMessagesSigned": False,
                "wantAssertionsSigned": False,
                "wantAssertionsEncrypted": False,
                "wantNameId": identity_attribute == "persistent_nameid",
                "wantNameIdEncrypted": False,
                "wantAttributeStatement": True,
                "requestedAuthnContext": False,
                "failOnAuthnContextMismatch": False,
                "rejectDeprecatedAlgorithm": True,
                "allowRepeatAttributeName": True,
                "wantXMLValidation": True,
                "signatureAlgorithm": C.RSA_SHA256,
                "digestAlgorithm": C.SHA256,
            },
        }
        if contact_email:
            settings["contactPerson"] = {"technical": {"givenName": "STUard", "emailAddress": contact_email}}
        self._settings = OneLogin_Saml2_Settings(settings, sp_validation_only=False)

    @property
    def entity_id(self) -> str:
        return f"{self.base_url}/saml/metadata"

    @property
    def acs_url(self) -> str:
        return f"{self.base_url}/saml/acs"

    def _request(self, path: str, *, post: dict[str, str] | None = None) -> dict[str, Any]:
        # Built from PUBLIC_BASE_URL, never from request headers, so Destination/Recipient checks are meaningful.
        parts = urlsplit(self.base_url)
        return {
            "https": "on" if parts.scheme == "https" else "off",
            "http_host": parts.netloc,
            "script_name": parts.path + path,
            "get_data": {},
            "post_data": post or {},
        }

    def login_url(self, relay_state: str) -> tuple[str, str]:
        auth = OneLogin_Saml2_Auth(self._request("/saml/login"), self._settings)
        url = auth.login(return_to=relay_state, force_authn=self.force_authn, set_nameid_policy=False)
        return url, auth.get_last_request_id()

    def metadata(self) -> str:
        xml = OneLogin_Saml2_Metadata.builder(
            self._settings.get_sp_data(),
            authnsign=True,
            wsign=False,
            contacts=self._settings.get_contacts(),
            organization=self._settings.get_organization(),
        )
        # Publish the certificate for encryption too: Shibboleth encrypts assertions by default.
        xml = OneLogin_Saml2_Metadata.add_x509_key_descriptors(xml, self._settings.get_sp_cert(), True)
        return self._augment_metadata(xml.decode("utf-8") if isinstance(xml, bytes) else xml)

    def _augment_metadata(self, xml: str) -> str:
        """Add the entity categories and the service description a federation needs to register the service."""
        parser = etree.XMLParser(resolve_entities=False, no_network=True)
        root = etree.fromstring(xml.encode("utf-8"), parser)

        if self.entity_categories:
            extensions = etree.Element(f"{{{NS_MD}}}Extensions", nsmap={"mdattr": NS_MDATTR, "saml": NS_SAML})
            entity_attributes = etree.SubElement(extensions, f"{{{NS_MDATTR}}}EntityAttributes")
            attribute = etree.SubElement(
                entity_attributes,
                f"{{{NS_SAML}}}Attribute",
                attrib={"Name": ENTITY_CATEGORY, "NameFormat": ATTRNAME_URI},
            )
            for category in self.entity_categories:
                etree.SubElement(attribute, f"{{{NS_SAML}}}AttributeValue").text = category
            root.insert(0, extensions)  # Extensions must come before the role descriptors

        descriptor = root.find(f"{{{NS_MD}}}SPSSODescriptor")
        if descriptor is not None:
            ui_extensions = etree.Element(f"{{{NS_MD}}}Extensions", nsmap={"mdui": NS_MDUI})
            ui_info = etree.SubElement(ui_extensions, f"{{{NS_MDUI}}}UIInfo")
            for lang in ("sk", "en"):
                etree.SubElement(ui_info, f"{{{NS_MDUI}}}DisplayName", attrib={XML_LANG: lang}).text = self.display_name
                if self.description:
                    element = etree.SubElement(ui_info, f"{{{NS_MDUI}}}Description", attrib={XML_LANG: lang})
                    element.text = self.description
                privacy = etree.SubElement(ui_info, f"{{{NS_MDUI}}}PrivacyStatementURL", attrib={XML_LANG: lang})
                privacy.text = f"{self.base_url}/privacy"
            descriptor.insert(0, ui_extensions)

        return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode("utf-8")

    def validate(self, post_data: dict[str, str], request_id: str) -> SamlIdentity:
        """Blocking (XML signature crypto) — call via asyncio.to_thread."""
        auth = OneLogin_Saml2_Auth(self._request("/saml/acs", post=post_data), self._settings)
        try:
            auth.process_response(request_id=request_id)
        except Exception as exc:
            log.warning("SAML response could not be processed: %s", type(exc).__name__)
            raise SamlValidationError("malformed") from exc
        if auth.get_errors() or not auth.is_authenticated():
            log.warning("SAML response rejected: %s", auth.get_last_error_reason())
            raise SamlValidationError("invalid")

        # python3-saml only compares InResponseTo when present; unsolicited responses are not accepted here.
        root = OneLogin_Saml2_XML.to_etree(auth.get_last_response_xml())
        if root.get("InResponseTo") != request_id:
            raise SamlValidationError("in_response_to")
        assertion_id = auth.get_last_assertion_id()
        if not assertion_id:
            raise SamlValidationError("no_assertion_id")

        attributes = auth.get_attributes()
        friendly = auth.get_friendlyname_attributes()
        return SamlIdentity(
            subject=self._subject(auth, attributes, friendly),
            scoped_affiliations=_values(attributes, friendly, OID_SCOPED_AFFILIATION, "eduPersonScopedAffiliation"),
            affiliations=_values(attributes, friendly, OID_AFFILIATION, "eduPersonAffiliation"),
            assertion_id=assertion_id,
            not_on_or_after=auth.get_last_assertion_not_on_or_after(),
        )

    def _subject(self, auth: OneLogin_Saml2_Auth, attributes: dict[str, Any], friendly: dict[str, Any]) -> str:
        if self.identity_attribute == "persistent_nameid":
            name_id = auth.get_nameid()
            if auth.get_nameid_format() != C.NAMEID_PERSISTENT or not name_id:
                raise SamlValidationError("missing_subject")
            return f"{self.idp_entity_id}!{name_id}"
        if self.identity_attribute == "pairwise_id":
            values = _values(attributes, friendly, PAIRWISE_ID, "pairwise-id")
        else:
            values = _values(attributes, friendly, OID_EPPN, "eduPersonPrincipalName")
        if len(values) != 1:
            raise SamlValidationError("missing_subject")
        subject = values[0].strip()
        local, sep, scope = subject.rpartition("@")
        if not sep or not local or not scope_allowed(scope, self.allowed_scopes):
            raise SamlValidationError("subject_scope")
        return subject


def load_saml(settings: Settings, cfg: AppConfig) -> SamlSP | None:
    files = {
        "SAML_SP_KEY_FILE": settings.saml_sp_key_file,
        "SAML_SP_CERT_FILE": settings.saml_sp_cert_file,
        "SAML_IDP_METADATA_FILE": settings.saml_idp_metadata_file,
    }
    missing = [f"{name}={path}" for name, path in files.items() if not path.is_file()]
    if missing:
        log.warning("SAML service provider disabled, missing files: %s", ", ".join(missing))
        return None
    return SamlSP(
        base_url=settings.public_base_url,
        sp_cert=settings.saml_sp_cert_file.read_text(encoding="utf-8"),
        sp_key=settings.saml_sp_key_file.read_text(encoding="utf-8"),
        idp_metadata_xml=settings.saml_idp_metadata_file.read_text(encoding="utf-8"),
        idp_entity_id=settings.saml_idp_entity_id,
        identity_attribute=cfg.sso.identity_attribute,
        allowed_scopes=cfg.sso.allowed_scopes,
        force_authn=cfg.sso.force_authn,
        contact_email=cfg.privacy_contact or None,
        entity_categories=cfg.sso.entity_categories,
        display_name=cfg.sso.display_name,
        description=cfg.sso.description,
    )
