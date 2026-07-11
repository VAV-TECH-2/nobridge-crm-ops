#!/usr/bin/env bash
# Adds the Nobridge Finance auth-bridge env vars to ~/finance/.env.finance.
# - reuses the CRM's Google OAuth client (reads id/secret from ~/twenty/.env)
# - generates a fresh HS256 session secret
# - writes the Twenty API key passed as $1
# Idempotent: replaces any prior managed block. Backs up .env.finance first.
# Read-only against the CRM; never touches CRM containers/compose.
set -uo pipefail

ENV="$HOME/finance/.env.finance"
TWENTY_ENV="$HOME/twenty/.env"
API_KEY="${1:?usage: wire-auth-env.sh <TWENTY_API_KEY>}"

[ -f "$ENV" ] || { echo "MISSING $ENV"; exit 1; }
[ -f "$TWENTY_ENV" ] || { echo "MISSING $TWENTY_ENV"; exit 1; }

cp "$ENV" "$ENV.bak.$(date +%Y%m%d-%H%M%S)"

GID="$(grep '^AUTH_GOOGLE_CLIENT_ID=' "$TWENTY_ENV" | cut -d= -f2- || true)"
GSECRET="$(grep '^AUTH_GOOGLE_CLIENT_SECRET=' "$TWENTY_ENV" | cut -d= -f2- || true)"
SESSION="$(openssl rand -hex 32)"

if [ -z "$GID" ] || [ -z "$GSECRET" ]; then
  echo "ERROR: AUTH_GOOGLE_CLIENT_ID / _SECRET not found in $TWENTY_ENV"
  exit 1
fi

# Remove any prior managed block, then append a fresh one.
sed -i '/# >>> nobridge-finance auth bridge >>>/,/# <<< nobridge-finance auth bridge <<</d' "$ENV"

cat >> "$ENV" <<EOF
# >>> nobridge-finance auth bridge >>>
FINANCE_SESSION_SECRET=$SESSION
TWENTY_METADATA_URL=https://crm.nobridge.co/metadata
TWENTY_API_KEY=$API_KEY
FULL_ACCESS_ROLES=Admin,Manager
GOOGLE_CLIENT_ID=$GID
GOOGLE_CLIENT_SECRET=$GSECRET
GOOGLE_REDIRECT_URI=https://fin.nobridge.co/api/auth/google/callback
# <<< nobridge-finance auth bridge <<<
EOF

echo "OK -> $ENV (values masked):"
sed -E 's/=.*/=.../' "$ENV"
