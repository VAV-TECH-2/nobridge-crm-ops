#!/usr/bin/env bash
# Writes /opt/heydeal-automations-dashboard/dashboard-auth.env for the ops dashboard
# at app.nobridge.co/ops. Since 2026-10-01 it signs people in with the CRM's own
# session (same origin) — no Google client any more:
#   - DASH_BASE_PATH=/ops (Caddy strips the prefix; the app re-adds it)
#   - the CRM over loopback for currentUser + the role lookup
#   - reuses the Twenty API key already wired for Finance (~/finance/.env.finance)
#   - generates (or PRESERVES) an HS256 session secret
#   - PRESERVES CALLINTEL_INTERNAL_SECRET (Calls tab approve/reject; the pre-2026-10
#     version of this script dropped it on a re-run)
# Idempotent: an existing DASH_SESSION_SECRET is kept, so re-running does NOT log
# everyone out. Backs up any existing file. Run ON THE VM (needs sudo for /opt).
set -uo pipefail

OUT="/opt/heydeal-automations-dashboard/dashboard-auth.env"
FIN_ENV="$HOME/finance/.env.finance"

[ -f "$FIN_ENV" ]    || { echo "MISSING $FIN_ENV (wire Finance auth first)"; exit 1; }

# Reuse Finance's Twenty API key (role lookup).
APIKEY="$(grep -E '^TWENTY_API_KEY='         "$FIN_ENV"    | head -n1 | cut -d= -f2-)"
[ -n "$APIKEY" ] || { echo "ERROR: TWENTY_API_KEY not in $FIN_ENV"; exit 1; }

# Preserve the session secret (so a re-run doesn't invalidate live sessions) and the
# engine's shared secret (without it the Calls tab cannot approve/reject).
SECRET=""
CALLINTEL=""
if sudo test -f "$OUT"; then
  SECRET="$(sudo grep -E '^DASH_SESSION_SECRET=' "$OUT" | head -n1 | cut -d= -f2- || true)"
  CALLINTEL="$(sudo grep -E '^CALLINTEL_INTERNAL_SECRET=' "$OUT" | head -n1 | cut -d= -f2- || true)"
  sudo cp "$OUT" "$OUT.bak.$(date +%Y%m%d-%H%M%S)"
fi
[ -n "$CALLINTEL" ] || echo "WARNING: no CALLINTEL_INTERNAL_SECRET to keep — Calls approve/reject will 503"
[ -n "$SECRET" ] || SECRET="$(openssl rand -hex 32)"

sudo mkdir -p "$(dirname "$OUT")"
sudo tee "$OUT" >/dev/null <<EOF
# Managed by deploy/dashboard/wire-dashboard-auth.sh — app.nobridge.co/ops dashboard.
# CRM-session sign-in + Twenty CRM role check (Admin/Manager only), like Nobridge Finance.
DASH_SESSION_SECRET=$SECRET
DASH_SESSION_TTL_SECONDS=28800
DASH_BASE_PATH=/ops
TWENTY_METADATA_URL=http://127.0.0.1:3000/metadata
TWENTY_API_KEY=$APIKEY
FULL_ACCESS_ROLES=Admin,Manager
CALLINTEL_INTERNAL_SECRET=$CALLINTEL
EOF
sudo chown root:root "$OUT"
sudo chmod 600 "$OUT"

echo "OK -> $OUT (values masked):"
sudo sed -E 's/=.*/=.../' "$OUT"
echo "Now: sudo systemctl restart heydeal-automations-dashboard"
