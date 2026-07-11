#!/usr/bin/env bash
# Writes /opt/heydeal-automations-dashboard/dashboard-auth.env — the Google-SSO
# auth env for the node.nobridge.co ops dashboard. Mirrors deploy/finance/wire-auth-env.sh:
#   - reuses the CRM's Google OAuth client (reads id/secret from ~/twenty/.env)
#   - reuses the Twenty API key already wired for Finance (~/finance/.env.finance)
#   - generates (or PRESERVES) an HS256 session secret
# Idempotent: an existing DASH_SESSION_SECRET is kept, so re-running does NOT log
# everyone out. Backs up any existing file. Run ON THE VM (needs sudo for /opt).
set -uo pipefail

OUT="/opt/heydeal-automations-dashboard/dashboard-auth.env"
TWENTY_ENV="$HOME/twenty/.env"
FIN_ENV="$HOME/finance/.env.finance"
REDIRECT_URI="https://node.nobridge.co/api/auth/google/callback"

[ -f "$TWENTY_ENV" ] || { echo "MISSING $TWENTY_ENV"; exit 1; }
[ -f "$FIN_ENV" ]    || { echo "MISSING $FIN_ENV (wire Finance auth first)"; exit 1; }

# Reuse the ONE shared Google client (CRM + Finance) and Finance's Twenty API key.
GID="$(grep -E '^AUTH_GOOGLE_CLIENT_ID='     "$TWENTY_ENV" | head -n1 | cut -d= -f2-)"
GSECRET="$(grep -E '^AUTH_GOOGLE_CLIENT_SECRET=' "$TWENTY_ENV" | head -n1 | cut -d= -f2-)"
APIKEY="$(grep -E '^TWENTY_API_KEY='         "$FIN_ENV"    | head -n1 | cut -d= -f2-)"

[ -n "$GID" ] && [ -n "$GSECRET" ] || { echo "ERROR: AUTH_GOOGLE_CLIENT_ID/_SECRET not in $TWENTY_ENV"; exit 1; }
[ -n "$APIKEY" ] || { echo "ERROR: TWENTY_API_KEY not in $FIN_ENV"; exit 1; }

# Preserve an existing session secret (so a re-run doesn't invalidate live sessions).
SECRET=""
if sudo test -f "$OUT"; then
  SECRET="$(sudo grep -E '^DASH_SESSION_SECRET=' "$OUT" | head -n1 | cut -d= -f2- || true)"
  sudo cp "$OUT" "$OUT.bak.$(date +%Y%m%d-%H%M%S)"
fi
[ -n "$SECRET" ] || SECRET="$(openssl rand -hex 32)"

sudo mkdir -p "$(dirname "$OUT")"
sudo tee "$OUT" >/dev/null <<EOF
# Managed by deploy/dashboard/wire-dashboard-auth.sh — node.nobridge.co ops dashboard.
# Google sign-in + Twenty CRM role check (Admin/Manager only), mirroring Nobridge Finance.
DASH_SESSION_SECRET=$SECRET
DASH_SESSION_TTL_SECONDS=28800
GOOGLE_CLIENT_ID=$GID
GOOGLE_CLIENT_SECRET=$GSECRET
GOOGLE_REDIRECT_URI=$REDIRECT_URI
TWENTY_METADATA_URL=https://crm.nobridge.co/metadata
TWENTY_API_KEY=$APIKEY
FULL_ACCESS_ROLES=Admin,Manager
EOF
sudo chown root:root "$OUT"
sudo chmod 600 "$OUT"

echo "OK -> $OUT (values masked):"
sudo sed -E 's/=.*/=.../' "$OUT"
echo "Now: sudo systemctl restart heydeal-automations-dashboard"
