"""Download and pin the STU IdP metadata and print its certificate fingerprints.

Confirm the fingerprints with idp@stuba.sk before trusting the file — the bot trusts exactly these certificates.

    .venv/bin/python scripts/fetch_idp_metadata.py
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import sys
import urllib.request
from pathlib import Path

from lxml import etree

DEFAULT_ENTITY = "https://idp.stuba.sk/idp/shibboleth"
NS = {"md": "urn:oasis:names:tc:SAML:2.0:metadata", "ds": "http://www.w3.org/2000/09/xmldsig#"}
MAX_BYTES = 2_000_000


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=DEFAULT_ENTITY, help="metadata URL (default: %(default)s)")
    parser.add_argument("--entity-id", default=DEFAULT_ENTITY)
    parser.add_argument("--out", default="saml/idp_metadata.xml")
    args = parser.parse_args()
    if not args.url.startswith("https://"):
        print("refusing to fetch metadata over plain HTTP", file=sys.stderr)
        return 2

    with urllib.request.urlopen(args.url, timeout=20) as resp:
        data = resp.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        print("metadata is suspiciously large", file=sys.stderr)
        return 1

    root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
    if root.get("entityID") == args.entity_id:
        entity = root
    else:
        entity = next(
            (e for e in root.iterfind(".//md:EntityDescriptor", NS) if e.get("entityID") == args.entity_id), None
        )
    if entity is None or entity.find("md:IDPSSODescriptor", NS) is None:
        print(f"no IdP with entityID {args.entity_id} in the metadata", file=sys.stderr)
        return 1

    print(f"IdP {args.entity_id}")
    for descriptor in entity.find("md:IDPSSODescriptor", NS).iterfind("md:KeyDescriptor", NS):
        use = descriptor.get("use", "signing+encryption")
        for cert in descriptor.iterfind(".//ds:X509Certificate", NS):
            der = base64.b64decode("".join((cert.text or "").split()))
            fingerprint = ":".join(f"{b:02X}" for b in hashlib.sha256(der).digest())
            print(f"  {use:<20} SHA256 {fingerprint}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    print(f"saved {out}. Confirm the signing fingerprints with idp@stuba.sk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
