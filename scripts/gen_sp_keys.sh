#!/usr/bin/env bash
# Generate the SAML Service Provider key pair (signing + encryption). Self-signed certificates are normal for SAML.
set -euo pipefail
cd "$(dirname "$0")/.."

host="${1:?usage: scripts/gen_sp_keys.sh <public host, e.g. verify.example.sk>}"
mkdir -p secrets
if [[ -e secrets/sp.key ]]; then
  echo "secrets/sp.key already exists — not overwriting it (an existing registration may rely on this certificate)." >&2
  exit 1
fi

umask 077
openssl req -x509 -newkey rsa:3072 -sha256 -nodes -days 3650 \
  -subj "/CN=${host}" -keyout secrets/sp.key -out secrets/sp.crt 2>/dev/null
chmod 600 secrets/sp.key
chmod 644 secrets/sp.crt

echo "Created secrets/sp.key and secrets/sp.crt"
echo "Certificate fingerprint (include it if you apply for registration):"
openssl x509 -in secrets/sp.crt -noout -fingerprint -sha256
