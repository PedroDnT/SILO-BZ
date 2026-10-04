#!/bin/sh
# Entry point of the engine image (map #510, slice E).
#
# On Cloudflare the Worker restricts the Container's egress to an allow-list,
# which for HTTPS means the platform intercepts TLS and drops its own CA at
# CF_CA shortly after the start. urllib (silo-mcp) and httpx (the LLM SDKs)
# both read SSL_CERT_FILE, so it points at a private bundle: certifi's roots at
# once, and certifi plus that CA as soon as the file appears (written to a
# temporary name, then moved, so a reader never sees half a file). Elsewhere
# (CI, docker run) SILO_TRUST_CF_CA is unset and nothing waits.
set -eu

CF_CA=/etc/cloudflare/certs/cloudflare-containers-ca.crt
BUNDLE=/tmp/silo-ca-bundle.pem
# certifi's roots when installed, else Debian's system bundle. Never fatal: a
# missing bundle must not keep the server from starting.
ROOTS=$(python -c 'import certifi; print(certifi.where())' 2>/dev/null || echo /etc/ssl/certs/ca-certificates.crt)
if [ -s "$ROOTS" ] && cp "$ROOTS" "$BUNDLE"; then
  export SSL_CERT_FILE="$BUNDLE"
else
  echo "no CA bundle found; SSL_CERT_FILE left unset"
fi

if [ "${SILO_TRUST_CF_CA:-0}" = 1 ]; then
  (
    i=0
    while [ "$i" -lt 240 ]; do
      if [ -s "$CF_CA" ] && [ -s "$ROOTS" ]; then
        cat "$ROOTS" "$CF_CA" > "$BUNDLE.new" && mv "$BUNDLE.new" "$BUNDLE"
        echo "egress CA trusted"
        exit 0
      fi
      i=$((i + 1))
      sleep 0.5
    done
    echo "egress CA not found after 120 s"
  ) &
fi

exec gunicorn --bind "0.0.0.0:${PORT}" --workers 1 --threads 4 --timeout 600 --graceful-timeout 30 \
  --access-logfile - 'src.portfolio.server:wsgi()'
