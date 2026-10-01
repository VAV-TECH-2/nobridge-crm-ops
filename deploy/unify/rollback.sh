#!/usr/bin/env bash
# Undo the 2026-10-01 unification (cutover.sh), back to three hosts with three
# Google sign-ins. Run ON THE VM as azureuser. Restores the files saved in
# ~/unify-backup-20261001 and the pre-unify images/bundles. app.nobridge.co keeps
# resolving (DNS) but goes back to stage 1 (CRM only) unless you also remove it.
#
# ./rollback.sh twenty|finance|ops|caddy   (default: all, in reverse order)
set -euo pipefail

STEP="${1:-all}"
B=~/unify-backup-20261001
DASH=/opt/heydeal-automations-dashboard

roll_caddy() {
  echo "== Caddy: back to the pre-unify Caddyfile"
  sudo cp $B/Caddyfile /etc/caddy/Caddyfile
  sudo systemctl reload caddy && systemctl is-active caddy
}

roll_ops() {
  echo "== Ops dashboard: previous code + env"
  sudo cp -a $B/dashboard-opt/dashboard.py $DASH/dashboard.py
  sudo cp -a $B/dashboard-opt/dashboard-auth.env $DASH/dashboard-auth.env
  sudo systemctl restart heydeal-automations-dashboard
  sleep 2; curl -s -o /dev/null -w '  healthz %{http_code}\n' http://127.0.0.1:3200/healthz
}

roll_finance() {
  echo "== Finance: pre-unify image + env"
  cd ~/finance
  cp -a $B/env.finance .env.finance
  docker tag nobridge-finance:pre-unify nobridge-finance:latest
  docker compose -f docker-compose.finance.yml up -d --force-recreate finance
  sleep 6; curl -s -o /dev/null -w '  health %{http_code}\n' http://127.0.0.1:3100/api/health
}

roll_twenty() {
  echo "== CRM: previous env + front bundle"
  cd ~/twenty
  cp -a $B/twenty.env .env
  if [ -d front-build.bak.20261001-preunify ]; then
    rm -rf front-build.unify-rolledback && mv front-build front-build.unify-rolledback
    mv front-build.bak.20261001-preunify front-build
  fi
  docker compose up -d
  for _ in $(seq 1 180); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:3000/healthz)" = 200 ] && break; sleep 1
  done
  curl -s -o /dev/null -w '  healthz %{http_code}\n' http://127.0.0.1:3000/healthz
}

case "$STEP" in
  caddy) roll_caddy ;;
  ops) roll_ops ;;
  finance) roll_finance ;;
  twenty) roll_twenty ;;
  all) roll_caddy; roll_ops; roll_finance; roll_twenty ;;
  *) echo "unknown step: $STEP"; exit 2 ;;
esac
echo "== rolled back: $STEP"
