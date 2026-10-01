#!/usr/bin/env bash
# 2026-10-01 unification cutover: CRM + Finance + Ops onto app.nobridge.co with one
# sign-in. Run ON THE VM as azureuser, from ~/unify/, AFTER staging:
#   ~/twenty/front-build.new                      CRM front with the returnToPath hand-off
#   ~/finance/finance-image.tar.gz                Finance image built with basePath /finance
#   /opt/heydeal-automations-dashboard/dashboard.py.new
#   ~/unify/Caddyfile.unified                     (deploy/Caddyfile.unified)
# Backups of everything this touches are in ~/unify-backup-20261001 (+ Azure snapshot
# snap-pre-unify-20261001, DB dumps). Undo with ./rollback.sh.
#
# Each step can be run alone: ./cutover.sh twenty|finance|ops|caddy  (default: all, in order)
set -euo pipefail

STEP="${1:-all}"
DASH=/opt/heydeal-automations-dashboard

wait_http() {  # wait_http <url> <expected-code> <seconds>
  local url=$1 want=$2 secs=$3 code=""
  for _ in $(seq 1 "$secs"); do
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 "$url" || true)
    [ "$code" = "$want" ] && { echo "  ok $url -> $code"; return 0; }
    sleep 1
  done
  echo "  FAILED $url -> $code (wanted $want)"; return 1
}

set_env() {  # set_env <file> <KEY> <value>   (replace or append, in place)
  local file=$1 key=$2 value=$3 as=""
  [ -w "$file" ] || as=sudo   # root-owned files under /opt only; never chown a user file
  if $as grep -q "^${key}=" "$file"; then
    $as sed -i "s|^${key}=.*|${key}=${value}|" "$file"
  else
    echo "${key}=${value}" | $as tee -a "$file" >/dev/null
  fi
}

step_twenty() {
  echo "== CRM: SERVER_URL/FRONTEND_URL -> app.nobridge.co, new front bundle"
  test -d ~/twenty/front-build.new
  cd ~/twenty
  set_env .env SERVER_URL https://app.nobridge.co
  set_env .env FRONTEND_URL https://app.nobridge.co
  # Google callbacks stay on crm.nobridge.co: those URLs are registered in GCP, and
  # Twenty passes its sign-in state in the URL, not a cookie, so the host can differ.
  grep -E '^(SERVER_URL|FRONTEND_URL|AUTH_GOOGLE_CALLBACK_URL|AUTH_GOOGLE_APIS_CALLBACK_URL|TAG)=' .env
  mv front-build front-build.bak.20261001-preunify
  mv front-build.new front-build
  docker compose up -d          # env changed -> recreates server + worker; image tag unchanged
  wait_http http://127.0.0.1:3000/healthz 200 180
  docker ps --filter name=twenty --format '  {{.Names}} {{.Image}} {{.Status}}'
}

step_finance() {
  echo "== Finance: image built with basePath /finance"
  cd ~/finance
  test -f finance-image.tar.gz
  set_env .env.finance NEXT_PUBLIC_BASE_PATH /finance
  ./deploy-finance-image.sh
  wait_http http://127.0.0.1:3100/finance/api/health 200 60
  echo "  unauthenticated page -> $(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' http://127.0.0.1:3100/finance)"
}

step_ops() {
  echo "== Ops dashboard: CRM sign-in, served under /ops"
  test -f $DASH/dashboard.py.new
  set_env $DASH/dashboard-auth.env DASH_BASE_PATH /ops
  set_env $DASH/dashboard-auth.env TWENTY_METADATA_URL http://127.0.0.1:3000/metadata
  sudo cp -a $DASH/dashboard.py $DASH/dashboard.py.bak-pre-unify-20261001
  sudo mv $DASH/dashboard.py.new $DASH/dashboard.py
  sudo systemctl restart heydeal-automations-dashboard
  wait_http http://127.0.0.1:3200/healthz 200 30
  echo "  unauthenticated page -> $(curl -s -o /dev/null -w '%{http_code} %{redirect_url}' http://127.0.0.1:3200/)"
}

step_caddy() {
  echo "== Caddy: final unified config"
  caddy validate --config ~/unify/Caddyfile.unified --adapter caddyfile 2>&1 | tail -1
  sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak.20261001-stage1
  sudo cp ~/unify/Caddyfile.unified /etc/caddy/Caddyfile
  sudo systemctl reload caddy
  sleep 2
  systemctl is-active caddy
}

case "$STEP" in
  twenty) step_twenty ;;
  finance) step_finance ;;
  ops) step_ops ;;
  caddy) step_caddy ;;
  all) step_twenty; step_finance; step_ops; step_caddy ;;
  *) echo "unknown step: $STEP"; exit 2 ;;
esac
echo "== done: $STEP"
