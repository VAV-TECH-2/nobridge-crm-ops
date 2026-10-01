#!/usr/bin/env bash
# Adds the Nobridge Finance auth-bridge env vars to ~/finance/.env.finance.
# Since 2026-10-01 Finance signs people in with the CRM's own session at
# app.nobridge.co/finance — no Google client any more.
# - generates a fresh HS256 session secret (re-running signs everyone out of Finance)
# - writes the Twenty API key passed as $1
# Idempotent: replaces any prior managed block. Backs up .env.finance first.
# Read-only against the CRM; never touches CRM containers/compose.
set -uo pipefail

ENV="$HOME/finance/.env.finance"
API_KEY="${1:?usage: wire-auth-env.sh <TWENTY_API_KEY>}"

[ -f "$ENV" ] || { echo "MISSING $ENV"; exit 1; }

cp "$ENV" "$ENV.bak.$(date +%Y%m%d-%H%M%S)"

SESSION="$(openssl rand -hex 32)"

# Remove any prior managed block, then append a fresh one.
sed -i '/# >>> nobridge-finance auth bridge >>>/,/# <<< nobridge-finance auth bridge <<</d' "$ENV"

cat >> "$ENV" <<EOF
# >>> nobridge-finance auth bridge >>>
FINANCE_SESSION_SECRET=$SESSION
TWENTY_METADATA_URL=https://crm.nobridge.co/metadata
TWENTY_API_KEY=$API_KEY
FULL_ACCESS_ROLES=Admin,Manager
# <<< nobridge-finance auth bridge <<<
EOF

echo "OK -> $ENV (values masked):"
sed -E 's/=.*/=.../' "$ENV"
